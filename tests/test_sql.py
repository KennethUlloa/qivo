import pytest
from flask import Flask
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from qivo.ext.sql import SQL, db


class Model(DeclarativeBase):
    pass


class Record(Model):
    __tablename__ = "records"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


@pytest.fixture
def db_app():
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite://",
        SQLALCHEMY_ENGINE_OPTIONS={},
    )
    extension = SQL(app)
    Model.metadata.create_all(extension.engine)
    return app


@pytest.fixture
def sql(db_app):
    return db_app.extensions["qivo.sql"]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_engine_is_created_from_the_database_uri(db_app, sql):
    assert sql.engine.url.render_as_string() == "sqlite://"
    assert sql.engine is db_app.extensions["qivo.sql"].engine


def test_engine_options_are_applied():
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite://",
        SQLALCHEMY_ENGINE_OPTIONS={"echo": True},
    )

    assert SQL(app).engine.echo is True


def test_explicit_options_override_the_app_config():
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite://",
        SQLALCHEMY_ENGINE_OPTIONS={"echo": True},
    )

    assert SQL(app, options={"echo": False}).engine.echo is False


def test_a_prepared_engine_can_be_passed():
    app = Flask(__name__)
    engine = create_engine("sqlite://")

    assert SQL(app, engine=engine).engine is engine


def test_missing_database_uri_raises():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = None

    with pytest.raises(ValueError, match="SQLALCHEMY_DATABASE_URI is not set"):
        SQL(app)


def test_extension_is_registered_in_the_app(db_app, sql):
    assert db_app.extensions["qivo.sql"] is sql


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


def test_session_is_created_on_first_access(db_app, sql):
    with db_app.app_context():
        session = sql.session

        assert isinstance(session, Session)
        assert session.get_bind() is sql.engine


def test_session_is_reused_within_the_app_context(db_app, sql):
    with db_app.app_context():
        assert sql.session is sql.session


def test_db_proxy_returns_the_request_session(db_app, sql):
    with db_app.app_context():
        assert db._get_current_object() is sql.session


def test_db_proxy_requires_an_app_context(db_app):
    with pytest.raises(RuntimeError):
        db.execute(select(Record))


def test_session_is_closed_on_teardown(db_app, sql):
    with db_app.app_context():
        record = Record(name="first")
        db.add(record)
        db.commit()
        session = sql.session
        assert list(session.identity_map)

    assert list(session.identity_map) == []


def test_queries_and_writes_work(sql, db_app):
    with db_app.app_context():
        db.add(Record(name="first"))
        db.commit()

        records = db.scalars(select(Record)).all()

        assert [record.name for record in records] == ["first"]
        assert records[0].id == 1


def test_session_is_bound_to_the_app_engine(db_app, sql):
    with db_app.app_context():
        db.add(Record(name="first"))
        db.commit()

    assert inspect(sql.engine).get_table_names() == ["records"]


def test_queries_work_inside_a_flask_view(db_app):
    @db_app.get("/records")
    def index():
        db.add(Record(name="from-view"))
        db.commit()
        return {"names": [record.name for record in db.scalars(select(Record)).all()]}

    client = db_app.test_client()

    assert client.get("/records").json == {"names": ["from-view"]}
    assert client.get("/records").json == {"names": ["from-view", "from-view"]}


def test_each_app_context_gets_a_fresh_session(db_app, sql):
    with db_app.app_context():
        first = sql.session

    with db_app.app_context():
        second = sql.session

        assert first is not second


def test_the_session_context_is_not_scoped_to_the_app_context(db_app, sql):
    session = sql.get_session()

    with db_app.app_context():
        assert sql.session is session

    with pytest.raises(RuntimeError):
        db.execute(select(Record))