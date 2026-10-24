import jwt
import pytest

from datetime import datetime

from jwt import PyJWTError
from werkzeug.exceptions import Forbidden, Unauthorized

from qivo.auth import (
    AuthManager,
    BaseAuthHandler,
    BasePermissionPolicy,
    HasAll,
    HasAny,
    auth,
    auth_handler,
    current_user,
)
from qivo.auth.defaults import (
    AbstractJWTAuthHandler,
    AbstractSessionAuthHandler,
    auth_ctx,
)
from qivo.auth.providers import JWTProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class User:
    def __init__(self, permissions=(), user_id="1", roles=(), active=True):
        self.permissions = permissions
        self.user_id = user_id
        self.roles = roles
        self.active = active

    def get_id(self):
        return self.user_id

    def get_permissions(self):
        return self.permissions

    def get_roles(self):
        return self.roles

    def is_active(self):
        return self.active


class StubHandler(BaseAuthHandler):
    def __init__(self, user=None, error=None):
        self.user = user
        self.error = error
        self.calls = 0

    def get_current_user(self):
        self.calls += 1
        return self.user

    def unauthorized_error(self):
        return self.error if self.error is not None else super().unauthorized_error()


class Provider:
    """Named handler resolver used by AuthManager."""

    def __init__(self, **handlers):
        self.handlers = handlers
        self.requested = []

    def __call__(self, name):
        self.requested.append(name)
        return self.handlers.get(name)


class SessionHandler(AbstractSessionAuthHandler):
    def __init__(self, users=None):
        self.users = users or {}
        self.lookups = []

    def get_user(self, user_id):
        self.lookups.append(user_id)
        return self.users.get(user_id)


class JWTHandler(AbstractJWTAuthHandler):
    def __init__(self, jwt_provider, users=None):
        super().__init__(jwt_provider)
        self.users = users or {}
        self.lookups = []

    def get_user(self, user_id):
        self.lookups.append(user_id)
        return self.users.get(user_id)


@pytest.fixture
def user():
    return User(permissions=["users:read"], user_id="1")


@pytest.fixture
def provider():
    return Provider()


@pytest.fixture
def manager(app, provider):
    return AuthManager(provider, app)


@pytest.fixture
def session_app(app):
    app.secret_key = "test-secret"
    return app


@pytest.fixture
def jwt_provider():
    return JWTProvider(
        secret_key="secret",
        access_key_expire=3600,
        refresh_key_expire=7200,
        algorithm="HS256",
    )


# ---------------------------------------------------------------------------
# AuthManager
# ---------------------------------------------------------------------------


def test_auth_manager_requires_a_provider():
    with pytest.raises(RuntimeError, match="provider is required"):
        AuthManager(None)


def test_auth_manager_registers_itself_on_the_app(app, manager):
    assert manager.app is app
    assert app.extensions["qivo.auth"] is manager


def test_auth_manager_can_be_resolved_from_the_app_context(app, manager):
    with app.app_context():
        assert AuthManager.current() is manager


def test_auth_manager_cannot_be_attached_twice_to_the_same_app(provider, manager):
    with pytest.raises(RuntimeError, match="only one app"):
        AuthManager(provider, manager.app)


def test_auth_manager_uses_the_default_handler(provider, manager):
    handler = StubHandler()

    provider.handlers["default"] = handler

    assert manager.handler() is handler
    assert provider.requested == ["default"]


def test_auth_manager_resolves_named_handlers(provider, manager):
    handler = StubHandler()

    provider.handlers["api"] = handler

    assert manager.handler("api") is handler
    assert provider.requested == ["api"]


def test_auth_manager_raises_for_unknown_handlers(provider, manager):
    with pytest.raises(ValueError, match="unknown"):
        manager.handler("unknown")


def test_auth_manager_asks_the_provider_on_every_call(provider, manager):
    provider.handlers["default"] = StubHandler()

    manager.handler()
    manager.handler()

    assert provider.requested == ["default", "default"]


# ---------------------------------------------------------------------------
# Module level accessors
# ---------------------------------------------------------------------------


def test_auth_handler_returns_the_current_manager_handler(app, provider, manager):
    handler = StubHandler()
    provider.handlers["default"] = handler

    with app.app_context():
        assert auth_handler() is handler


def test_auth_handler_requires_an_application_context(manager):
    with pytest.raises(RuntimeError):
        auth_handler()


def test_base_handler_requires_get_current_user_to_be_implemented():
    with pytest.raises(NotImplementedError):
        BaseAuthHandler().get_current_user()


def test_base_handler_default_unauthorized_error():
    assert isinstance(BaseAuthHandler().unauthorized_error(), Unauthorized)


# ---------------------------------------------------------------------------
# current_user
# ---------------------------------------------------------------------------


def test_current_user_returns_the_authenticated_user(app, provider, manager, user):
    provider.handlers["default"] = StubHandler(user)

    with app.app_context():
        assert current_user(required=False) is user


def test_current_user_returns_none_when_optional_and_anonymous(app, provider, manager):
    provider.handlers["default"] = None

    with app.app_context():
        assert current_user(required=False) is None


def test_current_user_raises_unauthorized_when_required(app, provider, manager):
    provider.handlers["default"] = None

    with app.app_context():
        with pytest.raises(Unauthorized):
            current_user(required=True)


def test_current_user_raises_the_handler_error(app, provider, manager):
    error = Forbidden()
    provider.handlers["default"] = StubHandler(error=error)

    with app.app_context():
        with pytest.raises(Forbidden):
            current_user(required=True)


def test_current_user_uses_the_requested_handler(app, provider, manager, user):
    provider.handlers["api"] = StubHandler(user)

    with app.app_context():
        assert current_user(required=True, handler_name="api") is user


# ---------------------------------------------------------------------------
# Permission policies
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("target", "granted", "expected"),
    [
        ("users:read", ["users:read"], True),
        ("users:read", ["users:*"], True),
        ("users:read", ["posts:*"], False),
        ("users:read", ["users:write"], False),
        ("users:read", [], False),
        ("users:read", ["users:read:extra"], False),
        ("manage", ["manage"], True),
    ],
)
def test_permission_matching(target, granted, expected):
    policy = BasePermissionPolicy([])

    assert policy.has_permission(target, granted) is expected


def test_has_all_allows_when_every_permission_is_present():
    policy = HasAll(["users:read", "users:write"])

    policy.apply(User(["users:read", "users:write"]))


def test_has_all_accepts_scope_wildcards():
    policy = HasAll(["users:read", "users:write"])

    policy.apply(User(["users:*"]))


def test_has_all_rejects_when_one_permission_is_missing():
    policy = HasAll(["users:read", "users:write"])

    with pytest.raises(Forbidden):
        policy.apply(User(["users:read"]))


def test_has_all_with_no_requirements_allows_the_user():
    HasAll([]).apply(User([]))


def test_has_any_allows_when_at_least_one_permission_is_present():
    policy = HasAny(["users:read", "users:write"])

    policy.apply(User(["users:write"]))


def test_has_any_accepts_scope_wildcards():
    HasAny(["users:read"]).apply(User(["users:*"]))


def test_has_any_rejects_when_no_permission_is_present():
    policy = HasAny(["users:read", "users:write"])

    with pytest.raises(Forbidden):
        policy.apply(User(["posts:read"]))


def test_has_any_with_no_requirements_rejects_the_user():
    with pytest.raises(Forbidden):
        HasAny([]).apply(User(["users:read"]))


def test_policies_read_permissions_from_the_user():
    policy = HasAny(["users:read"])
    user = User(["users:read"])

    assert policy.permissions == ["users:read"]
    policy.apply(user)


# ---------------------------------------------------------------------------
# auth decorator
# ---------------------------------------------------------------------------


def test_auth_calls_the_view_when_authenticated(app, provider, manager, user):
    provider.handlers["default"] = StubHandler(user)
    calls = []

    @auth()
    def view(value, flag=False):
        calls.append((value, flag))
        return "ok"

    with app.app_context():
        assert view("payload", flag=True) == "ok"

    assert calls == [("payload", True)]


def test_auth_rejects_anonymous_requests(app, provider, manager):
    provider.handlers["default"] = None

    @auth()
    def view():
        return "ok"

    with app.app_context():
        with pytest.raises(Unauthorized):
            view()


def test_auth_applies_policies_in_order(app, provider, manager, user):
    provider.handlers["default"] = StubHandler(user)
    seen = []

    class RecordingPolicy:
        def __init__(self, name):
            self.name = name

        def apply(self, current_user):
            seen.append((self.name, current_user))

    @auth([RecordingPolicy("first"), RecordingPolicy("second")])
    def view():
        return "ok"

    with app.app_context():
        assert view() == "ok"

    assert seen == [("first", user), ("second", user)]


def test_auth_stops_when_a_policy_rejects_the_user(app, provider, manager, user):
    provider.handlers["default"] = StubHandler(user)
    called = []

    @auth([HasAll(["admin:read"])])
    def view():
        called.append(True)
        return "ok"

    with app.app_context():
        with pytest.raises(Forbidden):
            view()

    assert called == []


def test_auth_uses_the_requested_handler(app, provider, manager, user):
    provider.handlers["api"] = StubHandler(user)

    @auth(handler_name="api")
    def view():
        return current_user(required=False, handler_name="api")

    with app.app_context():
        assert view() is user


def test_auth_preserves_view_metadata(app, provider, manager, user):
    provider.handlers["default"] = StubHandler(user)

    @auth()
    def view():
        """View documentation."""
        return "ok"

    assert view.__name__ == "view"
    assert view.__doc__ == "View documentation."


# ---------------------------------------------------------------------------
# Session auth handler
# ---------------------------------------------------------------------------


def test_session_handler_returns_none_without_a_session_key(session_app):
    handler = SessionHandler()

    with session_app.test_request_context():
        assert handler.get_current_user() is None

    assert handler.lookups == []


def test_session_handler_ignores_empty_user_ids(session_app):
    handler = SessionHandler()
    from flask import session

    with session_app.test_request_context():
        session["user_id"] = ""
        assert handler.get_current_user() is None

    assert handler.lookups == []


def test_session_handler_loads_the_user_from_the_session(session_app, user):
    handler = SessionHandler({"1": user})
    from flask import session

    with session_app.test_request_context():
        session["user_id"] = "1"
        assert handler.get_current_user() is user

    assert handler.lookups == ["1"]


def test_session_handler_caches_the_user_per_request(session_app, user):
    handler = SessionHandler({"1": user})
    from flask import session

    with session_app.test_request_context():
        session["user_id"] = "1"
        assert handler.get_current_user() is user
        assert handler.get_current_user() is user
        assert auth_ctx.cached_user is user

    assert handler.lookups == ["1"]


def test_session_handler_returns_the_cached_user_first(session_app, user):
    handler = SessionHandler()

    with session_app.test_request_context():
        auth_ctx.cached_user = user
        assert handler.get_current_user() is user

    assert handler.lookups == []


def test_session_handler_can_use_a_custom_session_key(session_app, user):
    class CustomSessionHandler(SessionHandler):
        session_key = "uid"

    handler = CustomSessionHandler({"1": user})
    from flask import session

    with session_app.test_request_context():
        session["user_id"] = "ignored"
        session["uid"] = "1"
        assert handler.get_current_user() is user

    assert handler.lookups == ["1"]


# ---------------------------------------------------------------------------
# JWT auth handler
# ---------------------------------------------------------------------------


def test_jwt_handler_returns_none_without_authorization(app, jwt_provider, user):
    handler = JWTHandler(jwt_provider, {"1": user})

    with app.test_request_context():
        assert handler.get_current_user() is None

    assert handler.lookups == []


def test_jwt_handler_loads_the_user_from_an_access_token(app, jwt_provider, user):
    handler = JWTHandler(jwt_provider, {"1": user})
    token = jwt_provider.access_key("1")

    with app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
        assert handler.get_current_user() is user

    assert handler.lookups == ["1"]


def test_jwt_handler_loads_the_user_from_a_refresh_token(app, jwt_provider, user):
    handler = JWTHandler(jwt_provider, {"1": user})
    token = jwt_provider.refresh_key("1")

    with app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
        assert handler.get_current_user() is user

    assert handler.lookups == ["1"]


def test_jwt_handler_rejects_malformed_tokens(app, jwt_provider, user):
    handler = JWTHandler(jwt_provider, {"1": user})

    with app.test_request_context(headers={"Authorization": "Bearer not-a-token"}):
        assert handler.get_current_user() is None

    assert handler.lookups == []


def test_jwt_handler_rejects_tokens_signed_with_another_secret(app, user):
    issuer = JWTProvider("other-secret", 3600, 7200, "HS256")
    handler = JWTHandler(JWTProvider("secret", 3600, 7200, "HS256"), {"1": user})
    token = issuer.access_key("1")

    with app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
        assert handler.get_current_user() is None

    assert handler.lookups == []


def test_jwt_handler_rejects_expired_tokens(app, user):
    provider = JWTProvider("secret", -1, -1, "HS256")
    handler = JWTHandler(provider, {"1": user})
    token = provider.access_key("1")

    with app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
        assert handler.get_current_user() is None

    assert handler.lookups == []


def test_jwt_handler_requires_the_subject_claim(app, jwt_provider, user):
    handler = JWTHandler(jwt_provider, {"1": user})
    token = jwt.encode({"role": "admin"}, "secret", algorithm="HS256")

    with app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
        assert handler.get_current_user() is None

    assert handler.lookups == []


def test_jwt_handler_caches_the_user_per_request(app, jwt_provider, user):
    handler = JWTHandler(jwt_provider, {"1": user})
    token = jwt_provider.access_key("1")

    with app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
        assert handler.get_current_user() is user
        assert handler.get_current_user() is user
        assert auth_ctx.cached_user is user

    assert handler.lookups == ["1"]


def test_jwt_handler_returns_the_cached_user_first(app, jwt_provider, user):
    handler = JWTHandler(jwt_provider)

    with app.test_request_context():
        auth_ctx.cached_user = user
        assert handler.get_current_user() is user

    assert handler.lookups == []


# ---------------------------------------------------------------------------
# JWT provider
# ---------------------------------------------------------------------------


def test_access_key_contains_the_expected_claims(jwt_provider):
    before = datetime.now().timestamp()

    token = jwt_provider.access_key("user-1", role="admin")

    after = datetime.now().timestamp()
    payload = jwt_provider.payload(token)

    assert payload["sub"] == "user-1"
    assert payload["type"] == "access"
    assert payload["role"] == "admin"
    assert before + 3600 <= payload["exp"] <= after + 3600


def test_refresh_key_contains_the_expected_claims(jwt_provider):
    before = datetime.now().timestamp()

    token = jwt_provider.refresh_key("user-1", scope="refresh")

    after = datetime.now().timestamp()
    payload = jwt_provider.payload(token)

    assert payload["sub"] == "user-1"
    assert payload["type"] == "refresh"
    assert payload["scope"] == "refresh"
    assert before + 7200 <= payload["exp"] <= after + 7200


def test_payload_rejects_tokens_signed_with_another_secret(jwt_provider):
    token = JWTProvider("other-secret", 3600, 7200, "HS256").access_key("user-1")

    with pytest.raises(PyJWTError):
        jwt_provider.payload(token)


def test_payload_rejects_malformed_tokens(jwt_provider):
    with pytest.raises(PyJWTError):
        jwt_provider.payload("not-a-token")


def test_payload_rejects_expired_tokens():
    provider = JWTProvider("secret", -1, -1, "HS256")
    token = provider.access_key("user-1")

    with pytest.raises(PyJWTError):
        provider.payload(token)


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


def test_authenticated_route_with_session_handler(session_app, user):
    manager = AuthManager(
        Provider(default=SessionHandler({"1": user})),
        session_app,
    )

    @session_app.route("/me")
    @auth()
    def me():
        return {"id": current_user(required=True).get_id()}

    with session_app.test_client() as client:
        assert client.get("/me").status_code == 401

        with client.session_transaction() as session_data:
            session_data["user_id"] = "1"

        response = client.get("/me")

    assert response.status_code == 200
    assert response.get_json() == {"id": "1"}
    assert manager.handler("default").lookups == ["1"]


def test_route_with_permission_policy(session_app, user):
    AuthManager(Provider(default=SessionHandler({"1": user})), session_app)

    @session_app.route("/users")
    @auth([HasAll(["users:read"])])
    def list_users():
        return {"users": []}

    with session_app.test_client() as client:
        with client.session_transaction() as session_data:
            session_data["user_id"] = "1"

        assert client.get("/users").status_code == 200

    restricted_user = User(permissions=["posts:read"], user_id="2")
    second_app = type(session_app)("restricted")
    second_app.secret_key = "test-secret"
    AuthManager(Provider(default=SessionHandler({"2": restricted_user})), second_app)

    @second_app.route("/users")
    @auth([HasAll(["users:read"])])
    def restricted_list_users():
        return {"users": []}

    with second_app.test_client() as client:
        with client.session_transaction() as session_data:
            session_data["user_id"] = "2"

        assert client.get("/users").status_code == 403
