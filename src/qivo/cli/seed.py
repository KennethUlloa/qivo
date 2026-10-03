import sys
import click
from pathlib import Path

from typing import Protocol, Type
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from qivo.settings import SQLAlchemy, Seed
from qivo.utils import import_symbol


class Seeder(Protocol):
    def run(): ...


@click.command("seed")
@click.argument("seeder", required=True)
def run_seeder(seeder: str):
    config_path = Path("qivo.toml").resolve()
    project_root = str(config_path.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    config = Seed.from_toml(str(config_path))
    sqlalchemy = SQLAlchemy.from_toml(str(config_path))
    seeders: dict[str, Type[Seeder]] = import_symbol(config.registry_path)

    engine = create_engine(sqlalchemy.url, **sqlalchemy.engine_options)
    session_factory = sessionmaker(engine)

    if seeder in seeders:
        try:
            session = session_factory()
            seeders[seeder](session).run()
        finally:
            session.close()

    else:
        raise ValueError(f"Unknown seeder: {seeder}")
