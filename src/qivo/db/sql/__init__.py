from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
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
from sqlalchemy.orm.base import NO_VALUE
from sqlalchemy.orm.properties import RelationshipProperty

ModelT = TypeVar("ModelT")

_DEFAULT_SESSION_OPTIONS = {"expire_on_commit": False}
_default_holder: "_SessionHolder | None" = None


class SessionManager:
    def __init__(self, factory: sessionmaker[Session]):
        self._factory = factory
        self._ambient: Session | None = None
        self._transactions: list[Session] = []

    @property
    def ambient(self) -> Session:
        if self._ambient is None:
            self._ambient = self._factory(autoflush=False)
        return self._ambient

    @property
    def current(self) -> Session:
        if self._transactions:
            return self._transactions[-1]
        return self.ambient

    @property
    def in_transaction(self) -> bool:
        return bool(self._transactions)

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        if self._transactions:
            yield self._transactions[-1]
            return

        session = self._factory()
        self._transactions.append(session)
        try:
            yield session
            session.commit()
            session.autoflush = False
            self._ambient = session
        except BaseException:
            try:
                session.rollback()
            finally:
                session.close()
            raise
        finally:
            self._transactions.pop()

    def commit_standalone(self, instance: ModelT) -> ModelT:
        with self._factory() as session:
            detach_graph(instance)
            session.add(instance)
            session.commit()
        self.expire_ambient()
        return instance

    def expire_ambient(self) -> None:
        ambient = self._ambient
        if ambient is None or _pending(ambient):
            return
        ambient.expire_all()

    def close(self) -> None:
        for session in reversed(self._transactions):
            session.close()
        self._transactions.clear()

        ambient = self._ambient
        self._ambient = None
        if ambient is None:
            return
        try:
            _ensure_persisted(ambient)
        finally:
            ambient.close()


class _SessionHolder:
    def __init__(self, base: type["Model"]):
        self._base = base
        self._managers: ContextVar[SessionManager | None] = ContextVar(
            "qivo_sql_sessions", default=None
        )

    def get(self) -> SessionManager:
        manager = self._managers.get()
        if manager is None:
            manager = SessionManager(self._base.__qivo_session_factory__)
            self._managers.set(manager)
        return manager

    def close(self) -> None:
        manager = self._managers.get()
        self._managers.set(None)
        if manager is not None:
            manager.close()


def transaction(
    model: type["Model"] | None = None,
) -> AbstractContextManager[Session]:
    return _holder(model).get().transaction()


def get_session(model: type["Model"] | None = None) -> Session:
    return _holder(model).get().current


def close_session(model: type["Model"] | None = None) -> None:
    holder = _holder(model, required=False)
    if holder is not None:
        holder.close()


def _holder(model: type["Model"] | None = None, *, required: bool = True):
    holder = (
        getattr(model, "__qivo_session_holder__", None)
        if model is not None
        else _default_holder
    )
    if holder is None:
        if not required:
            return None
        raise RuntimeError(
            "Configure the model base with Model.configure(engine) before querying"
        )
    return holder


def _pending(session: Session) -> bool:
    return bool(session.new or session.dirty or session.deleted)


def _ensure_persisted(session: Session) -> None:
    if _pending(session):
        raise RuntimeError(
            "The query session has unsaved changes. Save them with instance.q.save(), "
            "instance.q.delete() or with transaction() to commit them"
        )


def _attach(session: Session, instance: ModelT) -> ModelT:
    if inspect(instance).session is session:
        session.add(instance)
        return instance

    detach_graph(instance)
    session.add(instance)
    return instance


def detach_graph(instance: Any) -> None:
    session = inspect(instance).session
    if session is None:
        return
    _expunge_graph(session, instance)


def _expunge_graph(
    session: Session, instance: Any, visited: set[int] | None = None
) -> None:
    visited = set() if visited is None else visited
    if id(instance) in visited:
        return
    visited.add(id(instance))

    state = inspect(instance)
    if state.session is session:
        session.expunge(instance)

    for related in _loaded_related(state):
        if inspect(related).session is session:
            _expunge_graph(session, related, visited)


def _loaded_related(state: Any) -> Iterator[Any]:
    for prop in state.mapper.iterate_properties:
        if not isinstance(prop, RelationshipProperty):
            continue
        value = state.attrs[prop.key].loaded_value
        if value is NO_VALUE:
            continue
        if isinstance(value, (list, tuple, set)):
            yield from value
        elif value is not None:
            yield value


class ModelQuery(Generic[ModelT]):
    def __init__(self, model: type[ModelT], instance: ModelT | None = None):
        self.model = model
        self.instance = instance
        self.criteria: list[Any] = []

    def where(self, *criteria: Any) -> ModelQuery[ModelT]:
        self.criteria.extend(criteria)
        return self

    @property
    def statement(self) -> Any:
        return select(self.model).where(*self.criteria)

    def filter(self, **values: Any) -> ModelQuery[ModelT]:
        criteria = (
            getattr(self.model, name) == value for name, value in values.items()
        )
        return self.where(*criteria)

    @property
    def session(self) -> Session:
        return self._manager().current

    def get(self, identity: Any) -> ModelT | None:
        return self.session.get(self.model, identity)

    def first(self) -> ModelT | None:
        return self.session.scalars(self.statement).first()

    def all(self) -> list[ModelT]:
        return list(self.session.scalars(self.statement).all())

    def save(self) -> ModelT:
        instance = self._instance("save")
        manager = self._manager()

        if manager.in_transaction:
            _attach(manager.current, instance)
            manager.current.flush()
            return instance

        return manager.commit_standalone(instance)

    def delete(self) -> bool:
        instance = self._instance("delete")
        manager = self._manager()
        session = manager.current

        state = inspect(instance)
        if state.identity is None:
            raise RuntimeError("Cannot delete a model instance that has not been saved")

        if state.session is not session:
            identity = state.identity
            identity_key = identity[0] if len(identity) == 1 else identity
            if session.get(self.model, identity_key) is None:
                return False
            _attach(session, instance)

        session.delete(instance)

        if manager.in_transaction:
            session.flush()
        else:
            session.commit()
            manager.expire_ambient()

        return True

    def _instance(self, operation: str) -> ModelT:
        if self.instance is None:
            raise RuntimeError(
                f"Call {operation} on a model instance, "
                f"for example user.q.{operation}()"
            )
        return self.instance

    def _manager(self) -> SessionManager:
        holder = getattr(self.model, "__qivo_session_holder__", None)
        if holder is None:
            raise RuntimeError(
                "Configure the model base with Model.configure(engine) before querying"
            )
        return holder.get()


class _QueryDescriptor(Generic[ModelT]):
    def __get__(
        self,
        instance: ModelT | None,
        owner: type[ModelT],
    ) -> ModelQuery[ModelT]:
        return ModelQuery(owner, instance)


class _ModelMixin:
    q = _QueryDescriptor()
    __qivo_session_factory__: ClassVar[sessionmaker[Session] | None] = None
    __qivo_session_holder__: ClassVar[_SessionHolder | None] = None

    @classmethod
    def configure(cls, engine: Engine, **session_options: Any) -> None:
        global _default_holder

        options = {**_DEFAULT_SESSION_OPTIONS, **session_options}
        cls.__qivo_session_factory__ = sessionmaker(engine, **options)

        previous = cls.__dict__.get("__qivo_session_holder__")
        if previous is not None:
            previous.close()

        cls.__qivo_session_holder__ = _SessionHolder(cls)
        _default_holder = cls.__qivo_session_holder__


class Model(_ModelMixin, DeclarativeBase):
    pass


def model_base(name: str = "Model") -> type[Model]:
    """Build an isolated declarative base, for apps that need their own models."""

    return type(name, (_ModelMixin, DeclarativeBase), {})


@dataclass(frozen=True)
class SQLAlchemyConfig:
    url: str | URL
    engine_options: dict[str, Any] = field(default_factory=dict)

    def create_engine(self) -> Engine:
        return sqlalchemy_create_engine(self.url, **self.engine_options)


from qivo.db.sql.migrations import AlembicMigrations, MigrationConfig
from qivo.db.sql.sessions import (
    DatabaseSessionInterface,
    ServerSideSession,
    SessionConfig,
    SessionStore,
    prune_sessions,
    session_model,
)
from qivo.db.sql.extensions import DatabaseSessions, SQLEngine
