# Qivo

Qivo is a small Flask layer for dependency injection, authorization, and response
serialization. Each app owns its container, serializer, guards, and view-extension
pipeline; it does not choose or depend on a database.

## CLI

Initialize a suggested app layout in the current directory, or choose a target
directory and Python package name:

```console
uv run qivo init
uv run qivo init --name "Mi lista" --path ./service --package service
```

`qivo init` always asks for a required application name unless `--name` is passed.
The scaffold contains a minimal Flask todo list with a `Task` model, the four CRUD
endpoints, `qivo.toml`, and one HTML template at `app/template/app.html`, loaded
with Flask's normal `render_template` mechanism. Existing files are left untouched.
Edit the TOML settings to configure the database URL, model modules, model base,
and migrations directory.

```console
uv run qivo migrate --message "initial schema"
uv run qivo migrate:apply
uv run qivo migrate:revert
uv run qivo migrate:revert base
```

Migration commands accept `--config`, `--database-url`, `--model-base`, repeated
`--models`, and `--migrations-dir` overrides. `migrate` also supports `--empty`;
`migrate:apply` defaults to `head`, and `migrate:revert` defaults to `-1`.

```python
from flask import Flask

from qivo import Qivo

app = Flask(__name__)
qivo = Qivo(app)


class Greeting:
	def __init__(self):
		self.message = "Hello"


qivo.container.register(Greeting)


@app.route("/greeting", methods=["GET"])
@qivo.view()
def greeting(service: Greeting):
	return {"message": service.message}
```

## Authorization

Implement `Authenticator` against the identity source used by your application,
then add it to the app's `guards` mapping. Apply authentication or policies per
route with `auth`, `guard`, and `policies`:

```python
from qivo.guards import Authenticator, WithAll

qivo.guards["web"] = MyAuthenticator()


@app.route("/admin", methods=["GET"])
@qivo.view(auth=True, policies=[WithAll(["admin:read"])])
def admin_view():
	return {"ok": True}
```

## Extending Views

Add a `ViewExtension` to customize view handling without changing `Qivo` or the
built-in features. Extensions are applied outside-in in registration order. Pass
extension-specific route settings directly to `qivo.view(...)`:

```python
from functools import wraps


class AuditExtension:
	def wrap_view(self, app, view_func, *, options):
		@wraps(view_func)
		def wrapper(*args, **kwargs):
			result = view_func(*args, **kwargs)
			app.app.logger.info("audit category=%s", options.get("audit_category"))
			return result

		return wrapper


qivo.register_view_extension(AuditExtension())


@app.route("/records", methods=["GET"])
@qivo.view(audit_category="records")
def records():
	return []
```

An extension receives the Qivo instance, the next view callable, and an immutable
mapping of Qivo route options. Register extensions before declaring routes so they
wrap those routes. Place `@qivo.view(...)` directly below either `@app.route(...)`
or `@blueprint.route(...)`; Flask handles registration and lifecycle as usual.

## SQLAlchemy

Configure the database declaratively in Flask, then attach the SQL extension.
`SQLEngine` reads the URL, engine options, and session options from `app.config`
and configures the model base automatically:

```python
from flask import Flask
from sqlalchemy import delete
from sqlalchemy.orm import Mapped, mapped_column

from qivo import Qivo
from qivo.db.sql import Model, close_session, get_session, transaction
from qivo.db.sql.extensions import SQLEngine

app = Flask(__name__)
app.config.from_mapping(
	SQLALCHEMY_DATABASE_URI="sqlite:///app.db",
	SQLALCHEMY_ENGINE_OPTIONS={},
	SQLALCHEMY_SESSION_OPTIONS={},
)
qivo = Qivo(app)
db = SQLEngine(app)


class User(Model):
	__tablename__ = "users"

	id: Mapped[int] = mapped_column(primary_key=True)
	name: Mapped[str]
	is_active: Mapped[bool]


user = User(name="admin", is_active=True)
user.q.save()

user = User.q.get(user.id)
user.name = "root"
user.q.save()

user.q.delete()  # Returns False if the row no longer exists.

admin = User.q.filter(name="admin").first()
active_admins = User.q.where(User.name == "admin").where(
	User.is_active == True
).all()
```

Queries run on a shared read session that stays open while the request does, so
a returned instance keeps its relationships available:

```python
user = User.q.where(User.name == "admin").first()
user.roles  # Loaded from the database on first access.
```

Outside a request, close it explicitly with `close_session()` or call
`SQLEngine.dispose()`. `SQLEngine` does not create tables automatically; use the
migration commands for schema changes.

### Writes and Transactions

Outside a transaction, `save()` and `delete()` use their own connection and
commit only the instance and the relationships it holds. `save()` returns the
same instance, and objects left unsaved on the read session raise an error when
it is closed.

Inside `transaction()` every query and write shares one session and connection.
`save()` and `delete()` flush instead of committing, so the whole block commits
on exit or rolls back as a unit:

```python
from qivo.db.sql import transaction

with transaction() as t:
    user = User.q.where(User.name == "admin").first()
    user.name = "root"
    user.q.save()  # Committed when the block exits.
```

A nested `transaction()` joins the session of the enclosing block; the real
commit happens when the outermost block exits. An instance loaded before the
block keeps its identity and moves into the transaction session, so the variable
you already have is the one that gets saved. On a successful commit that session
becomes the shared read session, which keeps instances usable after the block:

```python
with transaction() as t:
    user = User.q.where(User.name == "admin").first()
    user.q.save()

user.roles  # Still loadable after the block.
```

Use the yielded session for anything the query API does not cover, such as bulk
statements or `session.add()`:

```python
with transaction() as t:
    t.add(Role(name="admin"))
    t.execute(delete(Role).where(Role.name == "obsolete"))
```

With several model bases, pass the base explicitly: `transaction(OtherBase)`.

For an isolated declarative base, build one with `model_base()` and hand it to
`SQLEngine(app, model=Base)`. Without an argument, `transaction()`, `get_session()`
and `close_session()` target the most recently configured base.

## Sessions

By default the session travels in Flask's signed cookie. Attach `DatabaseSessions`
to keep it in the database instead; the views keep using `session` and the cookie
carries only an opaque id:

```python
from qivo.db.sql import DatabaseSessions

app = Flask(__name__)
app.config.from_mapping(
    SQLALCHEMY_DATABASE_URI="sqlite:///app.db",
    QIVO_SESSION_LIFETIME=60 * 60 * 24 * 14,  # 14 days, in seconds
)
qivo = Qivo(app)
db = SQLEngine(app)
sessions = DatabaseSessions(app)  # Without this the cookie keeps the session.
```

```python
@app.get("/counter")
@qivo.view()
def counter():
    session["views"] = session.get("views", 0) + 1
    return {"views": session["views"]}
```

The rows live in the tables of the same model base, so tell the migration commands
about them with a `[session]` section in `qivo.toml` and create the table:

```console
uv run qivo migrate --message "session table"
uv run qivo migrate:apply
```

```toml
[session]
enabled = true
table = "qivo_sessions"
```

`table` defaults to `qivo_sessions`, and `enabled` only matters for migrations:
the commands do not run your app code, so they register the table from this
section instead of finding it at runtime. With an isolated base, hand the same
one to both extensions, `SQLEngine(app, model=Base)` and
`DatabaseSessions(app, model=Base)`, so the table lands in that metadata.

Expired rows are deleted by a sweep that runs once every
`QIVO_SESSION_CLEANUP_INTERVAL` requests, one hundred by default, and on demand:

```console
uv run qivo sessions:prune
```

Notes:

- Values must be JSON serializable, so store a date as an ISO string instead of
  a `date`. In exchange, the session is queryable and shared by every process.
- `QIVO_SESSION_LIFETIME` sets how long a browser session row lives; a permanent
  session uses `PERMANENT_SESSION_LIFETIME` instead.
- Nothing is signed, so `SECRET_KEY` is not required for the session.
- Two concurrent requests on the same session overwrite each other, the same way
  the default cookie behaves.

## Migrations

`AlembicMigrations` uses `Model.metadata` and creates a standard `migrations/`
directory on the first revision. Import all model modules before autogenerating
so Alembic can see their tables:

```python
from qivo.db.sql import AlembicMigrations

migrations = AlembicMigrations(engine)
migrations.revision("initial schema")
migrations.upgrade()
```

The directory and autogeneration options can be customized:

```python
from qivo.db.sql import AlembicMigrations, MigrationConfig

migrations = AlembicMigrations(
	engine,
	config=MigrationConfig(directory="db/migrations", compare_type=True),
)
```

Use `migrations.downgrade()` to revert one revision or pass a target such as
`"base"`; use `migrations.stamp()` to mark a database without applying scripts.
