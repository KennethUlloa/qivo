from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from qivo.cli.migrate.base import AlembicMigrations, MigrationConfig
from qivo.sql.mixins import TimestampMixin


class Model(DeclarativeBase):
    pass


class AuditBase(DeclarativeBase):
    pass


class User(TimestampMixin, Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True)


class AuditLog(AuditBase):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str]


def version_files(directory: Path) -> list[Path]:
    return sorted((directory / "versions").glob("*.py"))


def table_names(engine) -> set[str]:
    names = set(inspect(engine).get_table_names())
    names.discard("alembic_version")
    return names


@pytest.fixture
def engine(tmp_path):
    return create_engine(f"sqlite:///{tmp_path / 'app.db'}")


@pytest.fixture
def migrations(engine, tmp_path):
    return AlembicMigrations(
        engine,
        Model.metadata,
        MigrationConfig(directory=tmp_path / "migrations"),
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def test_the_migration_directory_is_created_on_demand(migrations, tmp_path):
    migrations.stamp()

    directory = tmp_path / "migrations"

    assert (directory / "env.py").exists()
    assert (directory / "alembic.ini").exists()
    assert (directory / "script.py.mako").exists()
    assert (directory / "versions").is_dir()


def test_env_uses_the_shared_template(migrations, tmp_path):
    migrations.stamp()

    env = (tmp_path / "migrations" / "env.py").read_text(encoding="utf-8")

    assert 'config.attributes.get("target_metadata")' in env
    assert 'config.attributes.get("engine")' in env


def test_an_existing_environment_is_reused(engine, tmp_path):
    directory = tmp_path / "migrations"
    AlembicMigrations(engine, Model.metadata, MigrationConfig(directory=directory)).stamp()
    env = directory / "env.py"
    env.write_text("# custom\n", encoding="utf-8")

    AlembicMigrations(engine, Model.metadata, MigrationConfig(directory=directory)).stamp()

    assert env.read_text(encoding="utf-8") == "# custom\n"


def test_an_incomplete_environment_is_rejected(engine, tmp_path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "env.py").write_text("", encoding="utf-8")
    migrations = AlembicMigrations(engine, Model.metadata, MigrationConfig(directory=directory))

    with pytest.raises(RuntimeError, match="Incomplete Alembic environment"):
        migrations.stamp()


def test_a_directory_without_env_is_rejected(engine, tmp_path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "readme.txt").write_text("hello", encoding="utf-8")
    migrations = AlembicMigrations(engine, Model.metadata, MigrationConfig(directory=directory))

    with pytest.raises(RuntimeError, match="not empty"):
        migrations.stamp()


def test_the_default_directory_is_migrations():
    config = MigrationConfig()

    assert Path(config.directory) == Path("migrations")
    assert config.compare_type is True
    assert config.render_as_batch is True


def test_the_directory_is_resolved(engine, tmp_path):
    migrations = AlembicMigrations(
        engine,
        Model.metadata,
        MigrationConfig(directory=tmp_path / "migrations"),
    )

    assert migrations.directory.is_absolute()
    assert migrations.directory.name == "migrations"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_config_keeps_the_engine_and_metadata(engine):
    migrations = AlembicMigrations(engine, Model.metadata)

    assert migrations.engine is engine
    assert migrations.metadata is Model.metadata


def test_config_defaults(engine):
    migrations = AlembicMigrations(engine, Model.metadata)

    assert migrations.options == MigrationConfig()


def test_config_sets_the_engine_and_metadata_attributes(engine):
    migrations = AlembicMigrations(engine, Model.metadata)

    config = migrations._config()

    assert config.attributes["engine"] is engine
    assert config.attributes["target_metadata"] is Model.metadata
    assert config.attributes["compare_type"] is True
    assert config.attributes["render_as_batch"] is True


def test_config_accepts_multiple_bases(engine):
    migrations = AlembicMigrations(
        engine,
        [Model.metadata, AuditBase.metadata],
        MigrationConfig(compare_type=False, render_as_batch=False),
    )

    config = migrations._config()

    assert config.attributes["target_metadata"] == [
        Model.metadata,
        AuditBase.metadata,
    ]
    assert config.attributes["compare_type"] is False
    assert config.attributes["render_as_batch"] is False


def test_config_points_to_the_script_location(engine, tmp_path):
    migrations = AlembicMigrations(
        engine,
        Model.metadata,
        MigrationConfig(directory=tmp_path / "migrations"),
    )

    config = migrations._config()

    assert config.get_main_option("script_location") == str(migrations.directory)
    assert config.get_main_option("sqlalchemy.url") == engine.url.render_as_string(
        hide_password=False
    )


# ---------------------------------------------------------------------------
# Revisions
# ---------------------------------------------------------------------------


def test_revision_autogenerates_a_migration(migrations, tmp_path):
    migrations.revision("initial schema")

    versions = version_files(tmp_path / "migrations")
    content = versions[0].read_text(encoding="utf-8")

    assert len(versions) == 1
    assert "initial schema" in content
    assert "op.create_table(" in content
    assert "'users'" in content
    assert "op.drop_table('users')" in content


def test_empty_revision_skips_autogeneration(migrations, tmp_path):
    migrations.revision("blank", autogenerate=False)

    versions = version_files(tmp_path / "migrations")

    assert len(versions) == 1
    assert "create_table" not in versions[0].read_text(encoding="utf-8")


def test_revision_creates_a_chain(migrations, tmp_path):
    migrations.revision("first")
    migrations.revision("second", autogenerate=False)

    assert len(version_files(tmp_path / "migrations")) == 2


def test_upgrade_creates_the_tables(migrations, engine):
    migrations.revision("initial schema")

    migrations.upgrade()

    assert table_names(engine) == {"users"}


def test_upgrade_defaults_to_head(migrations, engine, tmp_path):
    migrations.revision("initial schema")
    migrations.revision("blank", autogenerate=False)

    migrations.upgrade()

    assert table_names(engine) == {"users"}


def test_upgrade_to_a_specific_revision(migrations, engine):
    migrations.revision("initial schema")
    migrations.revision("blank", autogenerate=False)
    migrations.upgrade("base")

    assert table_names(engine) == set()


def test_upgrade_applies_every_base(engine, tmp_path):
    migrations = AlembicMigrations(
        engine,
        [Model.metadata, AuditBase.metadata],
        MigrationConfig(directory=tmp_path / "migrations"),
    )
    migrations.revision("initial schema")

    migrations.upgrade()

    assert table_names(engine) == {"users", "audit_logs"}


def test_downgrade_reverts_everything(migrations, engine):
    migrations.revision("initial schema")
    migrations.upgrade()

    migrations.downgrade("base")

    assert table_names(engine) == set()


def test_downgrade_reverts_one_step_by_default(migrations, engine):
    migrations.revision("initial schema")
    migrations.revision("blank", autogenerate=False)
    migrations.upgrade()

    migrations.downgrade()

    assert table_names(engine) == {"users"}


def test_downgrade_without_history_is_a_noop(migrations, engine):
    migrations.revision("initial schema")

    migrations.downgrade("base")

    assert table_names(engine) == set()


def test_stamp_marks_the_database_without_applying(migrations, engine):
    migrations.revision("initial schema")

    migrations.stamp()

    assert table_names(engine) == set()


def test_stamp_base_then_upgrade(migrations, engine):
    migrations.revision("initial schema")
    migrations.stamp("base")

    migrations.upgrade()

    assert table_names(engine) == {"users"}


def test_migrated_schema_is_writable(migrations, engine):
    migrations.revision("initial schema")
    migrations.upgrade()

    with Session(engine) as session:
        session.add(User(username="ada"))
        session.commit()

        assert session.query(User).one().username == "ada"