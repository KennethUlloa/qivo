import pytest
from werkzeug.exceptions import Forbidden, Unauthorized

from qivo.ext.auth import (
    AuthManager,
    PermissionStrategy,
    current_user,
    logged_in,
    permission,
)


class User:
    def __init__(self, permissions):
        self.permissions = permissions

    def get_id(self):
        return "1"

    def get_permissions(self):
        return self.permissions

    def any_permission(self, permissions):
        return any(item in self.permissions for item in permissions)

    def all_permissions(self, permissions):
        return all(item in self.permissions for item in permissions)


class Guard:
    logged_in = True
    user = None

    def check_logged_in(self):
        return self.logged_in

    def get_current_user(self, required=False):
        return self.user

    def permission_check_failed(self):
        raise Forbidden()

    def logged_in_check_failed(self):
        raise Unauthorized()


@pytest.fixture
def auth(app):
    manager = AuthManager(app)
    return manager


@pytest.fixture
def guard(auth):
    guard = Guard()

    @auth.guard_resolver()
    def get_guard():
        return guard

    return guard


# ---------------------------------------------------------------------------
# Guard registry
# ---------------------------------------------------------------------------


def test_guard_resolver_registers_the_default_guard(app, auth, guard):
    with app.app_context():
        assert auth.get_guard() is guard


def test_guard_resolver_registers_a_named_guard(app, auth):
    default_guard = Guard()
    web_guard = Guard()

    @auth.guard_resolver()
    def get_default():
        return default_guard

    @auth.guard_resolver("web")
    def get_web():
        return web_guard

    with app.app_context():
        assert auth.get_guard() is default_guard
        assert auth.get_guard("web") is web_guard


def test_guard_resolver_keeps_the_function(app, auth):
    @auth.guard_resolver()
    def get_guard():
        return Guard()

    with app.app_context():
        assert auth.get_guard().__class__ is Guard


def test_get_guard_returns_a_new_instance_per_call(app, auth):
    @auth.guard_resolver()
    def get_guard():
        return Guard()

    with app.app_context():
        assert auth.get_guard() is not auth.get_guard()


def test_get_unknown_guard(app, auth):
    with app.app_context():
        with pytest.raises(ValueError, match="Unknown guard"):
            auth.get_guard("missing")


def test_get_guard_without_resolvers(app, auth):
    with app.app_context():
        with pytest.raises(ValueError, match="Unknown guard"):
            auth.get_guard()


def test_current_user_returns_the_guard_user(app, auth, guard):
    guard.user = User(["tasks:read"])

    with app.app_context():
        assert current_user() is guard.user


def test_current_user_can_be_none(app, auth, guard):
    with app.app_context():
        assert current_user() is None


def test_auth_requires_an_app_context():
    with pytest.raises(RuntimeError):
        current_user()


# ---------------------------------------------------------------------------
# logged_in
# ---------------------------------------------------------------------------


def test_logged_in_allows_authenticated_users(app, auth, guard):
    @logged_in()
    def handler():
        return "ok"

    with app.app_context():
        assert handler() == "ok"


def test_logged_in_blocks_anonymous_users(app, auth, guard):
    guard.logged_in = False

    @logged_in()
    def handler():
        return "ok"

    with app.app_context():
        with pytest.raises(Unauthorized):
            handler()


def test_logged_in_can_return_a_response(app, auth):
    @auth.guard_resolver()
    def get_guard():
        class ResponseGuard(Guard):
            logged_in = False

            def logged_in_check_failed(self):
                return {"error": "unauthenticated"}, 401

        return ResponseGuard()

    @logged_in()
    def handler():
        return "ok"

    with app.app_context():
        assert handler() == ({"error": "unauthenticated"}, 401)


def test_logged_in_uses_the_named_guard(app, auth):
    default_guard = Guard()
    web_guard = Guard()
    web_guard.logged_in = False

    @auth.guard_resolver()
    def get_default():
        return default_guard

    @auth.guard_resolver("web")
    def get_web():
        return web_guard

    @logged_in("web")
    def handler():
        return "ok"

    with app.app_context():
        with pytest.raises(Unauthorized):
            handler()


def test_logged_in_preserves_the_function_metadata(auth):
    @logged_in()
    def handler():
        """Docstring."""

    assert handler.__name__ == "handler"
    assert handler.__doc__ == "Docstring."


# ---------------------------------------------------------------------------
# permission
# ---------------------------------------------------------------------------


def test_permission_allows_a_granted_permission(app, auth, guard):
    guard.user = User(["tasks:read"])

    @permission(["tasks:read"])
    def handler():
        return "ok"

    with app.app_context():
        assert handler() == "ok"


def test_permission_any_strategy_needs_one_permission(app, auth, guard):
    guard.user = User(["tasks:read"])

    @permission(["admin:read", "tasks:read"], strategy=PermissionStrategy.ANY)
    def handler():
        return "ok"

    with app.app_context():
        assert handler() == "ok"


def test_permission_any_strategy_rejects_missing_permissions(app, auth, guard):
    guard.user = User(["tasks:read"])

    @permission(["admin:read", "tasks:write"], strategy="any")
    def handler():
        return "ok"

    with app.app_context():
        with pytest.raises(Forbidden):
            handler()


def test_permission_all_strategy_requires_every_permission(app, auth, guard):
    guard.user = User(["tasks:read", "tasks:write"])

    @permission(["tasks:read", "tasks:write"], strategy=PermissionStrategy.ALL)
    def handler():
        return "ok"

    with app.app_context():
        assert handler() == "ok"


def test_permission_all_strategy_rejects_partial_permissions(app, auth, guard):
    guard.user = User(["tasks:read"])

    @permission(["tasks:read", "tasks:write"], strategy="all")
    def handler():
        return "ok"

    with app.app_context():
        with pytest.raises(Forbidden):
            handler()


def test_permission_uses_the_named_guard(app, auth):
    default_guard = Guard()
    default_guard.user = User([])
    web_guard = Guard()
    web_guard.user = User(["tasks:read"])

    @auth.guard_resolver()
    def get_default():
        return default_guard

    @auth.guard_resolver("web")
    def get_web():
        return web_guard

    @permission(["tasks:read"], guard="web")
    def handler():
        return "ok"

    with app.app_context():
        assert handler() == "ok"


def test_permission_with_an_unknown_guard(app, auth):
    @auth.guard_resolver()
    def get_guard():
        return Guard()

    @permission(["tasks:read"], guard="missing")
    def handler():
        return "ok"

    with app.app_context():
        with pytest.raises(ValueError, match="Unknown guard"):
            handler()


def test_permission_rejects_an_invalid_strategy():
    with pytest.raises(ValueError):
        permission(["tasks:read"], strategy="everything")


def test_permission_requests_a_required_user(app, auth, guard):
    guard.user = None

    @permission(["tasks:read"])
    def handler():
        return "ok"

    with app.app_context():
        with pytest.raises(AttributeError):
            handler()


def test_permission_can_return_a_response(app, auth):
    @auth.guard_resolver()
    def get_guard():
        class ResponseGuard(Guard):
            user = User([])

            def permission_check_failed(self):
                return {"error": "forbidden"}, 403

        return ResponseGuard()

    @permission(["tasks:read"])
    def handler():
        return "ok"

    with app.app_context():
        assert handler() == ({"error": "forbidden"}, 403)


def test_permission_preserves_the_function_metadata(auth):
    @permission(["tasks:read"])
    def handler():
        """Docstring."""

    assert handler.__name__ == "handler"
    assert handler.__doc__ == "Docstring."


def test_permission_and_logged_in_in_a_flask_view(app, auth, guard):
    guard.user = User(["tasks:read"])

    @app.get("/tasks")
    @logged_in()
    @permission(["tasks:read"])
    def index():
        return {"ok": True}

    @app.get("/admin")
    @permission(["admin:read"])
    def admin():
        return {"ok": True}

    client = app.test_client()

    assert client.get("/tasks").json == {"ok": True}
    assert client.get("/admin").status_code == 403