from abc import abstractmethod
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, Mapping

from werkzeug.exceptions import Forbidden, Unauthorized

if TYPE_CHECKING:
    from qivo import Qivo


@dataclass
class Authenticated:
    permissions: list[str]


class Authenticator:
    def is_authenticated(self) -> bool:
        return False

    def authenticate(self):
        if not self.is_authenticated():
            raise Unauthorized()

    @abstractmethod
    def authenticated(self) -> Authenticated:
        raise NotImplementedError


class Policy:
    def check(self, authenticator: Authenticator):
        pass


class WithAll(Policy):
    permissions: list[str]

    def __init__(self, permissions: list[str]):
        self.permissions = permissions

    def check(self, authenticator: Authenticator):
        permissions = self.get_permissions(authenticator)

        if not all(permission in permissions for permission in self.permissions):
            raise Forbidden()

    def get_permissions(self, authenticator: Authenticator):
        return authenticator.authenticated().permissions


class AuthorizationExtension:
    def wrap_view(
        self,
        app: Qivo,
        view_func: Callable,
        *,
        options: Mapping[str, Any],
    ) -> Callable:
        auth = options.get("auth", False)
        policies = options.get("policies")

        if not auth and not policies:
            return view_func

        @wraps(view_func)
        def wrapper(*args, **kwargs):
            authenticator = app.guard(options.get("guard"))
            if auth or policies:
                authenticator.authenticate()

            for policy in policies or ():
                policy.check(authenticator)

            return view_func(*args, **kwargs)

        return wrapper
