from pathlib import Path

import pytest
from sqlalchemy import ForeignKey, create_engine
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship, sessionmaker

from qivo.db.sql import close_session, model_base

Base = model_base("Base")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    roles: Mapped[list["Role"]] = relationship(
        secondary="user_roles", back_populates="users"
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    users: Mapped[list[User]] = relationship(
        secondary="user_roles", back_populates="roles"
    )


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), primary_key=True)


Unconfigured = model_base("Unconfigured")


@pytest.fixture
def engine(tmp_path: Path):
    # A file database, not "sqlite://" memory: with memory every session in the
    # thread shares one connection, which would hide the read/write separation.
    engine = create_engine(f"sqlite:///{tmp_path}/qivo-test.db")
    Base.configure(engine)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        close_session(Base)
        Base.metadata.drop_all(engine)
        engine.dispose()


def independent_session(engine) -> Session:
    """A session unrelated to the ambient and transaction sessions."""

    return sessionmaker(engine)()


def load_detached(engine, model, identity):
    """Load a row through a session that closes, leaving the instance detached."""

    with independent_session(engine) as session:
        return session.get(model, identity)
