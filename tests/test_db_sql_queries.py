import pytest

from qivo.db.sql import close_session, get_session, transaction

from conftest import Base, Role, Unconfigured, User, load_detached


def test_first_keeps_the_instance_attached_for_lazy_relations(engine):
    User(name="ana", roles=[Role(name="admin")]).q.save()
    close_session(Base)

    user = User.q.where(User.name == "ana").first()

    assert user.roles[0].name == "admin"


def test_get_and_all_return_attached_instances(engine):
    User(name="ana").q.save()
    User(name="bruno").q.save()

    loaded = User.q.get(1)
    everyone = User.q.all()

    assert loaded.name == "ana"
    assert sorted(user.name for user in everyone) == ["ana", "bruno"]
    assert all(user in get_session(Base) for user in everyone)


def test_filter_and_all_compose_criteria(engine):
    User(name="ana").q.save()
    User(name="bruno").q.save()

    found = User.q.filter(name="bruno").all()

    assert [user.name for user in found] == ["bruno"]


def test_where_returns_the_same_query(engine):
    query = User.q.where(User.name == "ana")

    assert query.filter(name="ana") is query


def test_query_on_an_unconfigured_base_raises():
    with pytest.raises(RuntimeError, match="Model.configure"):
        Unconfigured.q.all()


def test_ambient_session_survives_until_closed(engine):
    User(name="ana").q.save()

    session = get_session(Base)
    User.q.all()

    assert get_session(Base) is session


def test_session_property_matches_the_ambient_session(engine):
    session = get_session(Base)

    assert User.q.session is session


def test_load_detached_helper_returns_a_detached_instance(engine):
    User(name="ana").q.save()

    user = load_detached(engine, User, 1)

    assert user.name == "ana"


def test_transaction_yields_the_session_used_by_queries(engine):
    User(name="ana").q.save()

    with transaction() as session:
        user = User.q.first()

        assert user in session
        assert User.q.session is session
