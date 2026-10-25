from flask import Flask, g
import pytest

from qivo.accessors import GField

# -------------------------------------
# Global Flask object (g)
# -------------------------------------


def test_g_accessor_getter(app: Flask):
    class _BaseContext:
        preference: str = GField()

    ctx = _BaseContext()

    with app.app_context():
        g.preference = "dark"

        assert g.preference == ctx.preference

def test_g_accessor_setter(app: Flask):
    class _BaseContext:
        preference: str = GField()

    ctx = _BaseContext()

    with app.app_context():
        ctx.preference = "light"

        assert g.preference == "light"

def test_g_accessor_typed_setter(app: Flask):
    class _BaseContext:
        count: int = GField(strict_type=True)

    ctx = _BaseContext()

    with app.app_context():
        ctx.count = 1

        assert g.count == 1 # Check assignment still works

        with pytest.raises(ValueError):
            ctx.count = "hello"


def test_g_accessor_strict_typed_definition(app: Flask):
    class _BaseContext:
        count: int = GField(strict_type=True)
        description = GField(str, strict_type=True)

    with pytest.raises(ValueError):
        class _WrongTyping:
            count = GField(strict_type=True)


def test_g_accessor_typed_precedence(app: Flask):
    class BaseContext:
        count: int = GField(float)
        description = GField(str)

    assert BaseContext.count.type == float


def test_g_accessor_nullable(app: Flask):
    class BaseContext:
        count: int = GField(nullable=False, default=1)

    ctx = BaseContext()

    with pytest.raises(ValueError):
        ctx.count = None

    # Non nullables can not have None as default
    with pytest.raises(ValueError):
        class WrongType:
            count: int = GField(nullable=False)
