from jwt import PyJWTError
from abc import abstractmethod
from typing import Any, Sequence

from werkzeug.exceptions import Forbidden
from flask import session, request

from qivo.accessors import GField
from qivo.auth.providers import JWTProvider

from .ext import BaseAuthHandler, BasePolicy, BaseUser


class AuthContext:
    cached_user: BaseUser = GField()


auth_ctx = AuthContext()


class BasePermissionPolicy(BasePolicy):
    def __init__(self, permissions: Sequence[str]):
        self.permissions = permissions

    def has_permission(self, target_permission: str, user_permissions: Sequence[str]):
        scope, separator, action = target_permission.partition(":")

        if not scope:
            return False

        return target_permission in user_permissions or f"{scope}:*" in user_permissions


class HasAll(BasePermissionPolicy):
    def apply(self, user: BaseUser):
        current = user.get_permissions()
        if not all(self.has_permission(target, current) for target in self.permissions):
            raise Forbidden()


class HasAny(BasePermissionPolicy):
    def apply(self, user: BaseUser):
        current = user.get_permissions()
        if not any(self.has_permission(target, current) for target in self.permissions):
            raise Forbidden()


class AbstractSessionAuthHandler(BaseAuthHandler):
    session_key = "user_id"

    def get_current_user(self) -> BaseUser:
        if auth_ctx.cached_user:
            return auth_ctx.cached_user

        if self.session_key not in session or not session[self.session_key]:
            return None

        user_id = session[self.session_key]
        user = self.get_user(user_id)

        auth_ctx.cached_user = user
        return user

    @abstractmethod
    def get_user(self, user_id: Any) -> BaseUser:
        raise NotImplementedError()


class AbstractJWTAuthHandler(BaseAuthHandler):
    def __init__(self, jwt_provider: JWTProvider):
        self.jwt_provider = jwt_provider

    @abstractmethod
    def get_user(self, user_id: Any) -> BaseUser:
        raise NotImplementedError()

    def get_current_user(self):
        if auth_ctx.cached_user:
            return auth_ctx.cached_user

        authorization = request.authorization

        if not authorization:
            return None

        token = authorization.token

        if not token:
            return None

        try:
            payload = self.jwt_provider.payload(token)

            if "sub" not in payload:
                return None

            sub = payload["sub"]
            user = self.get_user(sub)
            auth_ctx.cached_user = user
            return user
        except PyJWTError:
            return None
