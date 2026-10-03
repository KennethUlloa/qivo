import sys
from uuid import uuid4

import pytest
from flask import Flask

from qivo.ext.sql import _session_context
from qivo.settings import load_toml_file


@pytest.fixture(autouse=True)
def workdir(tmp_path, monkeypatch):
    """Run every test from an empty temporary working directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def reset_session_context():
    """Keep the SQL session ContextVar isolated between tests."""
    _session_context.set(None)
    yield
    _session_context.set(None)


@pytest.fixture(autouse=True)
def clear_toml_cache():
    """Settings files are cached by path, isolate that cache per test."""
    load_toml_file.cache_clear()
    yield
    load_toml_file.cache_clear()


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def importable_module(tmp_path, monkeypatch):
    """Write importable modules into a temporary directory."""
    monkeypatch.syspath_prepend(str(tmp_path))
    created = []

    def create(content, prefix="module"):
        name = f"{prefix}_{uuid4().hex}"
        (tmp_path / f"{name}.py").write_text(content, encoding="utf-8")
        created.append(name)
        return name

    yield create

    for name in created:
        sys.modules.pop(name, None)