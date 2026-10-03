import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from qivo.sql.mixins import TimestampMixin
from qivo.sql.utils import Paginated, ensure_list, to_dict


class Model(DeclarativeBase):
    pass


class User(TimestampMixin, Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str]
    password: Mapped[str]
    is_active: Mapped[bool] = mapped_column(default=True)


class Secret(Model):
    __tablename__ = "secrets"

    __exclude__ = ["token"]

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    token: Mapped[str]


class Profile(Model):
    __tablename__ = "profiles"

    __include__ = ["display_name"]

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str]
    email: Mapped[str]


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Model.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    with factory() as session:
        yield session


@pytest.fixture
def users(session):
    users = [
        User(username=f"user{index}", password="hash", is_active=True)
        for index in range(5)
    ]
    session.add_all(users)
    session.commit()
    return users


# ---------------------------------------------------------------------------
# ensure_list
# ---------------------------------------------------------------------------


def test_ensure_list_wraps_a_single_value():
    assert ensure_list("a") == ["a"]


def test_ensure_list_keeps_a_list():
    assert ensure_list(["a", "b"]) == ["a", "b"]


def test_ensure_list_with_an_empty_list():
    assert ensure_list([]) == []


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------


def test_to_dict_includes_every_column(session):
    user = User(username="ada", password="hash", is_active=True)
    session.add(user)
    session.commit()

    data = to_dict(user)

    assert data["id"] == user.id
    assert data["username"] == "ada"
    assert data["password"] == "hash"
    assert data["is_active"] is True


def test_to_dict_excludes_configured_columns(session):
    secret = Secret(name="api", token="s3cret")
    session.add(secret)
    session.commit()

    data = to_dict(secret)

    assert "token" not in data
    assert data["name"] == "api"


def test_to_dict_includes_configured_properties(session):
    profile = Profile(display_name="Ada", email="ada@example.com")
    session.add(profile)
    session.commit()

    data = to_dict(profile)

    assert data == {
        "id": profile.id,
        "display_name": "Ada",
        "email": "ada@example.com",
    }


def test_to_dict_without_include_or_exclude(session):
    user = User(username="ada", password="hash", is_active=False)
    session.add(user)
    session.commit()

    data = to_dict(user)

    assert set(data) == {
        "id",
        "username",
        "password",
        "is_active",
        "created_at",
        "updated_at",
    }


def test_to_dict_reads_persisted_values(session):
    secret = Secret(name="api", token="s3cret")
    session.add(secret)
    session.commit()

    assert to_dict(secret)["name"] == "api"


# ---------------------------------------------------------------------------
# Paginated
# ---------------------------------------------------------------------------


def test_paginated_first_page(session, users):
    page = Paginated.get(session.query(User), 1, 2)

    assert page.page == 1
    assert page.per_page == 2
    assert page.total == 5
    assert [user.username for user in page.items] == ["user0", "user1"]


def test_paginated_middle_page(session, users):
    page = Paginated.get(session.query(User), 2, 2)

    assert [user.username for user in page.items] == ["user2", "user3"]
    assert page.has_next is True


def test_paginated_last_page(session, users):
    page = Paginated.get(session.query(User), 3, 2)

    assert [user.username for user in page.items] == ["user4"]
    assert page.has_next is False


def test_paginated_beyond_the_last_page(session, users):
    page = Paginated.get(session.query(User), 4, 2)

    assert page.items == []
    assert page.total == 5
    assert page.has_next is False


def test_paginated_without_rows(session):
    page = Paginated.get(session.query(User), 1, 10)

    assert page.items == []
    assert page.total == 0
    assert page.has_next is False


def test_paginated_to_dict(session, users):
    data = Paginated.get(session.query(User), 1, 2).to_dict()

    assert data["page"] == 1
    assert data["per_page"] == 2
    assert data["total"] == 5
    assert data["has_next"] is True
    assert [item.username for item in data["items"]] == ["user0", "user1"]


def test_paginated_to_dict_keeps_items_without_to_dict(session):
    session.add(Secret(name="api", token="s3cret"))
    session.commit()

    data = Paginated.get(session.query(Secret), 1, 2).to_dict()

    assert [type(item) for item in data["items"]] == [Secret]


def test_paginated_to_dict_serializes_to_dict_items(session):
    session.add(Secret(name="api", token="s3cret"))
    session.commit()

    class SerializableSecret:
        def __init__(self, name):
            self.name = name

        def to_dict(self):
            return {"name": self.name}

    page = Paginated(
        page=1,
        per_page=1,
        items=[SerializableSecret("api")],
        total=1,
    )

    assert page.to_dict()["items"] == [{"name": "api"}]


# ---------------------------------------------------------------------------
# TimestampMixin
# ---------------------------------------------------------------------------


def test_timestamp_mixin_adds_both_columns():
    columns = User.__table__.c

    assert "created_at" in columns
    assert "updated_at" in columns


def test_timestamp_columns_are_required_with_defaults():
    columns = User.__table__.c

    for name in ("created_at", "updated_at"):
        assert columns[name].nullable is False
        assert columns[name].server_default is not None


def test_updated_at_is_refreshed_on_update():
    assert User.__table__.c["updated_at"].onupdate is not None


def test_timestamps_are_populated_by_the_database(session):
    user = User(username="ada", password="hash")
    session.add(user)
    session.commit()

    assert user.created_at is not None
    assert user.updated_at is not None