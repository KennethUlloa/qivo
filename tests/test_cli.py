from contextlib import contextmanager

import pytest
from click.testing import CliRunner
from flask import Flask
from sqlalchemy import create_engine, inspect, text

from qivo.cli import cli

TOML_TEMPLATE = """
[application]
name = "Tasks"
host = "localhost"
port = 8000
import_path = "{import_path}"

[sqlalchemy]
url = "sqlite:///{database}"
engine_options = {{}}

[migrations]
directory = "migrations"
compare_type = true
render_as_batch = true
model_bases = ["{models}"]

[seed]
registry_path = "{seeders}"
"""

APP_MODULE = """
from flask import Flask

app = Flask(__name__)

not_an_app = 42


def create_app():
    return Flask(__name__)
"""

MODELS_MODULE = """
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Model(DeclarativeBase):
    pass


class User(Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True)
    password: Mapped[str]
"""

SEEDERS_MODULE = """
from qivo.sql.seed import BaseSeeder

from {models} import User


class UserSeeder(BaseSeeder):
    name = "users"

    def run(self):
        self.first_or_create(
            User(username="admin", password="hash"),
            User.username == "admin",
        )
        self.session.commit()


class UncommittedSeeder(BaseSeeder):
    name = "uncommitted"

    def run(self):
        self.first_or_create(
            User(username="ghost", password="hash"),
            User.username == "ghost",
        )


seeders = {{"users": UserSeeder, "uncommitted": UncommittedSeeder}}
"""


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def project(workdir, importable_module):
    """A working project with qivo.toml and importable modules."""
    models_module = importable_module(MODELS_MODULE, prefix="project_models")
    seeders_module = importable_module(
        SEEDERS_MODULE.format(models=models_module),
        prefix="project_seeders",
    )
    app_module = importable_module(APP_MODULE, prefix="project_app")

    write_config(
        workdir,
        import_path=f"{app_module}:app",
        models=f"{models_module}:Model",
        seeders=f"{seeders_module}:seeders",
    )

    return workdir


def write_config(
    directory,
    *,
    import_path,
    models,
    seeders,
    database="app.db",
):
    config = TOML_TEMPLATE.format(
        import_path=import_path,
        models=models,
        seeders=seeders,
        database=database,
    )
    (directory / "qivo.toml").write_text(config, encoding="utf-8")


@contextmanager
def connect(directory):
    engine = create_engine(f"sqlite:///{directory / 'app.db'}")

    try:
        yield engine.connect()
    finally:
        engine.dispose()


def table_names(directory):
    engine = create_engine(f"sqlite:///{directory / 'app.db'}")

    try:
        return set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def usernames(directory):
    with connect(directory) as connection:
        return connection.execute(text("SELECT username FROM users")).scalars().all()


@pytest.fixture
def migrated(runner, project):
    """A project with the schema already applied."""
    result = runner.invoke(cli, ["migrate", "-m", "initial schema"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(cli, ["migrate:apply"])
    assert result.exit_code == 0, result.output

    return project


# ---------------------------------------------------------------------------
# Group
# ---------------------------------------------------------------------------


def test_the_cli_exposes_every_command(runner):
    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "run" in result.output
    assert "seed" in result.output
    assert "migrate" in result.output
    assert "migrate:apply" in result.output
    assert "migrate:revert" in result.output


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def test_run_uses_the_configured_host_and_port(runner, project, monkeypatch):
    calls = []
    monkeypatch.setattr(Flask, "run", lambda self, **kwargs: calls.append(kwargs))

    result = runner.invoke(cli, ["run"])

    assert result.exit_code == 0, result.output
    assert calls == [{"host": "localhost", "port": 8000, "debug": False}]


def test_run_options_override_the_configuration(runner, project, monkeypatch):
    calls = []
    monkeypatch.setattr(Flask, "run", lambda self, **kwargs: calls.append(kwargs))

    result = runner.invoke(cli, ["run", "--host", "0.0.0.0", "--port", "9999", "--debug"])

    assert result.exit_code == 0, result.output
    assert calls == [{"host": "0.0.0.0", "port": "9999", "debug": True}]


def test_run_accepts_an_application_factory(runner, workdir, importable_module, monkeypatch):
    app_module = importable_module(APP_MODULE, prefix="factory_app")
    write_config(
        workdir,
        import_path=f"{app_module}:create_app",
        models="project_models:Model",
        seeders="project_seeders:seeders",
    )
    calls = []
    monkeypatch.setattr(Flask, "run", lambda self, **kwargs: calls.append(kwargs))

    result = runner.invoke(cli, ["run"])

    assert result.exit_code == 0, result.output
    assert calls == [{"host": "localhost", "port": 8000, "debug": False}]


def test_run_with_an_invalid_import_path(runner, workdir, importable_module):
    app_module = importable_module(APP_MODULE, prefix="invalid_app")
    write_config(
        workdir,
        import_path=f"{app_module}:not_an_app",
        models="project_models:Model",
        seeders="project_seeders:seeders",
    )

    result = runner.invoke(cli, ["run"])

    assert result.exit_code != 0
    assert isinstance(result.exception, RuntimeError)
    assert "Expected a Flask app" in str(result.exception)


def test_run_with_an_unknown_import_path(runner, workdir, importable_module):
    app_module = importable_module(APP_MODULE, prefix="unknown_app")
    write_config(
        workdir,
        import_path=f"{app_module}:missing",
        models="project_models:Model",
        seeders="project_seeders:seeders",
    )

    result = runner.invoke(cli, ["run"])

    assert result.exit_code != 0
    assert isinstance(result.exception, AttributeError)


def test_run_without_a_configuration(runner, workdir):
    result = runner.invoke(cli, ["run"])

    assert result.exit_code != 0
    assert isinstance(result.exception, FileNotFoundError)


# ---------------------------------------------------------------------------
# seed
# ---------------------------------------------------------------------------


def test_seed_runs_the_seeder(runner, migrated):
    result = runner.invoke(cli, ["seed", "users"])

    assert result.exit_code == 0, result.output
    assert usernames(migrated) == ["admin"]


def test_seed_is_idempotent(runner, migrated):
    runner.invoke(cli, ["seed", "users"])
    result = runner.invoke(cli, ["seed", "users"])

    assert result.exit_code == 0, result.output
    assert usernames(migrated) == ["admin"]


def test_seed_does_not_commit_for_the_seeder(runner, migrated):
    result = runner.invoke(cli, ["seed", "uncommitted"])

    assert result.exit_code == 0, result.output
    assert usernames(migrated) == []


def test_seed_with_an_unknown_seeder(runner, migrated):
    result = runner.invoke(cli, ["seed", "missing"])

    assert result.exit_code != 0
    assert isinstance(result.exception, ValueError)
    assert "Unknown seeder" in str(result.exception)


def test_seed_without_a_configuration(runner, workdir):
    result = runner.invoke(cli, ["seed", "users"])

    assert result.exit_code != 0
    assert isinstance(result.exception, FileNotFoundError)


# ---------------------------------------------------------------------------
# migrate
# ---------------------------------------------------------------------------


def test_migrate_autogenerates_a_revision(runner, project):
    result = runner.invoke(cli, ["migrate", "-m", "initial schema"])

    assert result.exit_code == 0, result.output
    assert len(list((project / "migrations" / "versions").glob("*.py"))) == 1


def test_migrate_default_message(runner, project):
    result = runner.invoke(cli, ["migrate"])

    assert result.exit_code == 0, result.output
    assert len(list((project / "migrations" / "versions").glob("*.py"))) == 1


def test_migrate_empty_creates_a_blank_revision(runner, project):
    result = runner.invoke(cli, ["migrate", "--empty", "-m", "blank"])

    assert result.exit_code == 0, result.output

    versions = list((project / "migrations" / "versions").glob("*.py"))

    assert len(versions) == 1
    assert "create_table" not in versions[0].read_text(encoding="utf-8")


def test_migrate_apply_creates_the_tables(runner, project):
    runner.invoke(cli, ["migrate", "-m", "initial schema"])

    result = runner.invoke(cli, ["migrate:apply"])

    assert result.exit_code == 0, result.output
    assert table_names(project) == {"users"}


def test_migrate_apply_is_idempotent(runner, migrated):
    result = runner.invoke(cli, ["migrate:apply"])

    assert result.exit_code == 0, result.output
    assert table_names(migrated) == {"users"}


def test_migrate_revert_defaults_to_one_step(runner, migrated):
    result = runner.invoke(cli, ["migrate:revert"])

    assert result.exit_code == 0, result.output
    assert table_names(migrated) == set()


def test_migrate_revert_accepts_a_revision(runner, migrated):
    result = runner.invoke(cli, ["migrate:revert", "base"])

    assert result.exit_code == 0, result.output
    assert table_names(migrated) == set()


def test_migrate_revert_without_history(runner, project):
    runner.invoke(cli, ["migrate", "-m", "initial schema"])

    result = runner.invoke(cli, ["migrate:revert"])

    assert result.exit_code != 0
    assert "Relative revision -1 didn't produce 1 migrations" in str(result.exception)


def test_migrate_round_trip(runner, project):
    runner.invoke(cli, ["migrate", "-m", "initial schema"])
    runner.invoke(cli, ["migrate:apply"])
    runner.invoke(cli, ["migrate:revert", "base"])

    result = runner.invoke(cli, ["migrate:apply"])

    assert result.exit_code == 0, result.output
    assert table_names(project) == {"users"}


def test_migrate_without_a_configuration(runner, workdir):
    result = runner.invoke(cli, ["migrate"])

    assert result.exit_code != 0
    assert isinstance(result.exception, FileNotFoundError)


def test_migrate_with_an_unknown_model_base(runner, workdir):
    write_config(
        workdir,
        import_path="project_app:app",
        models="missing_module:Model",
        seeders="project_seeders:seeders",
    )

    result = runner.invoke(cli, ["migrate"])

    assert result.exit_code != 0
    assert isinstance(result.exception, ModuleNotFoundError)