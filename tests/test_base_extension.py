import pytest
from flask import Flask

from qivo.ext.base import BaseExtension


class DummyExtension(BaseExtension):
    name = "qivo.dummy"

    def __init__(self, app=None):
        self.setup_calls = []
        super().__init__(app)

    def setup(self, app):
        self.setup_calls.append(app)


def test_init_app_registers_extension(app):
    extension = DummyExtension()

    extension.init_app(app)

    assert extension.app is app
    assert app.extensions["qivo.dummy"] is extension


def test_constructor_attaches_extension(app):
    extension = DummyExtension(app)

    assert app.extensions["qivo.dummy"] is extension
    assert extension.setup_calls == [app]


def test_setup_hook_receives_the_app(app):
    extension = DummyExtension(app)

    assert extension.setup_calls == [app]


def test_extension_can_be_attached_to_multiple_apps():
    first = Flask("first")
    second = Flask("second")
    extension = DummyExtension()

    extension.init_app(first)
    extension.init_app(second)

    assert first.extensions["qivo.dummy"] is extension
    assert second.extensions["qivo.dummy"] is extension
    assert extension.app is second


def test_extension_cannot_be_attached_twice_to_the_same_app(app):
    extension = DummyExtension(app)

    with pytest.raises(RuntimeError, match="only one app"):
        DummyExtension(app)


def test_current_returns_the_attached_extension(app):
    extension = DummyExtension(app)

    with app.app_context():
        assert DummyExtension.current() is extension


def test_current_requires_an_app_context(app):
    DummyExtension(app)

    with pytest.raises(RuntimeError):
        DummyExtension.current()


def test_current_requires_the_extension_to_be_attached(app):
    with app.app_context():
        with pytest.raises(RuntimeError, match="not attached"):
            DummyExtension.current()


def test_current_rejects_a_foreign_instance(app):
    class ForeignExtension(BaseExtension):
        name = "qivo.dummy"

    ForeignExtension(app)

    with app.app_context():
        with pytest.raises(RuntimeError, match="not attached"):
            DummyExtension.current()


def test_current_is_bound_to_the_active_app():
    first = Flask("first")
    second = Flask("second")
    first_extension = DummyExtension(first)
    second_extension = DummyExtension(second)

    with first.app_context():
        assert DummyExtension.current() is first_extension

    with second.app_context():
        assert DummyExtension.current() is second_extension