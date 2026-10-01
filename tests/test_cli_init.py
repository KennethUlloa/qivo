from importlib import import_module

from click.testing import CliRunner

from qivo.cli import cli
from qivo.db.sql import Model


def test_init_with_authentication_creates_auth_scaffold(tmp_path):
    result = CliRunner().invoke(
        cli,
        [
            "init",
            "--path",
            str(tmp_path),
            "--package",
            "demo",
            "--name",
            "Demo",
            "--auth",
        ],
    )

    assert result.exit_code == 0, result.output
    config = (tmp_path / "qivo.toml").read_text(encoding="utf-8")
    app = (tmp_path / "demo" / "app.py").read_text(encoding="utf-8")
    assert 'model_bases = ["qivo.db.sql:Model", "qivo.db.sql.auth:AuthBase"]' in config
    assert "DBSessionAuthenticator" in app
    assert "@qivo.view(auth=True)" in app
    assert "def login()" in app
    assert "def register()" in app
    assert (tmp_path / "demo" / "template" / "login.html").exists()
    assert (tmp_path / "demo" / "template" / "register.html").exists()


def test_init_prompts_for_authentication(tmp_path):
    result = CliRunner().invoke(
        cli,
        [
            "init",
            "--path",
            str(tmp_path),
            "--package",
            "demo",
            "--name",
            "Demo",
        ],
        input="y\n",
    )

    assert result.exit_code == 0, result.output
    assert "Would you like to enable authentication?" in result.output
    assert (tmp_path / "demo" / "template" / "login.html").exists()


def test_init_without_authentication_keeps_the_basic_scaffold(tmp_path):
    result = CliRunner().invoke(
        cli,
        [
            "init",
            "--path",
            str(tmp_path),
            "--package",
            "demo",
            "--name",
            "Demo",
            "--no-auth",
        ],
    )

    assert result.exit_code == 0, result.output
    app = (tmp_path / "demo" / "app.py").read_text(encoding="utf-8")
    assert "DBSessionAuthenticator" not in app
    assert not (tmp_path / "demo" / "template" / "login.html").exists()


def test_generated_auth_app_supports_registration_login_and_protected_tasks(
    tmp_path, monkeypatch
):
    result = CliRunner().invoke(
        cli,
        [
            "init",
            "--path",
            str(tmp_path),
            "--package",
            "demo",
            "--name",
            "Demo",
            "--auth",
        ],
    )
    assert result.exit_code == 0, result.output
    monkeypatch.syspath_prepend(str(tmp_path))
    generated = import_module("demo.app")
    Model.metadata.create_all(generated.db.engine)
    generated.AuthBase.metadata.create_all(generated.db.engine)
    generated.app.testing = True

    try:
        with generated.app.test_client() as client:
            assert client.get("/login").status_code == 200
            assert client.get("/register").status_code == 200
            assert client.get("/tasks").status_code == 401

            registered = client.post(
                "/register",
                data={"username": "ana", "password": "secreto"},
                follow_redirects=True,
            )
            assert registered.status_code == 200
            assert b"Tasks" in registered.data

            client.post("/logout")
            assert client.get("/tasks").status_code == 401

            logged_in = client.post(
                "/login",
                data={"username": "ana", "password": "secreto"},
                follow_redirects=True,
            )
            assert logged_in.status_code == 200
            assert b"Tasks" in logged_in.data
    finally:
        generated.AuthBase.metadata.drop_all(generated.db.engine)
        Model.metadata.drop_all(generated.db.engine)
        generated.db.dispose()
