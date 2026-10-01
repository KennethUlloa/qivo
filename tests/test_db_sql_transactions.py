import pytest
from sqlalchemy import delete, inspect, update

from qivo.db.sql import close_session, get_session, transaction

from conftest import Base, Role, User, independent_session, load_detached


def read_from_db(engine, model, identity):
    """Read a row through a session unrelated to the Qivo ones."""

    with independent_session(engine) as session:
        return session.get(model, identity)


def test_save_inside_a_transaction_commits_on_exit(engine):
    user = User(name="ana")
    user.q.save()

    with transaction():
        loaded = User.q.get(user.id)
        loaded.name = "ana-2"
        loaded.q.save()

        assert get_session(Base).get(User, user.id).name == "ana-2"

    close_session(Base)
    assert load_detached(engine, User, user.id).name == "ana-2"


def test_save_inside_a_transaction_does_not_commit_before_exit(engine):
    user = User(name="ana")
    user.q.save()
    close_session(Base)

    with transaction():
        loaded = User.q.get(user.id)
        loaded.name = "ana-2"
        loaded.q.save()

        assert read_from_db(engine, User, user.id).name == "ana"

    close_session(Base)
    assert load_detached(engine, User, user.id).name == "ana-2"


def test_rollback_discards_changes_on_exception(engine):
    user = User(name="ana")
    user.q.save()

    with pytest.raises(RuntimeError, match="boom"):
        with transaction():
            loaded = User.q.get(user.id)
            loaded.name = "perdida"
            loaded.q.save()
            raise RuntimeError("boom")

    close_session(Base)
    assert load_detached(engine, User, user.id).name == "ana"


def test_rollback_discards_new_rows(engine):
    with pytest.raises(RuntimeError, match="boom"):
        with transaction():
            User(name="ana").q.save()
            raise RuntimeError("boom")

    close_session(Base)
    assert load_detached(engine, User, 1) is None


def test_nested_transaction_joins_the_outer_session(engine):
    with transaction() as outer:
        with transaction() as inner:
            assert inner is outer
            User(name="ana").q.save()


def test_nested_transaction_defers_the_commit_to_the_outer_block(engine):
    user = User(name="ana")
    user.q.save()
    close_session(Base)

    with transaction():
        with transaction():
            loaded = User.q.get(user.id)
            loaded.name = "ana-2"
            loaded.q.save()

        assert read_from_db(engine, User, user.id).name == "ana"

    close_session(Base)
    assert load_detached(engine, User, user.id).name == "ana-2"


def test_transaction_saves_every_pending_object_in_the_session(engine):
    user = User(name="ana")
    user.q.save()
    close_session(Base)

    with transaction() as session:
        session.add(Role(name="admin"))
        loaded = User.q.get(user.id)
        loaded.name = "ana-2"
        loaded.q.save()

    close_session(Base)
    assert load_detached(engine, User, user.id).name == "ana-2"
    assert load_detached(engine, Role, 1).name == "admin"


def test_instance_loaded_before_the_block_keeps_its_identity(engine):
    user = User(name="ana")
    user.q.save()
    outside = User.q.get(user.id)

    with transaction() as session:
        outside.name = "movido"
        outside.q.save()

        assert inspect(outside).session is session
        assert outside.name == "movido"

    close_session(Base)
    assert load_detached(engine, User, user.id).name == "movido"


def test_instance_loaded_before_the_block_keeps_its_relations(engine):
    User(name="ana", roles=[Role(name="admin")]).q.save()
    outside = User.q.get(1)
    assert [role.name for role in outside.roles] == ["admin"]

    with transaction() as session:
        outside.name = "movido"
        outside.q.save()

        assert inspect(outside).session is session

    close_session(Base)
    assert load_detached(engine, User, 1).name == "movido"
    assert load_detached(engine, Role, 1).name == "admin"


def test_instances_stay_usable_after_the_block(engine):
    User(name="ana", roles=[Role(name="admin")]).q.save()
    close_session(Base)

    with transaction():
        loaded = User.q.first()
        loaded.name = "ana-2"
        loaded.q.save()

    assert loaded.roles[0].name == "admin"
    assert loaded.name == "ana-2"


def test_save_outside_a_transaction_persists_only_the_instance_graph(engine):
    User(name="bruno", roles=[Role(name="admin")]).q.save()
    ambient = get_session(Base)

    pending = Role(name="pendiente")
    ambient.add(pending)

    loaded = User.q.get(1)
    loaded.name = "bruno-2"
    loaded.q.save()

    assert pending in ambient.new

    ambient.rollback()
    close_session(Base)
    assert load_detached(engine, User, 1).name == "bruno-2"
    assert load_detached(engine, Role, 1).name == "admin"
    assert [role.name for role in Role.q.all()] == ["admin"]


def test_save_outside_a_transaction_keeps_the_instance_identity(engine):
    user = User(name="ana")
    user.q.save()

    saved = user.q.save()

    assert saved is user
    assert user.id is not None
    assert user.name == "ana"


def test_ambient_session_is_refreshed_after_an_outside_write(engine):
    User(name="ana").q.save()
    ambient = get_session(Base)
    assert ambient.get(User, 1).name == "ana"

    with independent_session(engine) as session:
        session.execute(update(User).where(User.id == 1).values(name="ana-2"))
        session.commit()

    assert User.q.get(1).name == "ana-2"


def test_delete_inside_a_transaction_flushes_without_committing(engine):
    user = User(name="ana")
    user.q.save()
    close_session(Base)

    with transaction() as session:
        loaded = User.q.get(user.id)
        loaded.q.delete()

        assert session.get(User, user.id) is None
        assert read_from_db(engine, User, user.id) is not None

    close_session(Base)
    assert load_detached(engine, User, user.id) is None


def test_delete_outside_a_transaction_commits(engine):
    user = User(name="ana")
    user.q.save()

    assert user.q.delete() is True

    close_session(Base)
    assert load_detached(engine, User, user.id) is None


def test_delete_returns_false_when_the_row_is_gone(engine):
    user = User(name="ana")
    user.q.save()
    detached = load_detached(engine, User, user.id)

    with independent_session(engine) as session:
        session.execute(delete(User).where(User.id == user.id))
        session.commit()

    assert detached.q.delete() is False


def test_delete_of_an_unsaved_instance_raises(engine):
    with pytest.raises(RuntimeError, match="has not been saved"):
        User(name="ana").q.delete()


def test_save_without_an_instance_raises(engine):
    with pytest.raises(RuntimeError, match="user.q.save"):
        User.q.save()


def test_delete_without_an_instance_raises(engine):
    with pytest.raises(RuntimeError, match="user.q.delete"):
        Role.q.delete()


def test_unsaved_changes_on_the_query_session_are_reported(engine):
    User(name="ana").q.save()
    loaded = User.q.get(1)
    loaded.name = "sin-guardar"

    with pytest.raises(RuntimeError, match="unsaved changes"):
        close_session(Base)
