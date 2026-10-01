from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.script import Script
from sqlalchemy import Engine, MetaData

_ENV_TEMPLATE = """from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
target_metadata = config.attributes.get("target_metadata")
compare_type = config.attributes.get("compare_type", True)
render_as_batch = config.attributes.get("render_as_batch", True)


def run_migrations_offline():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=compare_type,
        render_as_batch=render_as_batch,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = config.attributes.get("engine")
    owns_engine = connectable is None
    if owns_engine:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=compare_type,
                render_as_batch=render_as_batch,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        if owns_engine:
            connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
"""


@dataclass(frozen=True)
class MigrationConfig:
    directory: str | Path = Path("migrations")
    compare_type: bool = True
    render_as_batch: bool = True


class AlembicMigrations:
    def __init__(
        self,
        engine: Engine,
        metadata: MetaData | Sequence[MetaData] | None = None,
        config: MigrationConfig | None = None,
    ):
        if metadata is None:
            from qivo.db.sql import Model

            metadata = Model.metadata

        self.engine = engine
        self.metadata = metadata
        self.options = config or MigrationConfig()
        self.directory = Path(self.options.directory).resolve()

    def revision(
        self,
        message: str,
        *,
        autogenerate: bool = True,
    ) -> Script | None | list[Script | None]:
        return command.revision(
            self._config(),
            message=message,
            autogenerate=autogenerate,
        )

    def upgrade(self, revision: str = "head") -> None:
        command.upgrade(self._config(), revision)

    def downgrade(self, revision: str = "-1") -> None:
        command.downgrade(self._config(), revision)

    def stamp(self, revision: str = "head") -> None:
        command.stamp(self._config(), revision)

    def _config(self) -> Config:
        self._ensure_initialized()
        config = Config(str(self.directory / "alembic.ini"))
        config.set_main_option("script_location", str(self.directory))
        url = self.engine.url.render_as_string(hide_password=False).replace("%", "%%")
        config.set_main_option("sqlalchemy.url", url)
        config.attributes.update(
            engine=self.engine,
            target_metadata=self.metadata,
            compare_type=self.options.compare_type,
            render_as_batch=self.options.render_as_batch,
        )
        return config

    def _ensure_initialized(self) -> None:
        env_file = self.directory / "env.py"
        if env_file.exists():
            required_files = (
                self.directory / "alembic.ini",
                self.directory / "script.py.mako",
                self.directory / "versions",
            )
            if not all(path.exists() for path in required_files):
                raise RuntimeError(
                    f"Incomplete Alembic environment in {self.directory}"
                )
            return

        if self.directory.exists() and any(self.directory.iterdir()):
            raise RuntimeError(
                f"Migration directory {self.directory} is not empty and has no env.py"
            )

        config = Config(str(self.directory / "alembic.ini"))
        config.set_main_option("script_location", str(self.directory))
        command.init(config, str(self.directory), template="generic")
        env_file.write_text(_ENV_TEMPLATE, encoding="utf-8")
