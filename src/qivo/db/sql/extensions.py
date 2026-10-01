from collections.abc import Callable, Mapping, Sequence
from datetime import timedelta
from typing import Any, Protocol

from flask.sessions import SessionInterface
from sqlalchemy import Engine

from qivo.db.sql import Model, SQLAlchemyConfig, close_session
from qivo.db.sql.sessions import (
    DatabaseSessionInterface,
    FlaskSessionModel,
    SessionConfig,
    SessionStore,
    session_factory,
)


class ConfigurableApp(Protocol):
    config: Mapping[str, Any]
    extensions: dict[str, Any]
    session_interface: SessionInterface

    def teardown_request(
        self, func: Callable[[BaseException | None], Any]
    ) -> Any: ...


class SQLEngine:
    def __init__(
        self,
        app: ConfigurableApp | None = None,
        *,
        model: type[Model] | None = None,
        models: Sequence[type[Model]] | None = None,
    ):
        if model is not None and models is not None:
            raise ValueError("Configure either model or models, not both")

        self.app: ConfigurableApp | None = None
        self.models = tuple(models) if models is not None else (model or Model,)
        if not self.models:
            raise ValueError("At least one model base must be configured")
        self.model = self.models[0]
        self.engine: Engine | None = None

        if app is not None:
            self.init_app(app)

    def configure_models(self, *models: type[Model]) -> None:
        if not models:
            raise ValueError("At least one model base must be configured")

        new_models = tuple(model for model in models if model not in self.models)
        if self.engine is not None:
            session_options = self.app.config.get("SQLALCHEMY_SESSION_OPTIONS", {})
            for model in new_models:
                model.configure(self.engine, **session_options)

        self.models += new_models

    def init_app(self, app: ConfigurableApp) -> None:
        if self.app is not None and self.app is not app:
            raise RuntimeError("An SQLEngine instance can be attached to only one app")

        existing = app.extensions.get("qivo.sql")
        if existing is not None and existing is not self:
            raise RuntimeError(
                "An SQLEngine extension is already registered on this app"
            )
        if existing is self:
            return

        database_url = app.config.get("SQLALCHEMY_DATABASE_URI", "sqlite:///app.db")
        if not database_url:
            raise ValueError("SQLALCHEMY_DATABASE_URI must be configured")

        engine_options = app.config.get("SQLALCHEMY_ENGINE_OPTIONS", {})
        session_options = app.config.get("SQLALCHEMY_SESSION_OPTIONS", {})
        self.engine = SQLAlchemyConfig(database_url, engine_options).create_engine()
        for model in self.models:
            model.configure(self.engine, **session_options)
        self.app = app
        app.extensions["qivo.sql"] = self
        app.teardown_request(self._close_sessions)

    def _close_sessions(self, exception: BaseException | None = None) -> None:
        for model in self.models:
            close_session(model)

    def dispose(self) -> None:
        self._close_sessions()
        if self.engine is not None:
            self.engine.dispose()


class DatabaseSessions:
    """Stores the Flask session in the database instead of the cookie.

    Attach it to opt in; without it the app keeps Flask's signed cookie. The
    session rows live in the tables of the same model base, so create the table
    with the migration commands.
    """

    def __init__(
        self,
        app: ConfigurableApp | None = None,
        *,
        model: type[Model],
        config: SessionConfig | None = None,
    ):
        if not getattr(model, "__qivo_flask_session_model__", False):
            raise TypeError("model must inherit from FlaskSessionModel")

        self.app: ConfigurableApp | None = None
        self.model = model
        self.config = config
        self.store: SessionStore | None = None
        self.interface: DatabaseSessionInterface | None = None

        if app is not None:
            self.init_app(app)

    def init_app(self, app: ConfigurableApp) -> None:
        if self.app is not None and self.app is not app:
            raise RuntimeError(
                "A DatabaseSessions instance can be attached to only one app"
            )

        existing = app.extensions.get("qivo.sessions")
        if existing is not None and existing is not self:
            raise RuntimeError(
                "A DatabaseSessions extension is already registered on this app"
            )
        if existing is self:
            return

        config = self._resolve_config(app)
        store = SessionStore(self.model, session_factory(self.model))
        interface = DatabaseSessionInterface(store, config)

        self.config = config
        self.store = store
        self.interface = interface
        self.app = app
        app.extensions["qivo.sessions"] = self
        app.session_interface = interface

    def _resolve_config(self, app: ConfigurableApp) -> SessionConfig:
        base = self.config or SessionConfig()

        return SessionConfig(
            lifetime=_lifetime(
                app.config.get("QIVO_SESSION_LIFETIME"), base.lifetime
            ),
            cleanup_interval=int(
                app.config.get("QIVO_SESSION_CLEANUP_INTERVAL")
                or base.cleanup_interval
            ),
        )


def _lifetime(value: Any, default: timedelta) -> timedelta:
    if value is None:
        return default
    if isinstance(value, timedelta):
        return value
    return timedelta(seconds=float(value))
