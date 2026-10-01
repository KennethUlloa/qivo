
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import (
    Engine,
    create_engine as sqlalchemy_create_engine,
)
from sqlalchemy.engine import URL



@dataclass(frozen=True)
class SQLAlchemyConfig:
    url: str | URL
    engine_options: dict[str, Any] = field(default_factory=dict)

    def create_engine(self) -> Engine:
        return sqlalchemy_create_engine(self.url, **self.engine_options)


from qivo.db.sql.model import (
    Model,
    ModelQuery,
    Session,
    SessionManager,
    _SessionHolder,
    close_session,
    get_session,
    model_base,
    transaction,
)
from qivo.db.sql.migrations import AlembicMigrations, MigrationConfig
from qivo.db.sql.sessions import (
    DatabaseSessionInterface,
    FlaskSessionModel,
    ServerSideSession,
    SessionConfig,
    SessionStore,
    prune_sessions,
)
from qivo.db.sql.extensions import DatabaseSessions, SQLEngine
