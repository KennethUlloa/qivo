from collections.abc import Mapping
from typing import Any, Protocol

from sqlalchemy import Engine

from qivo.db.sql import Model, SQLAlchemyConfig


class ConfigurableApp(Protocol):
    config: Mapping[str, Any]
    extensions: dict[str, Any]


class SQLEngine:
    def __init__(
        self, app: ConfigurableApp | None = None, *, model: type[Model] = Model
    ):
        self.app: ConfigurableApp | None = None
        self.model = model
        self.engine: Engine | None = None

        if app is not None:
            self.init_app(app)

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
        self.model.configure(self.engine, **session_options)
        self.app = app
        app.extensions["qivo.sql"] = self

    def dispose(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
