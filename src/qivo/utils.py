from collections.abc import Callable
from functools import wraps
import importlib


def import_symbol(path: str):
    module_path, _, attr = path.rpartition(":")
    if not module_path:
        raise ValueError(f"Invalid import path: {path}")
    module = importlib.import_module(module_path)
    return getattr(module, attr)


class ViewDecorator:
    def __call__(self, f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            return self.handle_response(self.handle_function(f, *args, **kwargs))

        return wrapper

    def handle_response(self, response):
        return response

    def handle_function(self, function: Callable, *args, **kwargs):
        return function(*args, **kwargs)