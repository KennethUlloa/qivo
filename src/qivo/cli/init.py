import json
import keyword
from pathlib import Path

import click

_CONFIG_TEMPLATE = """[application]
name = {app_name}

[sqlalchemy]
url = {database_url}
{model_settings}
engine_options = {{}}

[migrations]
directory = "migrations"
compare_type = true
render_as_batch = true
"""

_APP_TEMPLATE = """from datetime import date

from flask import Flask, redirect, render_template, request, url_for

__AUTH_IMPORTS__
from qivo import Qivo
from qivo.db.sql.extensions import SQLEngine
from __PACKAGE__.models import Task

app = Flask(__name__, template_folder="template")
app.config.from_mapping(
    APP_NAME=__APP_NAME__,
    SQLALCHEMY_DATABASE_URI=__DATABASE_URL__,
    SQLALCHEMY_ENGINE_OPTIONS={},
    SQLALCHEMY_SESSION_OPTIONS={},
__AUTH_CONFIG__
)
qivo = Qivo(app__QIVO_OPTIONS__)
db = SQLEngine(app__DATABASE_OPTIONS__)
__AUTH_SETUP__

@app.route("/")
def index():
    return redirect(url_for("tasks"))

@app.errorhandler(401)
def unauthorized(error):
    return redirect(url_for("login"))

@app.get("/tasks")
@qivo.view(__VIEW_OPTIONS__)
def tasks():
    return render_template(
        "app.html",
        tasks=Task.q.all(),
        app_name=app.config["APP_NAME"],
    )


@app.post("/tasks")
@qivo.view(__VIEW_OPTIONS__)
def create_task():
    due_to_value = request.form.get("due_to", "")
    Task(
        title=request.form["title"],
        due_to=date.fromisoformat(due_to_value) if due_to_value else None,
        completed=False,
    ).q.save()
    return redirect(url_for("tasks"), code=303)


@app.delete("/task/<int:task_id>")
@qivo.view(__VIEW_OPTIONS__)
def delete_task(task_id: int):
    task = Task.q.get(task_id)
    if task is not None:
        task.q.delete()
    return redirect(url_for("tasks"), code=303)


@app.put("/task/<int:task_id>")
@qivo.view(__VIEW_OPTIONS__)
def toggle_task(task_id: int):
    task = Task.q.get(task_id)
    if task is not None:
        task.completed = request.form.get("completed") == "1"
        task.q.save()
    return redirect(url_for("tasks"), code=303)

__AUTH_ROUTES__
"""

_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ app_name }} · Tasks</title>
    <style>
        :root { color-scheme: light; font-family: system-ui, sans-serif; background: #f3f6f4; color: #19332d; }
        * { box-sizing: border-box; }
        body { margin: 0; padding: 40px 20px; }
        main { max-width: 900px; margin: 0 auto; }
        h1 { margin: 0 0 6px; font-size: 2rem; }
        .subtitle { margin: 0 0 28px; color: #60766f; }
        .new-task { display: grid; grid-template-columns: minmax(180px, 1fr) minmax(150px, 220px) auto; gap: 10px; margin-bottom: 24px; }
        input, button { min-height: 42px; border: 1px solid #c6d4ce; border-radius: 5px; padding: 9px 12px; font: inherit; }
        input { min-width: 0; background: white; }
        button { border-color: #176b52; background: #176b52; color: white; font-weight: 650; cursor: pointer; }
        button:hover { background: #105640; }
        .delete { border-color: #c9d4d0; background: white; color: #9d3d36; }
        .delete:hover { background: #fff0ed; }
        .table-wrap { overflow-x: auto; border: 1px solid #d8e1dd; border-radius: 6px; background: white; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 13px 16px; border-bottom: 1px solid #e7ece9; text-align: left; }
        th { color: #60766f; font-size: .8rem; text-transform: uppercase; }
        tr:last-child td { border-bottom: 0; }
        .title.completed { color: #82918b; text-decoration: line-through; }
        .status { width: 90px; text-align: center; }
        .status input { width: 18px; height: 18px; min-height: auto; accent-color: #176b52; cursor: pointer; }
        .actions { width: 110px; text-align: right; }
        .actions button { min-height: 34px; padding: 5px 10px; }
        .empty { padding: 28px; color: #60766f; text-align: center; }
        @media (max-width: 600px) {
            body { padding: 28px 14px; }
            .new-task { grid-template-columns: 1fr; }
            th, td { padding: 11px 10px; }
        }
    </style>
</head>
<body>
    <main>
        <h1>Tasks</h1>
        <p class="subtitle">One step at a time.</p>
        __AUTH_NAV__
        <form class="new-task" action="{{ url_for('tasks') }}" method="post">
            <input name="title" placeholder="What needs to get done?" required>
            <input name="due_to" type="date" aria-label="Due date">
            <button type="submit">Add task</button>
        </form>
        <div class="table-wrap">
            <table>
                <thead><tr><th>Task</th><th>Due date</th><th class="status">Complete</th><th class="actions">Actions</th></tr></thead>
                <tbody>
                {% for task in tasks %}
                    <tr>
                        <td class="title{% if task.completed %} completed{% endif %}">{{ task.title }}</td>
                        <td>{{ task.due_to.isoformat() if task.due_to else "-" }}</td>
                        <td class="status"><input type="checkbox" aria-label="Toggle status: {{ task.title }}" data-toggle="{{ task.id }}" {% if task.completed %}checked{% endif %}></td>
                        <td class="actions"><button class="delete" type="button" data-delete="{{ task.id }}">Delete</button></td>
                    </tr>
                {% else %}
                    <tr><td class="empty" colspan="4">No tasks yet. Add one above.</td></tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </main>
    <script>
        document.addEventListener("change", async (event) => {
            const checkbox = event.target.closest("[data-toggle]");
            if (!checkbox) return;
            const body = new URLSearchParams({completed: checkbox.checked ? "1" : "0"});
            const response = await fetch(`/task/${checkbox.dataset.toggle}`, {
                method: "PUT",
                headers: {"Content-Type": "application/x-www-form-urlencoded"},
                body
            });
            if (response.ok) window.location.reload();
        });
        document.addEventListener("click", async (event) => {
            const button = event.target.closest("[data-delete]");
            if (!button) return;
            const response = await fetch(`/task/${button.dataset.delete}`, {method: "DELETE"});
            if (response.ok) window.location.reload();
        });
    </script>
</body>
</html>"""

_AUTH_IMPORTS = """import os

from flask import g
from sqlalchemy import select
from werkzeug.exceptions import Unauthorized

from qivo.db.sql import Model
from qivo.db.sql.auth import AuthBase, DBSessionAuthenticator, User
"""

_AUTH_ROUTES = '''
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        try:
            authenticator.authenticate(
                {
                    "username": request.form.get("username", ""),
                    "password": request.form.get("password", ""),
                }
            )
        except Unauthorized:
            error = "Incorrect username or password."
        else:
            return redirect(url_for("tasks"))
    return render_template("login.html", app_name=app.config["APP_NAME"], error=error)


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            error = "Enter a username and password."
        else:
            with g.session_factory() as db_session:
                existing = db_session.scalar(
                    select(User.id).where(User.username == username)
                )
                if existing is not None:
                    error = "That username is already taken."
                else:
                    user = User(username=username)
                    user.set_password(password)
                    db_session.add(user)
                    db_session.commit()
            if error is None:
                authenticator.authenticate(
                    {"username": username, "password": password}
                )
                return redirect(url_for("tasks"))
    return render_template(
        "register.html", app_name=app.config["APP_NAME"], error=error
    )


@app.post("/logout")
def logout():
    authenticator.logout()
    return redirect(url_for("login"))
'''

_AUTH_LOGIN_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Log in · {{ app_name }}</title>
    <style>
        :root { color-scheme: light; font-family: system-ui, sans-serif; background: #f3f6f4; color: #19332d; }
        * { box-sizing: border-box; }
        body { margin: 0; padding: 40px 20px; }
        main { max-width: 420px; margin: 48px auto; padding: 28px; border: 1px solid #d8e1dd; border-radius: 6px; background: white; }
        h1 { margin: 0 0 8px; }
        p { color: #60766f; }
        label { display: block; margin: 18px 0 6px; font-weight: 600; }
        input, button { width: 100%; min-height: 44px; padding: 10px 12px; border: 1px solid #c6d4ce; border-radius: 5px; font: inherit; }
        button { margin-top: 22px; border-color: #176b52; background: #176b52; color: white; font-weight: 650; cursor: pointer; }
        a { color: #176b52; }
        .error { color: #9d3d36; }
    </style>
</head>
<body><main>
    <h1>Log in</h1>
    <p>{{ app_name }}</p>
    {% if error %}<p class="error">{{ error }}</p>{% endif %}
    <form method="post">
        <label for="username">Username</label>
        <input id="username" name="username" autocomplete="username" required>
        <label for="password">Password</label>
        <input id="password" name="password" type="password" autocomplete="current-password" required>
        <button type="submit">Sign in</button>
    </form>
    <p>New here? <a href="{{ url_for('register') }}">Create an account</a></p>
</main></body>
</html>"""

_AUTH_REGISTER_TEMPLATE = _AUTH_LOGIN_TEMPLATE.replace(
    "Log in", "Create an account"
).replace(
    "Sign in", "Create account"
).replace(
    "{{ url_for('register') }}", "{{ url_for('login') }}"
).replace(
    "Create an account</a>", "Log in</a>"
).replace(
    "New here?", "Already have an account?"
).replace(
    "current-password", "new-password"
)


_MODEL_TEMPLATE = """from datetime import date

from sqlalchemy import Date
from sqlalchemy.orm import Mapped, mapped_column

from qivo.db.sql import Model


class Task(Model):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    due_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed: Mapped[bool] = mapped_column(default=False)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "due_to": self.due_to,
            "completed": self.completed,
        }
"""


@click.command("init")
@click.option(
    "--path",
    "root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path.cwd,
    show_default=".",
)
@click.option("--package", "package_name", default="app", show_default=True)
@click.option(
    "--name",
    "app_name",
    prompt="Application name",
    required=True,
    help="Visible name of the application.",
)
@click.option("--database-url", default="sqlite:///app.db", show_default=True)
@click.option("--auth/--no-auth", default=None)
def init_command(
    root: Path,
    package_name: str,
    app_name: str,
    database_url: str,
    auth: bool | None,
) -> None:
    """Scaffold a suggested todo app without overwriting existing files."""
    if not package_name.isidentifier() or keyword.iskeyword(package_name):
        raise click.BadParameter(
            "must be a valid Python package name", param_hint="--package"
        )
    app_name = app_name.strip()
    if not app_name:
        raise click.BadParameter("cannot be empty", param_hint="--name")

    if auth is None:
        auth = click.confirm("Would you like to enable authentication?", default=False)

    if auth:
        model_settings = (
            f'models = ["{package_name}.models", "qivo.db.sql.auth"]\n'
            'model_bases = ["qivo.db.sql:Model", "qivo.db.sql.auth:AuthBase"]'
        )
        app_replacements = {
            "__AUTH_IMPORTS__": _AUTH_IMPORTS,
            "__AUTH_CONFIG__": (
                '    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),'
            ),
            "__QIVO_OPTIONS__": ', guards={"web": DBSessionAuthenticator()}',
            "__DATABASE_OPTIONS__": ", models=(Model, AuthBase)",
            "__AUTH_SETUP__": 'authenticator = qivo.guards["web"]',
            "__VIEW_OPTIONS__": "auth=True",
            "__AUTH_ROUTES__": _AUTH_ROUTES,
            "__AUTH_NAV__": (
                '<form action="{{ url_for(\'logout\') }}" method="post">'
                '<button class="delete" type="submit">Log out</button></form>'
            ),
        }
    else:
        model_settings = (
            f'models = ["{package_name}.models"]\n'
            'model_base = "qivo.db.sql:Model"'
        )
        app_replacements = {
            "__AUTH_IMPORTS__": "",
            "__AUTH_CONFIG__": "",
            "__QIVO_OPTIONS__": "",
            "__DATABASE_OPTIONS__": "",
            "__AUTH_SETUP__": "",
            "__VIEW_OPTIONS__": "",
            "__AUTH_ROUTES__": "",
            "__AUTH_NAV__": "",
        }

    app_contents = _APP_TEMPLATE.replace(
        "__DATABASE_URL__", json.dumps(database_url)
    ).replace("__PACKAGE__", package_name).replace(
        "__APP_NAME__", json.dumps(app_name)
    )
    for placeholder, value in app_replacements.items():
        app_contents = app_contents.replace(placeholder, value)

    files = {
        Path("qivo.toml"): _CONFIG_TEMPLATE.format(
            app_name=json.dumps(app_name),
            database_url=json.dumps(database_url),
            model_settings=model_settings,
        ),
        Path(package_name) / "__init__.py": "",
        Path(package_name) / "app.py": app_contents,
        Path(package_name) / "models.py": _MODEL_TEMPLATE,
        Path(package_name) / "template" / "app.html": _HTML_TEMPLATE.replace(
            "__AUTH_NAV__", app_replacements["__AUTH_NAV__"]
        ),
    }
    if auth:
        files[Path(package_name) / "template" / "login.html"] = (
            _AUTH_LOGIN_TEMPLATE
        )
        files[Path(package_name) / "template" / "register.html"] = (
            _AUTH_REGISTER_TEMPLATE
        )

    try:
        for relative_path, contents in files.items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                click.echo(f"Skipped existing {path}")
                continue
            path.write_text(contents, encoding="utf-8")
            click.echo(f"Created {path}")
    except OSError as error:
        raise click.ClickException(str(error)) from error