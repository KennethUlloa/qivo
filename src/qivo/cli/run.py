import click
from qivo.settings import Application
from qivo.utils import import_symbol
from flask import Flask


@click.command("run")
@click.option("--host", default=None, show_default=True)
@click.option("--port", default=None, show_default=True)
@click.option("--debug", is_flag=True, help="Enable debugging.", default=False)
def run_app(host: str, port: int, debug: bool) -> None:
    """Run a Flask application."""
    application = Application.from_toml("qivo.toml")
    app = import_symbol(application.import_path)

    if callable(app) and not isinstance(app, Flask):
        app = app()

    if not isinstance(app, Flask):
        raise RuntimeError(f"Expected a Flask app, got {type(app)}")

    data ={
        "host": host if host is not None else application.host,
        "port": port if port is not None else application.port,
        "debug": debug,
        "extra_files": application.extra_files
    }
    
    app.run(**data)
