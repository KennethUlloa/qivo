import json
import sys

import pytest

from qivo.settings import (
    Application,
    Migrations,
    Seed,
    Settings,
    SQLAlchemy,
    load_toml_file,
)
from qivo.utils import ViewDecorator, import_symbol

TOML_CONTENT = """
[application]
name = "Tasks"
host = "localhost"
port = 8000
import_path = "app.main:app"

[sqlalchemy]
url = "sqlite:///app.db"
engine_options = {}

[migrations]
directory = "migrations"
compare_type = true
render_as_batch = true
model_bases = ["app.models:Model"]

[seed]
registry_path = "seeders:seeders"
"""

JSON_CONTENT = {
    "application": {
        "name": "Tasks",
        "host": "0.0.0.0",
        "port": 5000,
        "import_path": "app.main:app",
    },
    "sqlalchemy": {"url": "sqlite:///app.db", "engine_options": {}},
    "migrations": {
        "directory": "migrations",
        "compare_type": True,
        "render_as_batch": True,
        "model_bases": ["app.models:Model"],
    },
    "seed": {"registry_path": "seeders:seeders"},
}


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "qivo.toml"
    path.write_text(TOML_CONTENT, encoding="utf-8")
    return str(path)


@pytest.fixture
def models_module(importable_module):
    return importable_module("class Model:\n    pass\n\n\nclass Other:\n    pass\n")


# ---------------------------------------------------------------------------
# load_toml_file
# ---------------------------------------------------------------------------


def test_load_toml_file_parses_the_config(config_file):
    config = load_toml_file(config_file)

    assert config["application"]["name"] == "Tasks"


def test_load_toml_file_is_cached(config_file):
    assert load_toml_file(config_file) is load_toml_file(config_file)


def test_load_toml_file_adds_the_project_root_to_sys_path(config_file, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))

    load_toml_file(config_file)

    assert str(tmp_path.resolve()) in sys.path


def test_load_toml_file_with_a_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_toml_file(str(tmp_path / "missing.toml"))


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def test_application_from_toml(config_file):
    application = Application.from_toml(config_file)

    assert application.name == "Tasks"
    assert application.import_path == "app.main:app"
    assert application.host == "localhost"
    assert application.port == 8000


def test_application_defaults():
    application = Application(name="Tasks", import_path="app.main:app")

    assert application.host == "0.0.0.0"
    assert application.port == 5000


def test_sqlalchemy_from_toml(config_file):
    sqlalchemy = SQLAlchemy.from_toml(config_file)

    assert sqlalchemy.url == "sqlite:///app.db"
    assert sqlalchemy.engine_options == {}


def test_migrations_from_toml(config_file):
    migrations = Migrations.from_toml(config_file)

    assert migrations.directory == "migrations"
    assert migrations.compare_type is True
    assert migrations.render_as_batch is True
    assert migrations.model_bases == ["app.models:Model"]


def test_seed_from_toml(config_file):
    assert Seed.from_toml(config_file).registry_path == "seeders:seeders"


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_settings_from_toml(config_file):
    settings = Settings.from_toml(config_file)

    assert settings.application.name == "Tasks"
    assert settings.sqlalchemy.url == "sqlite:///app.db"
    assert settings.migrations.model_bases == ["app.models:Model"]
    assert settings.seed.registry_path == "seeders:seeders"


def test_settings_from_json(tmp_path):
    path = tmp_path / "qivo.json"
    path.write_text(json.dumps(JSON_CONTENT), encoding="utf-8")

    settings = Settings.from_json(str(path))

    assert settings.application.port == 5000
    assert settings.sqlalchemy.url == "sqlite:///app.db"


def test_settings_from_dict():
    settings = Settings.from_dict(JSON_CONTENT)

    assert settings.application.host == "0.0.0.0"
    assert settings.migrations.compare_type is True


def test_settings_from_dict_with_a_missing_section():
    with pytest.raises(KeyError):
        Settings.from_dict({"application": JSON_CONTENT["application"]})


# ---------------------------------------------------------------------------
# import_symbol
# ---------------------------------------------------------------------------


def test_import_symbol_resolves_a_class(models_module):
    assert import_symbol(f"{models_module}:Model").__name__ == "Model"


def test_import_symbol_resolves_a_nested_attribute(importable_module):
    name = importable_module("value = 42\n")

    assert import_symbol(f"{name}:value") == 42


def test_import_symbol_without_a_module_path():
    with pytest.raises(ValueError, match="Invalid import path"):
        import_symbol("Model")


def test_import_symbol_with_an_unknown_attribute(models_module):
    with pytest.raises(AttributeError):
        import_symbol(f"{models_module}:Unknown")


def test_import_symbol_with_an_unknown_module():
    with pytest.raises(ModuleNotFoundError):
        import_symbol("does_not_exist:Model")


# ---------------------------------------------------------------------------
# ViewDecorator
# ---------------------------------------------------------------------------


def test_view_decorator_calls_the_function():
    class Custom(ViewDecorator):
        def handle_function(self, function, *args, **kwargs):
            return function(*args, **kwargs) + 1

    @Custom()
    def handler(value):
        return value

    assert handler(1) == 2


def test_view_decorator_can_transform_the_response():
    class Custom(ViewDecorator):
        def handle_response(self, response):
            return {"response": response}

    @Custom()
    def handler():
        return "value"

    assert handler() == {"response": "value"}


def test_view_decorator_passes_the_response_through():
    @ViewDecorator()
    def handler():
        return "value"

    assert handler() == "value"


def test_view_decorator_passes_arguments_through():
    class Custom(ViewDecorator):
        def handle_function(self, function, *args, **kwargs):
            return function(*args, **kwargs)

    @Custom()
    def handler(first, second=None):
        return first, second

    assert handler(1, second=2) == (1, 2)


def test_view_decorator_preserves_the_function_metadata():
    @ViewDecorator()
    def handler():
        """Docstring."""

    assert handler.__name__ == "handler"
    assert handler.__doc__ == "Docstring."