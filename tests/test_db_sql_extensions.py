import pytest
from flask import Flask
from sqlalchemy import inspect

from qivo.db.sql import get_session, model_base
from qivo.db.sql.extensions import SQLEngine

from conftest import Base, User, load_detached, sql_app  # noqa: F401


def test_engine_configures_the_model_base(sql_app):
    _, extension = sql_app

    assert Base.__qivo_session_factory__ is not None
    assert extension.app.extensions["qivo.sql"] is extension


def test_engine_configures_and_closes_multiple_model_bases(tmp_path):
    first = model_base("First")
    second = model_base("Second")
    app = Flask(__name__)
    app.config.from_mapping(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path}/multiple.db"
    )
    extension = SQLEngine(app, models=(first, second))

    assert first.__qivo_session_factory__.kw["bind"] is extension.engine
    assert second.__qivo_session_factory__.kw["bind"] is extension.engine

    with app.test_request_context("/"):
        first_session = get_session(first)
        second_session = get_session(second)

    assert get_session(first) is not first_session
    assert get_session(second) is not second_session
    extension.dispose()


def test_engine_can_configure_additional_model_bases_after_init(tmp_path):
    first = model_base("Initial")
    additional = model_base("Additional")
    app = Flask(__name__)
    app.config.from_mapping(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path}/additional.db"
    )
    extension = SQLEngine(app, model=first)

    extension.configure_models(additional)

    assert additional.__qivo_session_factory__.kw["bind"] is extension.engine
    with app.test_request_context("/"):
        session = get_session(additional)

    assert get_session(additional) is not session
    extension.dispose()


def test_ambient_session_is_closed_after_the_request(sql_app):
    app, extension = sql_app

    with app.test_request_context("/"):
        session = get_session(Base)
        User.q.all()

        assert get_session(Base) is session

    assert get_session(Base) is not session
    assert load_detached(extension.engine, User, 1) is None


def test_query_session_is_closed_after_the_request(sql_app):
    app, _ = sql_app

    with app.test_request_context("/"):
        session = User.q.session

    assert User.q.session is not session


def test_instances_are_detached_after_the_request(sql_app):
    app, _ = sql_app

    with app.test_request_context("/"):
        User(name="ana").q.save()

    with app.test_request_context("/"):
        user = User.q.first()

    assert inspect(user).session is None


def test_data_survives_between_requests(sql_app):
    app, _ = sql_app

    with app.test_request_context("/"):
        User(name="ana").q.save()

    with app.test_request_context("/"):
        assert User.q.first().name == "ana"


def test_dispose_closes_the_sessions(sql_app):
    app, extension = sql_app

    with app.test_request_context("/"):
        session = get_session(Base)

    extension.dispose()

    assert get_session(Base) is not session


def test_missing_database_uri_is_rejected():
    app = Flask(__name__)
    app.config.from_mapping(SQLALCHEMY_DATABASE_URI="")

    with pytest.raises(ValueError, match="SQLALCHEMY_DATABASE_URI"):
        SQLEngine(app, model=model_base("MissingUri"))


def test_a_second_extension_is_rejected(sql_app):
    _, extension = sql_app

    with pytest.raises(RuntimeError, match="already registered"):
        SQLEngine(extension.app, model=Base)


def test_an_extension_attaches_to_only_one_app(sql_app, tmp_path):
    _, extension = sql_app
    other = Flask(__name__)
    other.config.from_mapping(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path}/other.db"
    )

    with pytest.raises(RuntimeError, match="only one app"):
        extension.init_app(other)
