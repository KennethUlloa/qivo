import importlib
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
from alembic.util import CommandError

from qivo.cli.init import init_command
from qivo.db.sql import AlembicMigrations, MigrationConfig, SQLAlchemyConfig
from qivo.db.sql.sessions import prune_sessions


@click.group()
def cli() -> None:
    """Create and manage Qivo applications."""


cli.add_command(init_command)


def _migration_options(function):
    options = (
        click.option(
            "--config", type=click.Path(path_type=Path), default=Path("qivo.toml")
        ),
        click.option("--database-url"),
        click.option("--model-base"),
        click.option(
            "--models", multiple=True, help="Model module to import; repeat as needed."
        ),
        click.option("--migrations-dir", type=click.Path(path_type=Path)),
        click.option("--compare-type/--no-compare-type", default=None),
    )
    for option in options:
        function = option(function)
    return function


@dataclass(frozen=True)
class ProjectSettings:
    database_url: str
    engine_options: dict[str, Any]
    model_bases: tuple[Any, ...]
    metadata: Any
    migrations_directory: Path
    compare_type: bool
    render_as_batch: bool

    def create_engine(self):
        return SQLAlchemyConfig(self.database_url, self.engine_options).create_engine()


def _load_project(
    config_path: Path,
    database_url: str | None,
    model_base: str | None,
    model_modules: tuple[str, ...],
    migrations_dir: Path | None,
    compare_type: bool | None,
) -> ProjectSettings:
    """Resolve qivo.toml and the command flags into everything a command needs."""

    config_path = config_path.resolve()
    project_config: dict[str, Any] = {}
    if config_path.exists():
        with config_path.open("rb") as config_file:
            project_config = tomllib.load(config_file)

    sqlalchemy_options = project_config.get("sqlalchemy", {})
    migration_options = project_config.get("migrations", {})
    resolved_database_url = database_url or sqlalchemy_options.get(
        "url", "sqlite:///app.db"
    )
    configured_model_bases = sqlalchemy_options.get("model_bases")
    configured_model_modules = sqlalchemy_options.get("models")
    if model_modules:
        resolved_model_modules = model_modules
    elif configured_model_modules is not None:
        resolved_model_modules = tuple(configured_model_modules)
    elif configured_model_bases is not None:
        resolved_model_modules = ()
    else:
        resolved_model_modules = ("app.models",)
    if model_base is not None:
        resolved_model_bases = (model_base,)
    elif configured_model_bases is None:
        resolved_model_bases = (
            sqlalchemy_options.get("model_base", "qivo.db.sql:Model"),
        )
    elif isinstance(configured_model_bases, list):
        resolved_model_bases = tuple(configured_model_bases)
    else:
        raise ValueError("sqlalchemy.model_bases must be an array")
    if not resolved_model_bases:
        raise ValueError("At least one model base must be configured")
    resolved_directory = migrations_dir or Path(
        migration_options.get("directory", "migrations")
    )
    project_root = str(config_path.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    for module_name in resolved_model_modules:
        importlib.import_module(module_name)

    model_bases: list[Any] = []
    metadatas: list[Any] = []
    for model_base_path in resolved_model_bases:
        module_name, separator, attribute_path = model_base_path.partition(":")
        if not separator:
            raise ValueError("model_base must use 'module:attribute' syntax")
        model_base_object: Any = importlib.import_module(module_name)
        for attribute in attribute_path.split("."):
            model_base_object = getattr(model_base_object, attribute)
        metadata = getattr(model_base_object, "metadata", None)
        if metadata is None:
            raise ValueError(
                f"Configured model base {model_base_path!r} has no metadata"
            )
        model_bases.append(model_base_object)
        metadatas.append(metadata)

    metadata = metadatas[0] if len(metadatas) == 1 else tuple(metadatas)

    return ProjectSettings(
        database_url=resolved_database_url,
        engine_options=sqlalchemy_options.get("engine_options", {}),
        model_bases=tuple(model_bases),
        metadata=metadata,
        migrations_directory=resolved_directory,
        compare_type=(
            compare_type
            if compare_type is not None
            else migration_options.get("compare_type", True)
        ),
        render_as_batch=migration_options.get("render_as_batch", True),
    )


def _load_migrations(settings: ProjectSettings) -> AlembicMigrations:
    return AlembicMigrations(
        settings.create_engine(),
        metadata=settings.metadata,
        config=MigrationConfig(
            directory=settings.migrations_directory,
            compare_type=settings.compare_type,
            render_as_batch=settings.render_as_batch,
        ),
    )


@cli.command("migrate")
@_migration_options
@click.option("-m", "--message", default="autogenerated", show_default=True)
@click.option(
    "--empty", is_flag=True, help="Create a blank migration without autogeneration."
)
def migrate(
    config: Path,
    database_url: str | None,
    model_base: str | None,
    models: tuple[str, ...],
    migrations_dir: Path | None,
    compare_type: bool | None,
    message: str,
    empty: bool,
) -> None:
    """Review model changes and create an Alembic revision."""
    _run_migration_command(
        config,
        database_url,
        model_base,
        models,
        migrations_dir,
        compare_type,
        lambda migrations: _create_revision(migrations, message, not empty),
    )


@cli.command("migrate:apply")
@_migration_options
@click.argument("revision", required=False, default="head")
def migrate_apply(
    config: Path,
    database_url: str | None,
    model_base: str | None,
    models: tuple[str, ...],
    migrations_dir: Path | None,
    compare_type: bool | None,
    revision: str,
) -> None:
    """Apply migrations up to REVISION (defaults to head)."""
    _run_migration_command(
        config,
        database_url,
        model_base,
        models,
        migrations_dir,
        compare_type,
        lambda migrations: migrations.upgrade(revision),
    )


@cli.command("migrate:revert")
@_migration_options
@click.argument("revision", required=False, default="-1")
def migrate_revert(
    config: Path,
    database_url: str | None,
    model_base: str | None,
    models: tuple[str, ...],
    migrations_dir: Path | None,
    compare_type: bool | None,
    revision: str,
) -> None:
    """Revert to REVISION (defaults to one revision before head)."""
    _run_migration_command(
        config,
        database_url,
        model_base,
        models,
        migrations_dir,
        compare_type,
        lambda migrations: migrations.downgrade(revision),
    )


def _create_revision(
    migrations: AlembicMigrations,
    message: str,
    autogenerate: bool,
) -> None:
    revision = migrations.revision(message, autogenerate=autogenerate)
    if revision is None:
        click.echo("No migration was generated.")
    elif isinstance(revision, list):
        click.echo(f"Created {len(revision)} migration revision(s).")
    else:
        click.echo(f"Created migration {revision.revision}.")


def _run_migration_command(
    config: Path,
    database_url: str | None,
    model_base: str | None,
    models: tuple[str, ...],
    migrations_dir: Path | None,
    compare_type: bool | None,
    action,
) -> None:
    migrations = None
    try:
        migrations = _load_migrations(
            _load_project(
                config,
                database_url,
                model_base,
                models,
                migrations_dir,
                compare_type,
            )
        )
        action(migrations)
    except Exception as error:
        raise click.ClickException(str(error)) from error
    finally:
        if migrations is not None:
            migrations.engine.dispose()


@cli.command("sessions:prune")
@_migration_options
def sessions_prune(
    config: Path,
    database_url: str | None,
    model_base: str | None,
    models: tuple[str, ...],
    migrations_dir: Path | None,
    compare_type: bool | None,
) -> None:
    """Delete the expired rows of the session table."""
    engine = None
    try:
        settings = _load_project(
            config,
            database_url,
            model_base,
            models,
            migrations_dir,
            compare_type,
        )
        engine = settings.create_engine()
        session_models = tuple(
            dict.fromkeys(
                mapper.class_
                for base in settings.model_bases
                for mapper in base.registry.mappers
                if getattr(
                    mapper.class_, "__qivo_flask_session_model__", False
                )
            )
        )
        if len(session_models) > 1:
            raise RuntimeError(
                "More than one configured model base registers a Flask session model"
            )
        if not session_models:
            raise RuntimeError(
                "No configured model base declares a Flask session model; "
                "inherit from FlaskSessionModel"
            )
        removed = prune_sessions(session_models[0], engine)
    except click.ClickException:
        raise
    except Exception as error:
        raise click.ClickException(str(error)) from error
    finally:
        if engine is not None:
            engine.dispose()

    click.echo(f"Removed {removed} expired session(s).")


if __name__ == "__main__":
    cli()
