import re
import textwrap
from datetime import datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine

from qivo.cli import cli
from qivo.db.sql import FlaskSessionModel

BASE_CONFIG = """
[application]
name = "Sesiones"

[sqlalchemy]
url = "sqlite:///{url}"
model_bases = ["{package}.models:Base"]

[migrations]
directory = "migrations"
"""

MODELS = """
from sqlalchemy.orm import Mapped, mapped_column

from qivo.db.sql import model_base

Base = model_base("Base")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
"""


def models_of(config: Path) -> str:
    return f"{package_of(config.parent)}.models"


def package_of(root: Path) -> str:
    """Give every test project a unique import path and isolated model metadata."""

    return "tienda_" + re.sub(r"\W", "_", root.name)


def build_project(root: Path, *, register_session: bool) -> Path:
    """Write a throwaway project with a qivo.toml and its models."""

    package = package_of(root)
    directory = root / package
    directory.mkdir()
    (directory / "__init__.py").write_text("", encoding="utf-8")
    models_source = textwrap.dedent(MODELS)
    if register_session:
        models_source += textwrap.dedent(
            """

            from qivo.db.sql import FlaskSessionModel


            class FlaskSessionRow(Base, FlaskSessionModel):
                __tablename__ = "qivo_sessions"
            """
        )
    (directory / "models.py").write_text(models_source, encoding="utf-8")
    config = root / "qivo.toml"
    config.write_text(
        BASE_CONFIG.format(url=(root / "app.db").as_posix(), package=package),
        encoding="utf-8",
    )

    return config


def migrate_arguments(config: Path) -> list[str]:
    return [
        "migrate",
        "--config",
        str(config),
        "--migrations-dir",
        str(config.parent / "migrations"),
        "--message",
        "initial",
    ]


def latest_revision(root: Path) -> str:
    scripts = sorted((root / "migrations" / "versions").glob("*.py"))
    assert scripts, "no revision was generated"
    return scripts[-1].read_text(encoding="utf-8")


def remove_database(root: Path) -> None:
    """Leave no database behind, so autogenerate reports every table."""

    engine = create_engine(f"sqlite:///{root / 'app.db'}")
    engine.dispose()
    (root / "app.db").unlink(missing_ok=True)


@pytest.fixture
def project(tmp_path: Path, monkeypatch):
    config = build_project(tmp_path, register_session=True)
    monkeypatch.syspath_prepend(str(tmp_path))

    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    base = import_module(models_of(config)).Base

    base.metadata.create_all(engine)
    try:
        yield config, engine, base
    finally:
        base.metadata.drop_all(engine)
        engine.dispose()


def expired_row(engine, base, sid, *, minutes_ago):
    model = flask_session_row(base)
    with engine.begin() as connection:
        connection.execute(
            model.__table__.insert(),
            {
                "sid": sid,
                "data": {"value": "hola"},
                "expires_at": datetime.now(timezone.utc)
                - timedelta(minutes=minutes_ago),
            },
        )


def count_rows(engine, base):
    model = flask_session_row(base)
    with engine.connect() as connection:
        return len(connection.execute(model.__table__.select()).all())


def flask_session_row(base):
    models = [
        mapper.class_
        for mapper in base.registry.mappers
        if getattr(mapper.class_, "__qivo_flask_session_model__", False)
    ]
    assert len(models) == 1
    return models[0]


def test_sessions_prune_removes_the_expired_rows(project):
    config, engine, base = project
    expired_row(engine, base, "vencida", minutes_ago=5)

    result = CliRunner().invoke(
        cli,
        ["sessions:prune", "--config", str(config)],
    )

    assert result.exit_code == 0, result.output
    assert "Removed 1 expired session(s)." in result.output
    assert count_rows(engine, base) == 0


def test_sessions_prune_keeps_the_live_rows(project):
    config, engine, base = project
    expired_row(engine, base, "vencida", minutes_ago=5)
    model = flask_session_row(base)
    with engine.begin() as connection:
        connection.execute(
            model.__table__.insert(),
            {
                "sid": "viva",
                "data": {},
                "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
            },
        )

    result = CliRunner().invoke(
        cli,
        ["sessions:prune", "--config", str(config)],
    )

    assert result.exit_code == 0, result.output
    assert count_rows(engine, base) == 1


def test_sessions_prune_finds_the_flask_session_model_on_a_secondary_base(
    tmp_path, monkeypatch
):
    config = build_project(tmp_path, register_session=False)
    package = package_of(tmp_path)
    audit_package = tmp_path / package / "audit"
    audit_package.mkdir()
    (audit_package / "__init__.py").write_text("", encoding="utf-8")
    (audit_package / "models.py").write_text(
        textwrap.dedent(
            """
            from qivo.db.sql import FlaskSessionModel, model_base

            Base = model_base("SessionBase")


            class FlaskSessionRow(Base, FlaskSessionModel):
                __tablename__ = "qivo_sessions"
            """
        ),
        encoding="utf-8",
    )
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            f'model_bases = ["{package}.models:Base"]',
            "model_bases = "
            f'["{package}.models:Base", "{package}.audit.models:Base"]',
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    base = import_module(f"{package}.audit.models").Base
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    base.metadata.create_all(engine)
    expired_row(engine, base, "vencida", minutes_ago=5)

    result = CliRunner().invoke(cli, ["sessions:prune", "--config", str(config)])

    assert result.exit_code == 0, result.output
    assert count_rows(engine, base) == 0
    base.metadata.drop_all(engine)
    engine.dispose()


def test_sessions_prune_reports_a_broken_config(tmp_path):
    config = tmp_path / "qivo.toml"
    config.write_text(
        '[sqlalchemy]\nmodels = []\nmodel_base = "sin_dos_puntos"\n', "utf-8"
    )

    result = CliRunner().invoke(cli, ["sessions:prune", "--config", str(config)])

    assert result.exit_code != 0
    assert "model_base must use 'module:attribute' syntax" in result.output


def test_sessions_prune_requires_an_explicit_flask_session_class(tmp_path):
    config = build_project(tmp_path, register_session=False)

    result = CliRunner().invoke(cli, ["sessions:prune", "--config", str(config)])

    assert result.exit_code != 0
    assert "inherit from FlaskSessionModel" in result.output


def test_migrate_leaves_the_session_table_out_by_default(tmp_path):
    config = build_project(tmp_path, register_session=False)
    remove_database(tmp_path)

    result = CliRunner().invoke(cli, migrate_arguments(config))

    assert result.exit_code == 0, result.output
    assert "tasks" in latest_revision(tmp_path)
    assert "qivo_sessions" not in latest_revision(tmp_path)


def test_migrate_creates_the_registered_flask_session_table(tmp_path):
    config = build_project(tmp_path, register_session=True)
    remove_database(tmp_path)

    result = CliRunner().invoke(cli, migrate_arguments(config))

    assert result.exit_code == 0, result.output
    assert "create_table" in latest_revision(tmp_path)
    assert "qivo_sessions" in latest_revision(tmp_path)


def test_migrate_autogenerates_from_multiple_model_bases(tmp_path):
    config = build_project(tmp_path, register_session=False)
    package = package_of(tmp_path)
    audit_package = tmp_path / package / "audit"
    audit_package.mkdir()
    (audit_package / "__init__.py").write_text("", encoding="utf-8")
    (audit_package / "models.py").write_text(
        textwrap.dedent(
            """
            from sqlalchemy.orm import Mapped, mapped_column

            from qivo.db.sql import model_base

            Base = model_base("AuditBase")


            class AuditLog(Base):
                __tablename__ = "audit_logs"

                id: Mapped[int] = mapped_column(primary_key=True)
            """
        ),
        encoding="utf-8",
    )
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            f'model_bases = ["{package}.models:Base"]',
            "model_bases = "
            f'["{package}.models:Base", "{package}.audit.models:Base"]',
        ),
        encoding="utf-8",
    )
    remove_database(tmp_path)

    result = CliRunner().invoke(
        cli,
        [
            "migrate",
            "--config",
            str(config),
            "--migrations-dir",
            str(tmp_path / "migrations"),
            "--message",
            "initial",
        ],
    )

    assert result.exit_code == 0, result.output
    revision = latest_revision(tmp_path)
    assert "tasks" in revision
    assert "audit_logs" in revision