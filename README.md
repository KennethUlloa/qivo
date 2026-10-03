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
and migrations directory. To generate migrations from multiple independent
declarative bases without loading the Flask application, list each base as
`module:attribute` in `sqlalchemy.model_bases`:

```toml
[sqlalchemy]
model_bases = ["app.models:Base", "app.audit.models:Base"]
```

The legacy `model_base` setting and the `--model-base` option still select a
single base; specifying `--model-base` overrides the configured list.

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
and manages sessions independently of the declarative model base:

```python
from flask import Flask
from sqlalchemy import delete, select
from sqlalchemy.orm import Mapped, mapped_column

from qivo.db.sql import Model, transaction
from qivo.db.sql.extensions import SQLEngine

app = Flask(__name__)
app.config.from_mapping(
	SQLALCHEMY_DATABASE_URI="sqlite:///app.db",
	SQLALCHEMY_ENGINE_OPTIONS={},
	SQLALCHEMY_SESSION_OPTIONS={},
)
db = SQLEngine(app)


class User(Model):
	__tablename__ = "users"

	id: Mapped[int] = mapped_column(primary_key=True)
	name: Mapped[str]
	is_active: Mapped[bool]


@app.get("/users")
def users():
	return db.session.scalars(select(User)).all()


@app.post("/users")
def create_user():
	user = User(name="admin", is_active=True)
	db.session.add(user)
	db.session.commit()
	return {"id": user.id}
```

`db.session` creates a session on first access, reuses it for the request, and
closes it when Flask tears down the request context. Use normal SQLAlchemy
operations for queries, writes, and deletes:

```python
user = db.session.scalars(
	select(User).where(User.name == "admin")
).first()
user.roles  # Loaded from the database while the request session is open.

db.session.delete(user)
db.session.commit()
```

`SQLEngine` does not create tables automatically; use the migration commands
for schema changes.

### Writes and Transactions

Commit writes explicitly with `db.session.commit()`. To group operations
atomically, `transaction()` shares its session with `db.session` and commits on
exit or rolls back if an exception escapes. The transaction session closes on
exit, and `db.session` then resolves to the request's global session again:

```python
from qivo.db.sql import transaction

with transaction() as t:
	user = t.scalars(select(User).where(User.name == "admin")).first()
    user.name = "root"
	# Committed when the block exits.
```

A nested `transaction()` joins the session of the enclosing block; the real
commit happens when the outermost block exits. Objects loaded only by the
transaction session are detached after it closes, so reload them through
`db.session` if they are needed later in the request:

```python
with transaction() as t:
	user = t.scalars(select(User).where(User.name == "admin")).first()
	user.name = "root"

user = db.session.get(User, user.id)
```

Use the yielded session for any SQLAlchemy operation, including bulk statements:

```python
with transaction() as t:
    t.add(Role(name="admin"))
    t.execute(delete(Role).where(Role.name == "obsolete"))
```

`transaction()` and `get_session()` resolve the `SQLEngine` attached to the
active Flask application. `model_base()` only creates isolated model metadata;
the model classes do not need to be registered with the engine.

## Sessions

By default the session travels in Flask's signed cookie. Attach `DatabaseSessions`
to keep it in the database instead; the views keep using `session` and the cookie
carries only an opaque id:

```python
from qivo.db.sql import DatabaseSessions, FlaskSessionModel, model_base

Base = model_base("Base")

class FlaskSessionRow(Base, FlaskSessionModel):
	__tablename__ = "qivo_sessions"

app = Flask(__name__)
app.config.from_mapping(
    SQLALCHEMY_DATABASE_URI="sqlite:///app.db",
    QIVO_SESSION_LIFETIME=60 * 60 * 24 * 14,  # 14 days, in seconds
)
qivo = Qivo(app)
db = SQLEngine(app)
sessions = DatabaseSessions(app, model=FlaskSessionRow)
```

```python
@app.get("/counter")
@qivo.view()
def counter():
    session["views"] = session.get("views", 0) + 1
    return {"views": session["views"]}
```

Declare the Flask session row as a mapped class on the same base passed to
`DatabaseSessions`, and make sure its base is listed in `sqlalchemy.model_bases`
(or selected by `model_base`) in `qivo.toml`. The regular migration commands
discover its table along with the other models:

```toml
[sqlalchemy]
model_bases = ["app.models:Base"]
```

```console
uv run qivo migrate --message "session table"
uv run qivo migrate:apply
```

There is no separate session section. `DatabaseSessions` uses the engine attached
to the app by `SQLEngine(app)`; the Flask session row only needs to be included
in the model base used by migrations. When using multiple bases, declare the
Flask session model on exactly one base; `sessions:prune` finds it automatically.

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
