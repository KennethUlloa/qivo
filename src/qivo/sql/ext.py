from contextvars import ContextVar

from flask import Flask, current_app
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from werkzeug.local import LocalProxy

from qivo.ext.base import BaseExtension

_session_context: ContextVar[Session | None] = ContextVar(
    "db_session",
    default=None,
)


class SQL(BaseExtension):
    name = "qivo.sql"

    engine: Engine
    _factory: sessionmaker[Session]

    def __init__(
        self,
        app: Flask | None = None,
        *,
        engine: Engine | None = None,
        options: dict | None = None,
    ):
        super().__init__(app)

        if engine is not None:
            self.engine = engine

        else:
            self._validate_config(app)

            self.engine = create_engine(
                app.config["SQLALCHEMY_DATABASE_URI"],
                **(options or app.config.get("SQLALCHEMY_ENGINE_OPTIONS", {})),
            )

        self._factory = sessionmaker(bind=self.engine)

    def setup(self, app: Flask):
        @app.teardown_appcontext
        def close_session(exception: BaseException | None = None):
            session = _session_context.get()

            if session is not None:
                session.close()
                _session_context.set(None)

    def _validate_config(self, app: Flask):
        if app.config["SQLALCHEMY_DATABASE_URI"] is None:
            raise ValueError("SQLALCHEMY_DATABASE_URI is not set")

    def get_session(self) -> Session:
        if self._factory is None:
            raise RuntimeError("SQL extension is not initialized")

        session = _session_context.get()

        if session is None:
            session = self._factory()
            _session_context.set(session)

        return session

    @property
    def session(self) -> Session:
        return self.get_session()


def _get_sql() -> SQL:
    ext = current_app.extensions.get("qivo.sql")

    if ext is None or not isinstance(ext, SQL):
        raise RuntimeError("SQL is not attached to the app")

    return ext


def _get_db_session() -> Session:
    return _get_sql().get_session()


db: Session = LocalProxy(_get_db_session, unbound_message="Working outside of an application context")
