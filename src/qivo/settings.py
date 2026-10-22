"""Configuration module"""

import tomllib
import sys
import os
from string import Template
from functools import cache
from pathlib import Path
from dataclasses import dataclass, field, fields
from typing import Type


@cache
def load_toml_file(path: str):
    """Loads the toml file provided and replaces `${VARIABLE}` with values from the env
    that starts with 'QIVO'."""
    config_path = Path(path).resolve()
    project_root = str(config_path.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
        content = Template(content).safe_substitute(
            {key: value for key, value in os.environ.items() if key.startswith("QIVO")}
        )
        return tomllib.loads(content)


def _get_field_default(field_type: str | Type) -> str:
    repr_ = str(field_type)

    if repr_.startswith("list") or repr_.startswith("tuple"):
        return "[]"
    if repr_.startswith("dict"):
        return "{}"

    if field_type not in (str, int, bool, dict, tuple, list, set, bytes):
        return None

    if issubclass(field_type, bool):
        return "true"

    if issubclass(field_type, (int, float)):
        return "0" if issubclass(field_type, int) else "0.0"

    if issubclass(field_type, (tuple, list, set)):
        return "[]"
    if issubclass(field_type, dict):
        return "{}"

    return '""'


class BaseSetting:
    """Skeleton for configuration classes"""

    __toml_section__: str = None

    @classmethod
    def get_part(cls, data: dict):
        """Allows to retrieve a part of the whole configuration loaded"""
        return data

    @classmethod
    def from_toml(cls, file: str):
        """Loads the configuration data from a toml file"""
        config = load_toml_file(file)
        return cls.from_dict(cls.get_part(config))

    @classmethod
    def from_dict(cls, data: dict):
        """Loads the data from a dictionary, allows to apply custom logic to create instance depending on context"""
        return cls(**data)

    @classmethod
    def toml_template(cls):
        """Get the structure used to load the data"""
        template = f"[{cls.__toml_section__ or cls.__name__.lower()}]\n"

        for key, value in cls.get_template_map().items():
            if value is None:
                template += f"# Couldn't transform {key} type to a toml value\n"
            else:
                template += f"{key} = {value}\n"

        return template + "\n"

    @classmethod
    def get_template_map(cls):
        """Field = value mapping"""
        return {f.name: _get_field_default(f.type) for f in fields(cls)}


@dataclass
class Application(BaseSetting):
    """Application information"""

    name: str
    import_path: str
    port: int = 5000
    host: str = "0.0.0.0"
    extra_files: list[str] = field(default_factory=list)

    @classmethod
    def get_part(cls, data: dict):
        return data["application"]


@dataclass
class SQLAlchemy(BaseSetting):
    """Engine configuration"""

    url: str
    engine_options: dict

    @classmethod
    def get_part(cls, data: dict):
        return data["sqlalchemy"]


@dataclass
class Migrations(BaseSetting):
    """Alembic setup to apply migrations"""

    directory: str
    compare_type: bool
    render_as_batch: bool
    model_bases: list[str]

    @classmethod
    def get_part(cls, data: dict):
        return data["migrations"]


@dataclass
class Seed(BaseSetting):
    """Seeding configuration"""

    registry_path: str

    @classmethod
    def get_part(cls, data: dict):
        return data["seed"]


@dataclass
class Settings(BaseSetting):
    """Global configuration"""

    application: Application
    sqlalchemy: SQLAlchemy
    migrations: Migrations
    seed: Seed

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            application=Application.from_dict(data["application"]),
            sqlalchemy=SQLAlchemy.from_dict(data["sqlalchemy"]),
            migrations=Migrations.from_dict(data["migrations"]),
            seed=Seed.from_dict(data["seed"]),
        )


BASE_TOML = "".join(
    map(lambda c: c.toml_template(), [Application, SQLAlchemy, Migrations, Seed])
)
