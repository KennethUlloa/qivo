from datetime import datetime, timedelta

import pytest

from qivo.ext.container import (
    DIContainer,
    DIToken,
    DependencyInfo,
    Injected,
    Injector,
    container,
    inject,
    resolve,
)


class Repository:
    def __init__(self, name="default"):
        self.name = name


class Service:
    def __init__(self, repository: Repository):
        self.repository = repository


@pytest.fixture
def di(app):
    return DIContainer(app)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_and_resolve_by_type(di):
    di.register(Repository)

    instance = di.resolve(Repository)

    assert isinstance(instance, Repository)
    assert instance.name == "default"


def test_resolve_builds_a_new_instance_without_cache(di):
    di.register(Repository)

    assert di.resolve(Repository) is not di.resolve(Repository)


def test_register_with_a_replacement_factory(di):
    calls = []

    class FakeRepository(Repository):
        pass

    def factory(name="fake"):
        calls.append(name)
        return FakeRepository(name=name)

    di.register(Repository, factory, cached=-1)

    instance = di.resolve(Repository)

    assert isinstance(instance, FakeRepository)
    assert instance.name == "fake"
    assert calls == ["fake"]


def test_register_a_class_as_replacement(di):
    di.register(Repository, lambda: Repository(name="replaced"), cached=-1)

    assert di.resolve(Repository).name == "replaced"


def test_register_by_token(di):
    di.register("repository", Repository, cached=-1)

    assert isinstance(di.resolve("repository"), Repository)


def test_register_token_requires_a_replacement(di):
    with pytest.raises(ValueError, match="Replacement is required"):
        di.register("repository")


def test_resolve_unregistered_dependency(di):
    with pytest.raises(ValueError, match="Could not resolve dependency"):
        di.resolve(Repository)

    with pytest.raises(ValueError, match="Could not resolve dependency"):
        di.resolve("repository")


def test_unregister_removes_the_dependency(di):
    di.register(Repository)
    di.unregister(Repository)

    with pytest.raises(ValueError):
        di.resolve(Repository)


def test_unregister_token(di):
    di.register("repository", Repository)
    di.unregister("repository")

    with pytest.raises(ValueError):
        di.resolve("repository")


def test_unregister_unknown_dependency_is_a_noop(di):
    di.unregister(Repository)
    di.unregister("repository")


def test_register_replaces_previous_registration(di):
    di.register(Repository, lambda: Repository(name="first"), cached=-1)
    di.register(Repository, lambda: Repository(name="second"), cached=-1)

    assert di.resolve(Repository).name == "second"


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


def test_cached_forever_reuses_the_instance(di):
    di.register(Repository, cached=-1)

    assert di.resolve(Repository) is di.resolve(Repository)


def test_cached_for_a_time_window_reuses_the_instance(di):
    di.register(Repository, cached=60)

    assert di.resolve(Repository) is di.resolve(Repository)


def test_cached_instance_is_dropped_when_the_window_expires(di):
    di.register(Repository, cached=60)
    first = di.resolve(Repository)

    di._type_registry[Repository]._last_call = datetime.now() - timedelta(seconds=61)

    assert di.resolve(Repository) is not first


def test_registered_by_token_dependencies_are_cached(di):
    di.register("repository", Repository, cached=-1)

    assert di.resolve("repository") is di.resolve("repository")


def test_clear_cache_for_a_single_dependency(di):
    di.register(Repository, cached=-1)
    di.register(Service, cached=-1)
    repository = di.resolve(Repository)
    service = di.resolve(Service)

    di.clear_cache(Repository)

    assert di.resolve(Repository) is not repository
    assert di.resolve(Service) is service


def test_clear_cache_for_a_single_token(di):
    di.register("repository", Repository, cached=-1)
    repository = di.resolve("repository")

    di.clear_cache("repository")

    assert di.resolve("repository") is not repository


def test_clear_cache_everything(di):
    di.register(Repository, cached=-1)
    di.register("repository", Repository, cached=-1)
    repository = di.resolve(Repository)
    token = di.resolve("repository")

    di.clear_cache()

    assert di.resolve(Repository) is not repository
    assert di.resolve("repository") is not token


def test_clear_cache_ignores_unknown_dependencies(di):
    di.clear_cache(Repository)
    di.clear_cache("repository")


# ---------------------------------------------------------------------------
# DependencyInfo cache semantics
# ---------------------------------------------------------------------------


def test_dependency_info_without_cache_time_is_always_expired():
    info = DependencyInfo(callback=Repository)

    assert info.is_cache_expired is True
    assert info.is_cached is False


def test_dependency_info_cached_forever():
    info = DependencyInfo(callback=Repository, cache_time=-1)

    assert info.is_cache_expired is True

    info.cache("instance")

    assert info.is_cache_expired is False
    assert info.is_cached is True
    assert info.cached() == "instance"


def test_dependency_info_expires_after_the_given_seconds():
    info = DependencyInfo(callback=Repository, cache_time=30)

    assert info.is_cache_expired is True

    info.cache("instance")
    assert info.is_cache_expired is False

    info._last_call = datetime.now() - timedelta(seconds=31)
    assert info.is_cache_expired is True


def test_dependency_info_clear_cache():
    info = DependencyInfo(callback=Repository, cache_time=-1)
    info.cache("instance")

    info.clear_cache()

    assert info.cached() is None
    assert info.is_cached is False


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_resolve_passes_positional_and_keyword_arguments(di):
    di.register(Repository)

    positional = di.resolve(Repository, "positional")
    keyword = di.resolve(Repository, name="keyword")

    assert positional.name == "positional"
    assert keyword.name == "keyword"


def test_resolve_injects_dependencies_of_the_factory(di):
    di.register(Repository)
    di.register(Service)

    service = di.resolve(Service)

    assert isinstance(service.repository, Repository)


def test_explicit_arguments_override_injected_dependencies(di):
    other = Repository("other")
    di.register(Repository, cached=-1)
    di.register(Service)

    service = di.resolve(Service, repository=other)

    assert service.repository is other


def test_resolve_params_injects_registered_annotations(di):
    di.register(Repository)

    def handler(repository: Repository, other: str = "plain"):
        return repository, other

    resolved = di.resolve_params(handler)

    assert isinstance(resolved["repository"], Repository)
    assert "other" not in resolved


def test_resolve_params_ignores_unregistered_annotations(di):
    def handler(repository: Repository):
        return repository

    assert di.resolve_params(handler) == {}


def test_resolve_params_ignores_parameters_without_annotation(di):
    def handler(repository):
        return repository

    assert di.resolve_params(handler) == {}


def test_resolve_params_ignores_var_args(di):
    di.register(Repository)

    def handler(*args, **kwargs):
        return args, kwargs

    assert di.resolve_params(handler) == {}


def test_resolve_params_resolves_ditoken_defaults(di):
    di.register("repository", Repository, cached=-1)

    def handler(repository=DIToken("repository")):
        return repository

    assert isinstance(di.resolve_params(handler)["repository"], Repository)


def test_resolve_params_calls_injector_defaults(di):
    class Body(Injector):
        def __call__(self, type_):
            return type_(payload="from-injector")

    class Payload:
        def __init__(self, payload):
            self.payload = payload

    def handler(body: Payload = Body()):
        return body

    assert di.resolve_params(handler)["body"].payload == "from-injector"


def test_resolve_params_injects_registered_annotations_with_defaults(di):
    di.register(Repository)

    def handler(value: int, repository: Repository = None):
        return value, repository

    resolved = di.resolve_params(handler)

    assert "value" not in resolved
    assert isinstance(resolved["repository"], Repository)


def test_resolve_missing_required_dependency_fails_on_call(di):
    def handler(repository: Repository):
        return repository

    with pytest.raises(TypeError):
        handler()


# ---------------------------------------------------------------------------
# Flask integration
# ---------------------------------------------------------------------------


def test_container_current_requires_an_app_context():
    with pytest.raises(RuntimeError):
        DIContainer.current()


def test_container_proxy_resolves_the_current_container(app):
    di = DIContainer(app)
    di.register(Repository, cached=-1)

    with app.app_context():
        assert isinstance(container, DIContainer)
        assert isinstance(container.resolve(Repository), Repository)


def test_container_proxy_outside_app_context():
    with pytest.raises(RuntimeError):
        container.resolve(Repository)


def test_resolve_function_uses_the_current_container(app):
    DIContainer(app).register(Repository, cached=-1)

    with app.app_context():
        assert isinstance(resolve(Repository), Repository)


def test_resolve_function_outside_app_context():
    with pytest.raises(RuntimeError):
        resolve(Repository)


# ---------------------------------------------------------------------------
# Injected descriptor
# ---------------------------------------------------------------------------


def test_injected_requires_a_type_annotation(di):
    with pytest.raises(TypeError, match="must have a type annotation"):

        class Broken:
            repository = Injected()


def test_injected_resolves_on_access(app, di):
    di.register(Repository)

    class Handler:
        repository: Repository = Injected()

    handler = Handler()

    with app.app_context():
        assert isinstance(handler.repository, Repository)


def test_injected_resolves_on_every_access_when_not_cached(app, di):
    di.register(Repository)

    class Handler:
        repository: Repository = Injected()

    handler = Handler()

    with app.app_context():
        assert handler.repository is not handler.repository


def test_injected_caches_per_instance(app, di):
    di.register(Repository)

    class Handler:
        repository: Repository = Injected(cached=True)

    handler = Handler()
    other = Handler()

    with app.app_context():
        assert handler.repository is handler.repository
        assert handler.repository is not other.repository


def test_injected_requires_an_app_context(app, di):
    di.register(Repository)

    class Handler:
        repository: Repository = Injected()

    with pytest.raises(RuntimeError):
        Handler().repository


def test_injected_class_access_returns_the_descriptor(di):
    class Handler:
        repository: Repository = Injected()

    assert isinstance(Handler.repository, Injected)


def test_injected_can_be_overwritten(app, di):
    di.register(Repository)

    class Handler:
        repository: Repository = Injected(cached=True)

    handler = Handler()

    with app.app_context():
        handler.repository = "manual"

        assert handler.repository == "manual"


def test_injected_can_be_deleted(app, di):
    di.register(Repository)

    class Handler:
        repository: Repository = Injected(cached=True)

    handler = Handler()

    with app.app_context():
        handler.repository = "manual"
        del handler.repository

        assert isinstance(handler.repository, Repository)


def test_injected_deleting_without_cache_is_a_noop(app, di):
    di.register(Repository)

    class Handler:
        repository: Repository = Injected()

    handler = Handler()

    with app.app_context():
        del handler.repository

        assert isinstance(handler.repository, Repository)


# ---------------------------------------------------------------------------
# @inject decorator
# ---------------------------------------------------------------------------


def test_inject_resolves_annotated_dependencies(app, di):
    di.register(Repository)
    di.register(Service)

    @inject
    def handler(service: Service):
        return service

    with app.app_context():
        assert isinstance(handler().repository, Repository)


def test_inject_explicit_arguments_win(app, di):
    repository = Repository("explicit")
    di.register(Repository)

    @inject
    def handler(value: Repository):
        return value

    with app.app_context():
        assert handler(value=repository) is repository


def test_inject_supports_ditoken(app, di):
    di.register("repository", Repository, cached=-1)

    @inject
    def handler(repository=DIToken("repository")):
        return repository

    with app.app_context():
        assert isinstance(handler(), Repository)


def test_inject_injects_nested_dependencies(app, di):
    di.register(Repository)
    di.register(Service)

    @inject
    def handler(service: Service, suffix: str = "!"):
        return f"{service.repository.name}{suffix}"

    with app.app_context():
        assert handler() == "default!"


def test_inject_preserves_the_function_metadata(di):
    @inject
    def handler(repository: Repository):
        """Docstring."""

    assert handler.__name__ == "handler"
    assert handler.__doc__ == "Docstring."


def test_inject_outside_app_context():
    @inject
    def handler(repository: Repository):
        return repository

    with pytest.raises(RuntimeError):
        handler()


def test_inject_in_a_flask_view(app, di):
    di.register(Repository)

    @app.get("/service")
    @inject
    def handler(repository: Repository):
        return {"name": repository.name}

    client = app.test_client()

    assert client.get("/service").json == {"name": "default"}