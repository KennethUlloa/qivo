import importlib
from typing import Any

from flask import Flask
from click import command, option

def import_string(import_path: str) -> Any:
    """Import an object based on a string import path."""
    module_path, _, attr = import_path.rpartition(":")
    if not module_path:
        raise ValueError(f"Invalid import path: {import_path}")
    module = importlib.import_module(module_path)
    return getattr(module, attr)


def run_app(import_path: str, host: str, port: int, debug: bool) -> None:
    """Run a Flask application."""
    app = import_string(import_path)

    if callable(app) and not isinstance(app, Flask):
        app = app()

    if not isinstance(app, Flask):
        raise RuntimeError(f"Expected a Flask app, got {type(app)}")
    
    app.run(host=host, port=port, debug=debug)



