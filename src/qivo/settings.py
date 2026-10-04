import json
import tomllib
import sys
from functools import cache
from pathlib import Path
from dataclasses import dataclass, field


@cache
def load_toml_file(path: str):
    config_path = Path(path).resolve()
    project_root = str(config_path.parent)
    if project_root not in sys.path:
            sys.path.insert(0, project_root)

    with open(path, "rb") as f:
        return tomllib.load(f)


@dataclass
class Application:
    name: str
    import_path: str
    port: int = 5000
    host: str = "0.0.0.0"
    extra_files: list[str] = field(default_factory=list)

    @classmethod
    def from_toml(cls, path: str):
        config = load_toml_file(path)
        return cls(**config["application"])


@dataclass
class SQLAlchemy:
    url: str
    engine_options: dict

    @classmethod
    def from_toml(cls, path: str):
        config = load_toml_file(path)
        return cls(**config["sqlalchemy"])


@dataclass
class Migrations:
    directory: str
    compare_type: bool
    render_as_batch: bool
    model_bases: list[str]

    @classmethod
    def from_toml(cls, path: str):
        config = load_toml_file(path)
        return cls(**config["migrations"])


@dataclass
class Seed:
    registry_path: str

    @classmethod
    def from_toml(cls, path: str):
        config = load_toml_file(path)
        return cls(**config["seed"])


@dataclass
class Settings:
    application: Application
    sqlalchemy: SQLAlchemy
    migrations: Migrations
    seed: Seed

    @classmethod
    def from_toml(cls, path: str):
        with open(path, "rb") as f:
            config = tomllib.load(f)
            return cls.from_dict(config)

    @classmethod
    def from_json(cls, path: str):
        with open(path, "r") as f:
            config = json.load(f)
            return cls.from_dict(config)

    @classmethod
    def from_dict(cls, config: dict):
        return cls(
            application=Application(**config["application"]),
            sqlalchemy=SQLAlchemy(**config["sqlalchemy"]),
            migrations=Migrations(**config["migrations"]),
            seed=Seed(**config["seed"]),
        )
