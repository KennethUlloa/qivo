import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from qivo.sql.seed import BaseSeeder


class Model(DeclarativeBase):
    pass


class User(Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True)
    password: Mapped[str]
    is_active: Mapped[bool] = mapped_column(default=True)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Model.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    with factory() as session:
        yield session


class UserSeeder(BaseSeeder):
    name = "users"

    def run(self):
        return self.first_or_create(
            User(username="ada", password="hash"),
            User.username == "ada",
        )


def test_base_seeder_run_is_not_implemented(session):
    with pytest.raises(NotImplementedError):
        BaseSeeder.run(session)


def test_seeder_keeps_the_session(session):
    assert UserSeeder(session).session is session


def test_first_or_create_creates_the_object(session):
    created = UserSeeder(session).run()
    session.commit()

    assert created.id is not None
    assert session.query(User).count() == 1


def test_first_or_create_returns_the_existing_object(session):
    seeder = UserSeeder(session)
    created = seeder.run()
    session.commit()

    assert seeder.run() is created
    assert session.query(User).count() == 1


def test_first_or_create_does_not_touch_other_rows(session):
    session.add(User(username="grace", password="hash"))
    session.commit()

    UserSeeder(session).run()
    session.commit()

    assert {user.username for user in session.query(User).all()} == {"ada", "grace"}


def test_create_or_update_inserts_when_missing(session):
    created = UserSeeder(session).create_or_update(
        User,
        User.username == "ada",
        {"username": "ada", "password": "hash"},
    )
    session.commit()

    assert created.id is not None
    assert session.query(User).one().username == "ada"


def test_create_or_update_updates_an_existing_object(session):
    UserSeeder(session).create_or_update(
        User,
        User.username == "ada",
        {"username": "ada", "password": "hash"},
    )
    session.commit()

    updated = UserSeeder(session).create_or_update(
        User,
        User.username == "ada",
        {"username": "ada", "password": "new-hash"},
    )
    session.commit()

    assert updated.password == "new-hash"
    assert session.query(User).count() == 1


def test_create_or_update_adds_a_column_missing_from_data(session):
    UserSeeder(session).create_or_update(
        User,
        User.username == "ada",
        {"username": "ada", "password": "hash", "is_active": False},
    )
    session.commit()

    updated = UserSeeder(session).create_or_update(
        User,
        User.username == "ada",
        {"username": "ada"},
    )
    session.commit()

    assert updated.is_active is False


def test_create_or_update_returns_the_persisted_object(session):
    seeder = UserSeeder(session)
    created = seeder.create_or_update(
        User,
        User.username == "ada",
        {"username": "ada", "password": "hash"},
    )
    session.commit()

    assert seeder.create_or_update(
        User,
        User.username == "ada",
        {"password": "new-hash"},
    ) is created