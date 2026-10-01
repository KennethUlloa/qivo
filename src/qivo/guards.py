from abc import abstractmethod
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, Mapping, Protocol

from werkzeug.exceptions import Forbidden, Unauthorized

if TYPE_CHECKING:
    from qivo import Qivo


class Authenticated(Protocol):
    def get_id(self) -> str:
        raise NotImplementedError

    def is_active(self) -> bool:
        raise NotImplementedError

    def get_permissions(self) -> list[str]:
        raise NotImplementedError


class Authenticator:
    @abstractmethod
    def require_authentication(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def authenticate(self, data: Any) -> Authenticated:
        raise NotImplementedError

    @abstractmethod
    def authenticated(self) -> Authenticated:
        raise NotImplementedError

    @abstractmethod
    def permissions(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def has_permission(self, permission: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def logout(self) -> None:
        raise NotImplementedError


class Policy:
    def check(self, authenticator: Authenticator):
        raise NotImplementedError


class PermissionPolicy(Policy):
    permission: str

    def __init__(self, permission: str):
        self.permission = permission


class WithAny(PermissionPolicy):
    permissions: list[str]

    def __init__(self, permissions: list[str]):
        self.permissions = permissions

    def check(self, authenticator: Authenticator):
        if not any(
            authenticator.has_permission(permission) for permission in self.permissions
        ):
            raise Unauthorized()


class WithAll(PermissionPolicy):
    permissions: list[str]

    def __init__(self, permissions: list[str]):
        self.permissions = permissions

    def check(self, authenticator: Authenticator):
        if not all(
            authenticator.has_permission(permission) for permission in self.permissions
        ):
            raise Forbidden()


class WithOne(PermissionPolicy):
    permission: str

    def __init__(self, permission: str):
        self.permission = permission

    def check(self, authenticator: Authenticator):
        if not authenticator.has_permission(self.permission):
            raise Forbidden()


class AuthorizationExtension:
    def wrap_view(
        self,
        app: Qivo,
        view_func: Callable,
        *,
        options: Mapping[str, Any],
    ) -> Callable:
        auth = options.get("auth", False)
        policies: list[Policy] = options.get("policies")

        if not auth and not policies:
            return view_func

        @wraps(view_func)
        def wrapper(*args, **kwargs):
            authenticator = app.guard(options.get("guard"))
            if auth or policies:
                authenticator.require_authentication()

            for policy in policies or ():
                policy.check(authenticator)

            return view_func(*args, **kwargs)

        return wrapper
