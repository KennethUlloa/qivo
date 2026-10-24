from collections.abc import Callable
from typing import Optional, Protocol, Sequence

from flask import Flask
from werkzeug.exceptions import Unauthorized
from qivo.ext.base import BaseExtension
from qivo.utils import ViewDecorator

DEFAULT_HANDLER_NAME = "default"


class BaseUser(Protocol):
    def get_id(self) -> str:
        """
        Get the user id
        """

    def get_permissions(self) -> Sequence[str]:
        """
        Get the user permissions
        """

    def get_roles(self) -> Sequence[str]:
        """
        Get the user roles
        """

    def is_active(self) -> bool:
        """
        Check if the user is active
        """


class BaseAuthHandler:
    def get_current_user(self) -> Optional[BaseUser]:
        """
        Read the user from a context (ie. session, jwt token)
        """
        raise NotImplementedError()

    def unauthorized_error(self):
        return Unauthorized()


class BasePolicy(Protocol):
    def apply(self, user: BaseUser):
        """
        Applies the logic for the provided user. Exception must be raised to stop the flow.
        """


class AuthManager(BaseExtension):
    def __init__(self, provider: Callable[[str], BaseAuthHandler], app: Flask = None):
        if not provider:
            raise RuntimeError(
                "The provider is required before initializing the authentication engine."
            )
        self._provider = provider

        super().__init__(app)

    def handler(self, name: str = DEFAULT_HANDLER_NAME) -> BaseAuthHandler:
        _handler = self._provider(name)

        if not _handler:
            raise ValueError(f"There's no handler available for name {name}")

        return _handler


def auth_handler(name: str = DEFAULT_HANDLER_NAME) -> BaseAuthHandler:
    ext = AuthManager.current()
    return ext.handler(name)


def current_user(
    *, required: bool, handler_name: str = DEFAULT_HANDLER_NAME
) -> BaseUser:
    handler = auth_handler(handler_name)
    user = handler.get_current_user()

    if not user and required:
        raise handler.unauthorized_error() or Unauthorized()

    return user


class _AuthDecorator(ViewDecorator):
    def __init__(
        self,
        policies: Sequence[BasePolicy] = None,
        handler_name: str = DEFAULT_HANDLER_NAME,
    ):
        self.policies = policies or []
        self.handler_name = handler_name

    def handle_function(self, function, *args, **kwargs):
        user = current_user(required=True, handler_name=self.handler_name)
        for policy in self.policies:
            policy.apply(user)

        return function(*args, **kwargs)


def auth(
    policies: Sequence[BasePolicy] = None, handler_name: str = DEFAULT_HANDLER_NAME
):
    return _AuthDecorator(policies, handler_name)
