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
and configures the model base automatically. Each terminal query opens and closes
its own session:

```python
from flask import Flask
from sqlalchemy.orm import Mapped, mapped_column

from qivo import Qivo
from qivo.db.sql import Model
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

Use eager loading for relationships that must be accessed after a query returns,
because its session is closed when the operation completes. `SQLEngine` does not
create tables automatically; use the migration commands for schema changes.

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
