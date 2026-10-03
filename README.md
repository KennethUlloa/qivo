# Qivo

Qivo is a small Flask layer made of independent extensions: dependency injection,
authorization, response serialization, and a lazy SQLAlchemy session. Every app owns
its container, serializer, guards, and database engine, so nothing is imposed on
your layout and no database is chosen for you.

```console
uv add qivo
```

## Example

A single Flask app using every extension. Read the sections below for the details.

```toml
# qivo.toml
[application]
name = "Tasks"
host = "localhost"
port = 8000
import_path = "app:create_app"

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
```

```python
# app/__init__.py
from flask import Flask, session
from sqlalchemy import select
from werkzeug.exceptions import Forbidden, Unauthorized

from app.models import Task, User
from qivo.ext.auth import AuthManager, current_user, logged_in, permission
from qivo.ext.container import DIContainer, inject
from qivo.ext.serialization import Serializer, serialized
from qivo.ext.sql import SQL, db


def create_app():
	app = Flask(__name__)
	app.config.from_mapping(
		SECRET_KEY=b"secret",
		SQLALCHEMY_DATABASE_URI="sqlite:///app.db",
		SQLALCHEMY_ENGINE_OPTIONS={},
	)

	container = DIContainer(app)
	Serializer(app)
	SQL(app)
	auth = AuthManager(app)

	class Guard:
		def check_logged_in(self):
			return session.get("user_id") is not None

		def get_current_user(self, required=False):
			if not session.get("user_id"):
				return None

			user = db.get(User, session["user_id"])

			if required and user is None:
				return self.logged_in_check_failed()

			return user

		def permission_check_failed(self):
			raise Forbidden()

		def logged_in_check_failed(self):
			raise Unauthorized()

	@auth.guard_resolver()
	def get_guard():
		return Guard()

	container.register(TaskService)

	@app.get("/me")
	@serialized
	def me():
		return {"user": current_user()}

	@app.get("/tasks")
	@logged_in()
	@permission(["tasks:read"], strategy="all")
	@serialized
	@inject
	def index(service: TaskService):
		return service.all()

	return app


class TaskService:
	def all(self):
		return db.scalars(select(Task)).all()
```

```console
uv run qivo migrate -m "initial schema"
uv run qivo migrate:apply
uv run qivo seed users
uv run qivo run
```

Note that `@inject` is the innermost decorator: it is the one that fills the view
parameters, so `@serialized` has to wrap it, not the other way around.

## Configuration

The CLI reads `qivo.toml` from the current directory. The Flask app itself is
configured through `app.config`; qivo only reads the keys it documents.

| Section | Key | Purpose |
| --- | --- | --- |
| `application` | `name` | Application name. |
| | `import_path` | `module:attribute` of the Flask app or app factory. |
| | `host`, `port` | Defaults for `qivo run`. |
| `sqlalchemy` | `url` | Database URL used by `migrate` and `seed`. |
| | `engine_options` | Keyword arguments passed to `create_engine`. |
| `migrations` | `directory` | Alembic directory, created on the first revision. |
| | `compare_type`, `render_as_batch` | Passed to the Alembic environment. |
| | `model_bases` | `module:attribute` of each declarative base to compare. |
| `seed` | `registry_path` | `module:attribute` of the seeder registry. |

List every base your models use in `migrations.model_bases`; the migration commands
import them without loading the Flask application, so tables declared on any of
those bases are discovered.

```toml
[migrations]
model_bases = ["app.models:Model", "app.audit.models:Model"]
```

## Extensions

Every feature is a `BaseExtension`. Constructing it with an app attaches it, and
`init_app` can be used to attach it later, for example with an application factory:

```python
from qivo.ext.base import BaseExtension

class AuditExtension(BaseExtension):
	name = "qivo.audit"

	def setup(self, app):
		app.before_request(self.log_request)

	def log_request(self):
		...

AuditExtension(app)
```

- An extension is stored in `app.extensions[AuditExtension.name]`. Attaching it
  twice to the same app raises `RuntimeError`; different apps keep their own
  reference, which is what makes the factory pattern above possible.
- `SomeExtension.current()` returns the instance attached to the active app and
  raises `RuntimeError` outside of an application context or when nothing is
  attached.
- `setup(app)` runs during `init_app`, which is where an extension registers its
  hooks, such as `teardown_appcontext`.

The built-in names are `qivo.container`, `qivo.auth`, `qivo.serializer`, and
`qivo.sql`.

## Dependency Injection

`DIContainer` resolves call parameters from the annotations of a function. Only
registered types are injected, so a view keeps working when a parameter is not a
dependency of the container.

```python
from flask import Flask

from qivo.ext.container import DIContainer, inject

app = Flask(__name__)
container = DIContainer(app)


class Greeting:
	def __init__(self):
		self.message = "Hello"


container.register(Greeting)


@app.get("/greeting")
@inject
def greeting(service: Greeting):
	return {"message": service.message}
```

### Registration

```python
container.register(Greeting)                    # built by calling Greeting
container.register(Greeting, FakeGreeting)      # built by calling FakeGreeting
container.register(Greeting, make_greeting)     # built by calling make_greeting
container.register(Greeting, cached=-1)         # one instance for the app
container.register("clock", lambda: Clock())    # registered by token
```

- `cached=None` builds a new instance on every resolution, `cached=-1` reuses it
  forever, and `cached=60` reuses it for sixty seconds. The cache lives on the
  container, so it is shared by the whole application.
- Dependencies of a factory are resolved recursively: a factory annotated with
  another registered type receives it already built.
- `container.unregister(Greeting)` removes a registration and
  `container.clear_cache()` drops every cached instance.
- `*args` and `**kwargs` parameters are never injected, and explicit arguments
  always win over injected values.

### Tokens and injectors

`DIToken` resolves a registration by name instead of by type, and `Injector` builds
a value from the annotation of the parameter. Both are used as parameter defaults:

```python
from qivo.ext.container import DIToken, Injector


class Body(Injector):
	def __call__(self, type_):
		if hasattr(type_, "load_form"):
			return type_.load_form()

		return type_(request.form)


@app.post("/users")
@inject
def create_user(data: CreateUser = Body(), clock=DIToken("clock")):
	...
```

### Descriptor and helpers

`Injected` resolves on attribute access, which is handy for objects that are built
somewhere else, and `resolve` does the same thing imperatively. Both need an
application context.

```python
from qivo.ext.container import Injected, resolve


class UserService:
	repository: UserRepository = Injected(cached=True)

	def signup(self):
		self.repository.save(...)


repository = resolve(UserRepository)
```

`Injected(cached=True)` caches the value per object instance, and assigning to or
deleting the attribute replaces or clears that value. `Injected` requires a type
annotation, otherwise the class definition raises `TypeError`.

## Authorization

`AuthManager` keeps named guard resolvers, and each resolver returns an object
implementing `AuthGuard`. A guard is asked for a new instance on every check, so
keep it cheap to build.

```python
from flask import session
from werkzeug.exceptions import Forbidden, Unauthorized

from qivo.contracts.auth import AuthGuard
from qivo.ext.auth import AuthManager

auth = AuthManager(app)


class SessionGuard:
	def check_logged_in(self) -> bool:
		return session.get("user_id") is not None

	def get_current_user(self, required: bool = False):
		if not session.get("user_id"):
			return None

		user = db.get(User, session["user_id"])

		if required and user is None:
			return self.logged_in_check_failed()

		return user

	def permission_check_failed(self):
		raise Forbidden()

	def logged_in_check_failed(self):
		raise Unauthorized()


@auth.guard_resolver()
def get_guard():
	return SessionGuard()


@auth.guard_resolver("api")
def get_api_guard():
	return ApiGuard()
```

- The resolver without a name is the default guard, `auth.get_guard()` returns it
  and `auth.get_guard("api")` returns a named one; an unknown name raises
  `ValueError`.
- `permission_check_failed` and `logged_in_check_failed` decide what a failed
  check does: raise an exception, as above, or return a Flask response such as
  `{"error": "forbidden"}, 403`.
- The user object answers `any_permission` and `all_permissions`, so matching,
  including any wildcard support, is up to the model. `AuthenticatedUser` in
  `qivo.contracts.auth` describes the rest of the protocol.

Two decorators consume the guards:

```python
from qivo.ext.auth import current_user, logged_in, permission


@app.get("/tasks")
@logged_in()
def index():
	return current_user().to_dict()


@app.delete("/tasks/<int:task_id>")
@logged_in("api")
@permission(["tasks:delete"], strategy="all")
def delete(task_id):
	...
```

- `logged_in()` runs `check_logged_in` and calls `logged_in_check_failed` when it
  returns false. Both decorators accept a guard name.
- `permission(permissions, *, guard=None, strategy="any")` asks for a required
  user and then calls `any_permission` or `all_permissions` on it, depending on
  the strategy; `"any"` is the default. An unknown strategy raises `ValueError`.
- `current_user()` returns the user of the default guard, or `None`.

Since `permission` requests a required user, a guard that raises from
`get_current_user(True)` rejects the request before any permission is evaluated.

## Serialization

`Serializer` turns return values into JSON friendly data. Attach it to the app and
decorate the views that should use it:

```python
from qivo.ext.serialization import Serializer, serialized

serializer = Serializer(app)


@app.get("/accounts")
@serialized
def index():
	return [Account(id=1, balance=Decimal("9.99"))]
```

Values are converted in this order:

| Value | Result |
| --- | --- |
| `None` | `None` |
| A registered serializer definition | `definition.serialize(value)` |
| An object with `to_dict` | `to_dict()` serialized again |
| `dict` | keys and values serialized |
| A dataclass | `asdict` and serialized again |
| `list`, `tuple`, `set`, `frozenset` | a list of serialized items |
| `Enum` | the serialized value |
| `datetime`, `date`, `time` | ISO 8601 string |
| `UUID`, `Decimal` | string |
| Anything else | the value itself |

A serializer definition is any object with `match` and `serialize`, and the first
one that matches wins:

```python
class AccountSerializer:
	def match(self, value):
		return isinstance(value, Account)

	def serialize(self, value):
		return {"id": str(value.id), "balance": str(value.balance)}


serializer.add(AccountSerializer())
```

`@serialized` preserves the metadata of the view, and needs an application context
because it resolves the serializer attached to the active app.

## SQL

`SQL` builds the engine from the app configuration and exposes one session per
application context. `db` is a proxy to that session, so it is used directly:

```python
from flask import Flask
from sqlalchemy import select
from sqlalchemy.orm import Mapped, mapped_column

from app.models import User
from qivo.ext.sql import SQL, db

app = Flask(__name__)
app.config.from_mapping(
	SQLALCHEMY_DATABASE_URI="sqlite:///app.db",
	SQLALCHEMY_ENGINE_OPTIONS={},
)
sql = SQL(app)


@app.get("/users")
def index():
	return [user.name for user in db.scalars(select(User)).all()]


@app.post("/users")
def create_user():
	db.add(User(name="admin"))
	db.commit()

	return {"id": db.query(User).one().id}
```

- The session is created on the first use, reused while the application context
  is alive, and closed by Flask when the context is torn down.
- `SQL(app, engine=engine)` accepts a ready engine, and `SQL(app, options={...})`
  overrides `SQLALCHEMY_ENGINE_OPTIONS`.
- A missing `SQLALCHEMY_DATABASE_URI` raises `ValueError`.
- Tables are never created automatically; use the migration commands or
  `Model.metadata.create_all(sql.engine)` while developing.
- Using `db` outside of an application context raises `RuntimeError`.

## Models

`to_dict` reads the mapped columns of a model, so a serializer is not needed to
return rows. `__exclude__` removes columns and `__include__` adds anything
reachable from the instance, such as properties or relationships:

```python
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from qivo.sql.utils import to_dict


class Model(DeclarativeBase):
	def to_dict(self):
		return to_dict(self)


class Task(Model):
	__tablename__ = "tasks"
	__exclude__ = ["notes"]
	__include__ = ["status"]

	id: Mapped[int] = mapped_column(primary_key=True)
	title: Mapped[str]

	@property
	def status(self):
		return "done" if self.completed else "open"
```

`TimestampMixin` adds `created_at` and `updated_at` columns, filled by the
database:

```python
from qivo.sql.mixins import TimestampMixin


class Task(TimestampMixin, Model):
	__tablename__ = "tasks"
	...
```

`Paginated` slices a query and reports whether more rows follow:

```python
from flask import request

from qivo.sql.utils import Paginated


@app.get("/users")
def index():
	page = Paginated.get(db.query(User), request.args.get("page", 1), 25)

	return page.to_dict()
```

`Paginated` exposes `page`, `per_page`, `items`, `total` and `has_next`. Its
`to_dict` calls `to_dict()` on every item that has it, so a model like the one
above needs no extra serializer.

## Seeders

A seeder receives the session and decides when to commit. The CLI never commits, so
a seeder that forgets to do it is discarded when the session closes:

```python
from qivo.sql.seed import BaseSeeder

from app.models import User


class UserSeeder(BaseSeeder):
	name = "users"

	def run(self):
		self.first_or_create(
			User(username="admin", permissions=["tasks:read"]),
			User.username == "admin",
		)
		self.session.commit()


seeders = {"users": UserSeeder}
```

- `first_or_create(instance, match)` adds the instance only when nothing matches.
- `create_or_update(Model, match, data)` inserts the data when nothing matches and
  updates it otherwise, without touching the columns missing from `data`.

## CLI

Every command reads `./qivo.toml`.

```console
uv run qivo run [--host HOST] [--port PORT] [--debug]
uv run qivo migrate [-m MESSAGE] [--empty]
uv run qivo migrate:apply [REVISION]
uv run qivo migrate:revert [REVISION]
uv run qivo seed SEEDER
```

`run` imports `application.import_path`, accepts either a Flask app or a factory
returning one, and uses `host` and `port` from the configuration unless the options
say otherwise.

`migrate` autogenerates a revision from the bases listed in `model_bases`, and
`--empty` writes a blank one instead. `migrate:apply` upgrades to `head` and
`migrate:revert` downgrades one revision, both accepting a target such as
`head`, `-1` or `base`.

Note that `migrate:apply base` is a no-op, since `base` is where an upgrade starts;
use `migrate:revert base` to revert everything.

`seed` builds the engine from `sqlalchemy.url`, resolves the seeder registry from
`seed.registry_path`, and runs the requested seeder.

## Migrations

The commands above are a thin wrapper around `AlembicMigrations`, which can also be
driven from Python:

```python
from qivo.cli.migrate.base import AlembicMigrations, MigrationConfig

migrations = AlembicMigrations(
	engine,
	[Model.metadata],
	MigrationConfig(directory="db/migrations", compare_type=True),
)

migrations.revision("initial schema")
migrations.upgrade()          # head
migrations.downgrade("base")
migrations.stamp("head")      # mark without applying
```

- `metadata` accepts one `MetaData` or a list of them, one per declarative base.
- The Alembic directory is created on the first use. A directory with files but no
  `env.py`, or an `env.py` without `alembic.ini`, `script.py.mako` and `versions`,
  raises `RuntimeError` instead of being overwritten.
- The generated environment reads the engine and the metadata from the Alembic
  configuration, so migrations never import the Flask application.

## Testing

```console
uv sync --group dev
uv run pytest
```

The suite covers every module of the library: the extensions, the container, the
serialization rules, the session lifecycle, the helpers, the settings, the
migrations, and the CLI. Tests run in a temporary directory and never touch your
project files or the demo application.