import json
import secrets
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from flask import Flask, Request, Response
from flask.sessions import SessionInterface, SessionMixin
from sqlalchemy import JSON, DateTime, String, delete, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, mapped_column, sessionmaker

if TYPE_CHECKING:
    from qivo.db.sql import Model

_SID_BYTES = 32
_MAX_SID_LENGTH = 64
_MISSING_TABLE_HINTS = ("no such table", "does not exist", "undefined table")


@dataclass(frozen=True)
class SessionConfig:
    """How a server side session is stored and how long its rows live."""

    table: str = "qivo_sessions"
    lifetime: timedelta = timedelta(days=31)
    cleanup_interval: int = 100


def session_model(base: type["Model"], table: str = "qivo_sessions") -> type["Model"]:
    """Build, and remember on the base, the model that holds the session rows."""

    cached = base.__dict__.get("__qivo_session_model__")
    if cached is not None:
        if cached.__tablename__ != table:
            raise RuntimeError(
                f"The model base {base.__name__} already stores sessions in "
                f"{cached.__tablename__!r}; use one model base per session table"
            )
        return cached

    model = type(
        f"{base.__name__}Session",
        (base,),
        {
            "__tablename__": table,
            "sid": mapped_column(String(_MAX_SID_LENGTH), primary_key=True),
            "data": mapped_column(JSON, nullable=False),
            "expires_at": mapped_column(DateTime(timezone=True), index=True),
        },
    )
    base.__qivo_session_model__ = model
    return model


def prune_sessions(
    base: type["Model"],
    factory: Engine | sessionmaker[Session] | None = None,
    *,
    now: datetime | None = None,
) -> int:
    """Delete the expired session rows of the model base and count them."""

    model = base.__dict__.get("__qivo_session_model__")
    if model is None:
        raise RuntimeError(
            f"The model base {base.__name__} has no session table; attach "
            "DatabaseSessions to the app or enable it in qivo.toml"
        )

    return SessionStore(model, session_factory(base, factory)).prune(now)


class ServerSideSession(dict, SessionMixin):
    """The session dict; its data lives in a database row instead of a cookie."""

    def __init__(self, data: dict[str, Any] | None = None, sid: str | None = None):
        super().__init__(data or {})
        self.sid = sid
        self.modified = False

    def __setitem__(self, key: str, value: Any) -> None:
        self.modified = True
        dict.__setitem__(self, key, value)

    def __delitem__(self, key: str) -> None:
        self.modified = True
        dict.__delitem__(self, key)

    def update(self, *args: Any, **kwargs: Any) -> None:
        self.modified = True
        dict.update(self, *args, **kwargs)

    def setdefault(self, key: str, default: Any = None) -> Any:
        self.modified = True
        return dict.setdefault(self, key, default)

    def pop(self, *args: Any) -> Any:
        self.modified = True
        return dict.pop(self, *args)

    def popitem(self) -> tuple[str, Any]:
        self.modified = True
        return dict.popitem(self)

    def clear(self) -> None:
        self.modified = True
        dict.clear(self)

    def __ior__(self, other: Any) -> ServerSideSession:
        self.modified = True
        dict.update(self, other)
        return self


class SessionStore:
    """Reads and writes session rows with a session of its own.

    It never touches the ambient or the transaction session: rows are written at
    the end of the response, where the request session has already been served.
    """

    def __init__(
        self, model: type["Model"], factory: sessionmaker[Session] | Engine
    ) -> None:
        self.model = model
        self._factory = (
            sessionmaker(factory) if isinstance(factory, Engine) else factory
        )

    def load(self, sid: str) -> dict[str, Any] | None:
        """Return the data of a live session, or None when it is gone or expired."""

        with self._session() as session:
            row = session.scalars(
                select(self.model).where(
                    self.model.sid == sid,
                    or_(
                        self.model.expires_at.is_(None),
                        self.model.expires_at > _utcnow(),
                    ),
                )
            ).first()

            return None if row is None else dict(row.data)

    def store(self, sid: str, data: dict[str, Any], expires_at: datetime) -> None:
        """Insert or update one session row."""

        _ensure_json(data)

        with self._session() as session:
            row = session.get(self.model, sid)
            if row is None:
                row = self.model(sid=sid)
                session.add(row)

            row.data = data
            row.expires_at = expires_at
            session.commit()

    def remove(self, sid: str) -> None:
        """Delete one session row, if it is still there."""

        with self._session() as session:
            session.execute(delete(self.model).where(self.model.sid == sid))
            session.commit()

    def prune(self, now: datetime | None = None) -> int:
        """Delete every expired row and return how many were removed."""

        with self._session() as session:
            result = session.execute(
                delete(self.model).where(
                    self.model.expires_at.is_not(None),
                    self.model.expires_at < (now or _utcnow()),
                )
            )
            session.commit()
            return result.rowcount

    def create_sid(self) -> str:
        return secrets.token_urlsafe(_SID_BYTES)

    @contextmanager
    def _session(self) -> Iterator[Session]:
        session = self._factory()
        try:
            yield session
        except DBAPIError as error:
            missing = _missing_table_error(error, self.model)
            if missing is None:
                raise
            raise missing from error
        finally:
            session.close()


class DatabaseSessionInterface(SessionInterface):
    """Keeps the session data in the database; the cookie only carries its id."""

    def __init__(self, store: SessionStore, config: SessionConfig) -> None:
        self.store = store
        self.config = config
        self._requests = 0
        self._lock = threading.Lock()

    def open_session(self, app: Flask, request: Request) -> ServerSideSession:
        self._sweep_expired()

        sid = request.cookies.get(self.get_cookie_name(app))
        if not sid or len(sid) > _MAX_SID_LENGTH:
            return ServerSideSession()

        data = self.store.load(sid)
        if data is None:
            return ServerSideSession()

        return ServerSideSession(data, sid=sid)

    def save_session(
        self, app: Flask, session: SessionMixin, response: Response
    ) -> None:
        if session.accessed:
            response.vary.add("Cookie")

        cookie = {
            "domain": self.get_cookie_domain(app),
            "path": self.get_cookie_path(app),
            "secure": self.get_cookie_secure(app),
            "partitioned": self.get_cookie_partitioned(app),
            "samesite": self.get_cookie_samesite(app),
            "httponly": self.get_cookie_httponly(app),
        }
        name = self.get_cookie_name(app)
        sid = getattr(session, "sid", None)

        if not session:
            if session.modified:
                if sid is not None:
                    self.store.remove(sid)
                response.delete_cookie(name, **cookie)
                response.vary.add("Cookie")
            return

        if not self.should_set_cookie(app, session):
            return

        sid = sid or self.store.create_sid()
        expires = self.get_expiration_time(app, session)
        lifetime = expires or _utcnow() + self.config.lifetime
        self.store.store(sid, dict(session), lifetime)
        session.sid = sid

        response.set_cookie(name, sid, expires=expires, **cookie)
        response.vary.add("Cookie")

    def _sweep_expired(self) -> None:
        interval = self.config.cleanup_interval
        if interval <= 0:
            return

        with self._lock:
            self._requests += 1
            due = self._requests % interval == 0

        if due:
            self.store.prune()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_json(data: dict[str, Any]) -> None:
    """Refuse the values that a JSON column cannot hold, before touching the db."""

    try:
        json.dumps(data)
    except TypeError as error:
        raise RuntimeError(
            "The session holds a value that is not JSON serializable, for "
            "example a date or a custom object; store it as a primitive type "
            f"instead: {error}"
        ) from error


def session_factory(
    base: type["Model"], factory: Engine | sessionmaker[Session] | None = None
) -> sessionmaker[Session]:
    """Return the sessionmaker of the base, or wrap the given engine in one."""

    if factory is None:
        configured = getattr(base, "__qivo_session_factory__", None)
        if configured is None:
            raise RuntimeError(
                f"The model base {base.__name__} has no database attached; "
                "configure it with SQLEngine(app, model=Base) before using "
                "database sessions"
            )
        return configured

    return sessionmaker(factory) if isinstance(factory, Engine) else factory


def _missing_table_error(
    error: DBAPIError, model: type["Model"]
) -> RuntimeError | None:
    """Point at the missing migration instead of a bare driver message."""

    message = str(error.orig or error).lower()
    if not any(hint in message for hint in _MISSING_TABLE_HINTS):
        return None

    return RuntimeError(
        f"The table {model.__tablename__} does not exist. Create it with "
        '`qivo migrate --message "sessions"` and `qivo migrate:apply`'
    )