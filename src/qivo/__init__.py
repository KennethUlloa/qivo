from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Callable

from flask import Flask

from qivo.dependencies import DIContainer, DependencyInjectionExtension
from qivo.extensions import ViewExtension
from qivo.guards import Authenticator, AuthorizationExtension, Policy
from qivo.serialization import SerializationExtension, Serializer


class Qivo:
    def __init__(
        self,
        app: Flask | None = None,
        serializer: Serializer | None = None,
        container: DIContainer | None = None,
        guards: Mapping[str, Authenticator] | None = None,
        view_extensions: list[ViewExtension] | None = None,
    ):
        self.app: Flask | None = None
        self.serializer = serializer or Serializer()
        self.container = container or DIContainer()
        self.guards = dict(guards or {})
        self.default_guard = "web"
        self.view_extensions: list[ViewExtension] = [
            AuthorizationExtension(),
            DependencyInjectionExtension(),
            SerializationExtension(),
        ]
        for extension in view_extensions or ():
            self.register_view_extension(extension)

        if app is not None:
            self.init_app(app)

    def init_app(self, app: Flask) -> None:
        """Attach this Qivo extension to one Flask application."""
        if self.app is not None and self.app is not app:
            raise RuntimeError("A Qivo instance can be attached to only one Flask app")

        existing = app.extensions.get("qivo")
        if existing is not None and existing is not self:
            raise RuntimeError("A Qivo extension is already registered on this app")

        self.app = app
        app.extensions["qivo"] = self

    def register_view_extension(self, extension: ViewExtension) -> None:
        """Add a view wrapper; extensions run in registration order outside-in."""
        self.view_extensions.append(extension)

    def view(self, **options: Any):
        """Wrap a view with Qivo features without registering a Flask route."""
        immutable_options = MappingProxyType(dict(options))

        def decorator(view_func: Callable):
            for extension in reversed(self.view_extensions):
                view_func = extension.wrap_view(
                    self,
                    view_func,
                    options=immutable_options,
                )
            return view_func

        return decorator

    def guard(self, name: str | None = None):
        guard_name = name or self.default_guard
        return self.guards[guard_name]

    def _serialize_view_response(self, rv):
        target = rv
        if isinstance(rv, tuple):
            target = rv[0]

        serialized = self.serializer.serialize(target)

        if isinstance(rv, tuple) and len(rv) > 1:
            return (serialized,) + rv[1:]

        return serialized
