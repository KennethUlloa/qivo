from collections.abc import Callable
from enum import StrEnum
from functools import wraps

from flask import Flask, current_app

from qivo.contracts.auth import AuthGuard
from qivo.ext.base import BaseExtension
from qivo.utils import ViewDecorator


class AuthManager(BaseExtension):
    name = "qivo.auth"

    def __init__(self, app: Flask | None = None):
        super().__init__(app)

        self._guard_resolvers: dict[str, Callable[[], AuthGuard]] = {}

    def get_guard(self, name: str | None = None) -> AuthGuard:
        guard = self._guard_resolvers.get(name)

        if guard is None:
            raise ValueError(f"Unknown guard {name}")

        return guard()

    def guard_resolver(self, name: str = None):
        def decorator(func):
            self._guard_resolvers[name] = func
            return func

        return decorator


def _get_auth() -> AuthManager:
    return AuthManager.current()

def current_user():
    return _get_auth().get_guard().get_current_user()


def logged_in(guard_name: str | None = None):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            guard = _get_auth().get_guard(guard_name)
            if not guard.check_logged_in():
                return guard.logged_in_check_failed()
            return func(*args, **kwargs)

        return wrapper

    return decorator


class PermissionStrategy(StrEnum):
    ANY = "any"
    ALL = "all"

class permission(ViewDecorator):
    def __init__(self, permissions: list[str], *, guard: str = None, strategy: PermissionStrategy = PermissionStrategy.ANY):
        self.permissions = permissions
        self.strategy = PermissionStrategy(strategy)
        self.guard = guard

    def handle_function(self, function, *args, **kwargs):
        guard = AuthManager.current().get_guard(self.guard)
        current_user = guard.get_current_user(True)
        can_access = False

        if self.strategy == PermissionStrategy.ANY:
            can_access = current_user.any_permission(self.permissions)
        elif self.strategy == PermissionStrategy.ALL:
            can_access = current_user.all_permissions(self.permissions)

        if not can_access:
            return guard.permission_check_failed()

        return function(*args, **kwargs)