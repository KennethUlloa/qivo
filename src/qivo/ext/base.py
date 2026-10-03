from typing import Self

from flask import Flask, current_app


class BaseExtension:
    app: Flask | None = None
    name: str

    def __init__(self, app: Flask | None = None):
        if app is not None:
            self.init_app(app)

    def init_app(self, app: Flask):
        self.app = app

        if self.name in app.extensions:
            raise RuntimeError(f"An {self.__class__.__name__} instance can be attached to only one app")

        app.extensions[self.name] = self

        self.setup(app)

    def setup(self, app: Flask):
        pass

    @classmethod
    def current(cls) -> Self:
        instance = current_app.extensions.get(cls.name)

        if instance is None or not isinstance(instance, cls):
            raise RuntimeError(f"{cls.__name__} is not attached to the app")

        return instance
