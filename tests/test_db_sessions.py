from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask, flash, get_flashed_messages, session
from flask.sessions import SecureCookieSessionInterface
from sqlalchemy import create_engine, select
from sqlalchemy.exc import DBAPIError

from qivo.db.sql import (
    DatabaseSessions,
    SessionConfig,
    close_session,
    model_base,
    prune_sessions,
    session_model,
)
from qivo.db.sql.extensions import SQLEngine
from qivo.db.sql.sessions import ServerSideSession, SessionStore

from conftest import Base, Unconfigured, build_app, independent_session

SessionRow = session_model(Base)


@pytest.fixture
def session_app(tmp_path):
    app = build_app(tmp_path, QIVO_SESSION_LIFETIME=3600)
    db = SQLEngine(app, model=Base)
    extension = DatabaseSessions(app, model=Base)
    Base.metadata.create_all(db.engine)

    @app.get("/set/<value>")
    def set_value(value):
        session["value"] = value
        return {"value": value}

    @app.get("/read")
    def read_value():
        return {"value": session.get("value")}

    @app.get("/peek")
    def peek():
        return {"value": session.get("value")}

    @app.get("/count")
    def count():
        session["count"] = session.get("count", 0) + 1
        return {"count": session["count"]}

    @app.get("/clear")
    def clear():
        session.clear()
        return {"cleared": True}

    @app.get("/permanent")
    def permanent():
        session.permanent = True
        session["value"] = "para siempre"
        return {"permanent": session.permanent}

    @app.get("/flash")
    def flash_message():
        flash("hola")
        return {"flashed": True}

    @app.get("/flashes")
    def read_flashes():
        return {"flashes": get_flashed_messages()}

    try:
        yield app, db, extension
    finally:
        close_session(Base)
        Base.metadata.drop_all(db.engine)
        db.engine.dispose()


def rows(engine):
    with independent_session(engine) as db:
        return list(db.scalars(select(SessionRow)).all())


def row_data(engine, sid):
    with independent_session(engine) as db:
        row = db.get(SessionRow, sid)
        return None if row is None else dict(row.data)


def insert_row(engine, sid, data, expires_at):
    with independent_session(engine) as db:
        db.add(SessionRow(sid=sid, data=data, expires_at=expires_at))
        db.commit()


def utcnow():
    return datetime.now(timezone.utc)


def as_utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def test_the_session_keeps_the_cookie_backend_by_default(tmp_path):
    app = build_app(tmp_path)

    assert isinstance(app.session_interface, SecureCookieSessionInterface)


def test_the_session_data_lives_in_the_database(session_app):
    app, db, _ = session_app

    with app.test_client() as client:
        client.get("/set/hola")

    assert [row.data for row in rows(db.engine)] == [{"value": "hola"}]


def test_the_cookie_carries_the_session_id_only(session_app):
    app, db, _ = session_app

    with app.test_client() as client:
        client.get("/set/hola")
        cookie = client.get_cookie("session")

    assert cookie is not None
    assert len(cookie.value) <= 64
    assert "hola" not in cookie.value
    assert [row.sid for row in rows(db.engine)] == [cookie.value]


def test_the_session_survives_between_requests(session_app):
    app, _, _ = session_app

    with app.test_client() as client:
        assert client.get("/count").json == {"count": 1}
        assert client.get("/count").json == {"count": 2}
        assert client.get("/read").json == {"value": None}


def test_a_read_only_request_does_not_write_a_row(session_app):
    app, db, _ = session_app

    with app.test_client() as client:
        client.get("/peek")
        client.get("/peek")

    assert rows(db.engine) == []


def test_the_row_is_updated_in_place(session_app):
    app, db, _ = session_app

    with app.test_client() as client:
        client.get("/count")
        first = client.get_cookie("session").value
        client.get("/count")

    assert [row.sid for row in rows(db.engine)] == [first]
    assert row_data(db.engine, first) == {"count": 2}


def test_clear_removes_the_row_and_the_cookie(session_app):
    app, db, _ = session_app

    with app.test_client() as client:
        client.get("/set/hola")
        client.get("/clear")

        assert rows(db.engine) == []
        assert client.get("/read").json == {"value": None}


def test_a_regular_session_expires_with_the_configured_lifetime(session_app):
    app, db, _ = session_app

    with app.test_client() as client:
        client.get("/set/hola")
        sid = client.get_cookie("session").value

    expires_at = as_utc(rows(db.engine)[0].expires_at)
    remaining = (expires_at - utcnow()).total_seconds()

    assert 3500 < remaining <= 3600


def test_a_permanent_session_expires_with_the_permanent_lifetime(session_app):
    app, db, _ = session_app

    with app.test_client() as client:
        response = client.get("/permanent")
        sid = client.get_cookie("session").value

    expected = app.permanent_session_lifetime.total_seconds()
    remaining = (as_utc(rows(db.engine)[0].expires_at) - utcnow()).total_seconds()

    assert 0 < remaining <= expected
    assert "Expires=" in response.headers["Set-Cookie"]


def test_an_expired_row_starts_a_new_session(session_app):
    app, db, _ = session_app
    insert_row(
        db.engine,
        "vencida",
        {"value": "vieja"},
        utcnow() - timedelta(minutes=1),
    )

    with app.test_client() as client:
        client.set_cookie("session", "vencida")
        assert client.get("/read").json == {"value": None}

        client.get("/set/nueva")
        sid = client.get_cookie("session").value

    assert sid != "vencida"
    assert row_data(db.engine, sid) == {"value": "nueva"}


def test_an_unknown_cookie_starts_a_new_session(session_app):
    app, db, _ = session_app

    with app.test_client() as client:
        client.set_cookie("session", "no-existe")
        assert client.get("/read").json == {"value": None}

        client.get("/set/hola")
        sid = client.get_cookie("session").value

    assert sid != "no-existe"
    assert row_data(db.engine, sid) == {"value": "hola"}


def test_an_oversized_cookie_is_ignored(session_app):
    app, db, _ = session_app

    with app.test_client() as client:
        client.set_cookie("session", "x" * 200)
        assert client.get("/read").json == {"value": None}

    assert rows(db.engine) == []


def test_reading_the_session_marks_the_response_as_cookie_dependent(session_app):
    app, _, _ = session_app

    with app.test_client() as client:
        response = client.get("/peek")

    assert response.headers["Vary"] == "Cookie"


def test_flashed_messages_travel_through_the_database(session_app):
    app, _, _ = session_app

    with app.test_client() as client:
        client.get("/flash")
        assert client.get("/flashes").json == {"flashes": ["hola"]}
        assert client.get("/flashes").json == {"flashes": []}


def test_a_session_needs_no_secret_key(session_app):
    app, db, _ = session_app

    with app.test_client() as client:
        client.get("/set/hola")
        assert client.get("/read").json == {"value": "hola"}

    assert app.secret_key is None
    assert len(rows(db.engine)) == 1


def test_the_session_table_belongs_to_the_app_models(session_app):
    _, _, _ = session_app

    assert SessionRow.__tablename__ in Base.metadata.tables


def test_values_must_be_json_serializable(session_app):
    app, db, _ = session_app

    @app.get("/date")
    def store_date():
        session["when"] = datetime(2024, 1, 1)
        return {"stored": True}

    with app.test_client() as client, pytest.raises(RuntimeError, match="JSON"):
        client.get("/date")

    assert rows(db.engine) == []


def test_a_missing_table_is_reported_with_the_migration_hint(session_app):
    app, db, _ = session_app
    SessionRow.__table__.drop(db.engine)

    with app.test_client() as client, pytest.raises(RuntimeError, match="migrate"):
        client.get("/set/hola")


def test_another_database_error_is_left_alone(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'no' / 'app.db'}")
    store = SessionStore(SessionRow, engine)

    with pytest.raises(DBAPIError):
        store.load("cualquiera")


def test_pruning_a_base_without_a_session_table_is_rejected(tmp_path):
    build_app(tmp_path)

    with pytest.raises(RuntimeError, match="has no session table"):
        prune_sessions(Unconfigured, create_engine(f"sqlite:///{tmp_path / 'app.db'}"))


def test_the_sweep_deletes_the_expired_rows(session_app):
    _, db, _ = session_app
    insert_row(db.engine, "vencida", {}, utcnow() - timedelta(minutes=1))
    insert_row(db.engine, "viva", {}, utcnow() + timedelta(days=1))

    sweeper = Flask(__name__)
    DatabaseSessions(sweeper, model=Base, config=SessionConfig(cleanup_interval=1))

    with sweeper.test_client() as client:
        client.get("/peek")

    assert [row.sid for row in rows(db.engine)] == ["viva"]


def test_the_sweep_can_be_turned_off(session_app):
    _, db, _ = session_app
    insert_row(db.engine, "vencida", {}, utcnow() - timedelta(minutes=1))

    keeper = Flask(__name__)
    DatabaseSessions(
        keeper, model=Base, config=SessionConfig(cleanup_interval=0)
    )

    with keeper.test_client() as client:
        client.get("/peek")

    assert [row.sid for row in rows(db.engine)] == ["vencida"]


def test_prune_sessions_removes_only_the_expired_rows(session_app):
    _, db, _ = session_app
    insert_row(db.engine, "vencida", {}, utcnow() - timedelta(minutes=1))
    insert_row(db.engine, "viva", {}, utcnow() + timedelta(days=1))

    assert prune_sessions(Base, db.engine) == 1
    assert [row.sid for row in rows(db.engine)] == ["viva"]


def test_a_loaded_session_starts_unmodified():
    loaded = ServerSideSession({"value": "hola"}, sid="abc")

    assert loaded.modified is False
    assert loaded.sid == "abc"
    assert loaded.permanent is False
    assert loaded == {"value": "hola"}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.__setitem__("a", 1),
        lambda s: s.update({"a": 1}),
        lambda s: s.__ior__({"a": 1}),
        lambda s: s.setdefault("a", 1),
        lambda s: s.pop("value"),
        lambda s: s.popitem(),
        lambda s: s.__delitem__("value"),
        lambda s: s.clear(),
        lambda s: setattr(s, "permanent", True),
    ],
)
def test_every_mutation_marks_the_session_as_modified(mutate):
    session_object = ServerSideSession({"value": "hola"}, sid="abc")

    mutate(session_object)

    assert session_object.modified is True


def test_an_unconfigured_model_base_is_rejected(tmp_path):
    app = build_app(tmp_path)

    with pytest.raises(RuntimeError, match="has no database attached"):
        DatabaseSessions(app, model=Unconfigured)


def test_a_second_extension_is_rejected(session_app):
    app, _, _ = session_app

    with pytest.raises(RuntimeError, match="already registered"):
        DatabaseSessions(app, model=Base)


def test_an_extension_attaches_to_only_one_app(session_app, tmp_path):
    _, _, extension = session_app

    with pytest.raises(RuntimeError, match="only one app"):
        extension.init_app(build_app(tmp_path, "otra.db"))


def test_another_table_name_on_the_same_base_is_rejected():
    with pytest.raises(RuntimeError, match="already stores sessions"):
        session_model(Base, "otras_sesiones")


def test_the_table_name_can_be_configured(tmp_path, session_app, monkeypatch):
    _, db, _ = session_app
    other_base = model_base("Other")
    monkeypatch.setattr(
        other_base,
        "__qivo_session_factory__",
        Base.__qivo_session_factory__,
        raising=False,
    )

    app = build_app(tmp_path, "otra.db", QIVO_SESSION_TABLE="mis_sesiones")
    extension = DatabaseSessions(app, model=other_base)
    other_base.metadata.create_all(db.engine)

    @app.get("/set")
    def set_value():
        session["value"] = "hola"
        return {"ok": True}

    with app.test_client() as client:
        client.get("/set")
        sid = client.get_cookie("session").value

    assert extension.store.model.__tablename__ == "mis_sesiones"
    assert "mis_sesiones" in other_base.metadata.tables
    assert "qivo_sessions" in Base.metadata.tables

    with independent_session(db.engine) as db_session:
        assert dict(db_session.get(extension.store.model, sid).data) == {
            "value": "hola"
        }