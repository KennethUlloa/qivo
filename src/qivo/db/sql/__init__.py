from dataclasses import dataclass, field
from typing import Any, ClassVar, Generic, TypeVar

from sqlalchemy import (
    Engine,
    create_engine as sqlalchemy_create_engine,
    inspect,
    select,
)
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

ModelT = TypeVar("ModelT")


class ModelQuery(Generic[ModelT]):
    def __init__(self, model: type[ModelT], instance: ModelT | None = None):
        self.model = model
        self.instance = instance
        self.statement = select(model)

    def where(self, *criteria: Any) -> ModelQuery[ModelT]:
        self.statement = self.statement.where(*criteria)
        return self

    def filter(self, **values: Any) -> ModelQuery[ModelT]:
        criteria = (
            getattr(self.model, name) == value for name, value in values.items()
        )
        return self.where(*criteria)

    def get(self, identity: Any) -> ModelT | None:
        with self._session_factory()() as session:
            return session.get(self.model, identity)

    def first(self) -> ModelT | None:
        with self._session_factory()() as session:
            return session.scalars(self.statement).first()

    def all(self) -> list[ModelT]:
        with self._session_factory()() as session:
            return list(session.scalars(self.statement).all())

    def save(self) -> ModelT:
        if self.instance is None:
            raise RuntimeError(
                "Call save on a model instance, for example user.q.save()"
            )

        with self._session_factory()() as session:
            session.expire_on_commit = False
            if inspect(self.instance).session is not None:
                saved_instance = session.merge(self.instance)
            else:
                session.add(self.instance)
                saved_instance = self.instance
            session.commit()

        return saved_instance

    def delete(self) -> bool:
        if self.instance is None:
            raise RuntimeError(
                "Call delete on a model instance, for example user.q.delete()"
            )

        identity = inspect(self.instance).identity
        if identity is None:
            raise RuntimeError("Cannot delete a model instance that has not been saved")

        identity_key = identity[0] if len(identity) == 1 else identity
        with self._session_factory()() as session:
            persisted_instance = session.get(self.model, identity_key)
            if persisted_instance is None:
                return False

            session.delete(persisted_instance)
            session.commit()

        return True

    def _session_factory(self) -> sessionmaker[Session]:
        factory = getattr(self.model, "__qivo_session_factory__", None)
        if factory is None:
            raise RuntimeError(
                "Configure the model base with Model.configure(engine) before querying"
            )
        return factory


class _QueryDescriptor(Generic[ModelT]):
    def __get__(
        self,
        instance: ModelT | None,
        owner: type[ModelT],
    ) -> ModelQuery[ModelT]:
        return ModelQuery(owner, instance)


class Model(DeclarativeBase):
    q = _QueryDescriptor()
    __qivo_session_factory__: ClassVar[sessionmaker[Session] | None] = None

    @classmethod
    def configure(cls, engine: Engine, **session_options: Any) -> None:
        cls.__qivo_session_factory__ = sessionmaker(engine, **session_options)


@dataclass(frozen=True)
class SQLAlchemyConfig:
    url: str | URL
    engine_options: dict[str, Any] = field(default_factory=dict)

    def create_engine(self) -> Engine:
        return sqlalchemy_create_engine(self.url, **self.engine_options)


from qivo.db.sql.migrations import AlembicMigrations, MigrationConfig
from qivo.db.sql.extensions import SQLEngine
