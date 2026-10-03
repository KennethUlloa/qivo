from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from inspect import Parameter, signature
from typing import Any, Callable, Type, TypeVar, overload

from flask import Flask, current_app
from werkzeug.local import LocalProxy

from qivo.ext.base import BaseExtension

T = TypeVar("T")
Dependency = Callable[..., Any]


# ============================================================================
# Tokens
# ============================================================================


@dataclass(frozen=True, slots=True)
class DIToken:
    """
    Explicitly identifies a dependency by name instead of by type.

    Example:

        def service(repo=DIToken("user_repository")):
            ...
    """

    name: str


# ============================================================================
# Injection marker
# ============================================================================


@dataclass(frozen=True, slots=True)
class Injector:
    """
    Marker for annotation handling.
    """

    def __call__(self, type_: Type):
        pass


# ============================================================================
# Dependency metadata
# ============================================================================


@dataclass(slots=True)
class DependencyInfo:
    callback: Dependency
    cache_time: int | float | None = None
    _instance: Any = None
    _last_call: datetime | None = None

    @property
    def is_cached(self) -> bool:
        return self._last_call is not None

    @property
    def is_cache_expired(self) -> bool:
        """
        Cache semantics:

        None -> do not cache
        < 0  -> cache forever
        >= 0 -> cache for N seconds
        """

        if self.cache_time is None:
            return True

        if self.cache_time < 0:
            return not self.is_cached

        if not self.is_cached:
            return True

        assert self._last_call is not None

        elapsed = (datetime.now() - self._last_call).total_seconds()

        return elapsed > self.cache_time

    def cache(self, instance: Any) -> None:
        self._instance = instance
        self._last_call = datetime.now()

    def cached(self) -> Any:
        return self._instance

    def clear_cache(self) -> None:
        self._instance = None
        self._last_call = None


# ============================================================================
# DI Container
# ============================================================================


class DIContainer(BaseExtension):
    """
    Application-scoped dependency injection container.

    Dependencies can be registered either by type:

        container.register(UserRepository)

    or by token:

        container.register(
            "user_repository",
            UserRepository,
        )

    Cached dependencies:

        container.register(
            Database,
            cached=-1,
        )

    `cached=-1` means cache forever.
    `cached=60` means cache for 60 seconds.
    `cached=None` means don't cache.
    """

    name = "qivo.container"

    def __init__(self, app: Flask | None = None):
        super().__init__(app)

        self._type_registry: dict[type, DependencyInfo] = {}
        self._token_registry: dict[str, DependencyInfo] = {}

    # ------------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------------

    @overload
    def register(
        self,
        type_: type[T],
        replacement: Dependency | None = None,
        cached: int | float | None = None,
    ) -> None: ...

    @overload
    def register(
        self,
        type_: str,
        replacement: Dependency,
        cached: int | float | None = None,
    ) -> None: ...

    def register(
        self,
        type_: type[T] | str,
        replacement: Dependency | None = None,
        cached: int | float | None = None,
    ) -> None:
        """
        Register a dependency.

        Type registration:

            container.register(UserRepository)

        This resolves UserRepository by constructing UserRepository.

        Replacement:

            container.register(
                UserRepository,
                MockUserRepository,
            )

        Token:

            container.register(
                "repository",
                UserRepository,
            )
        """

        if isinstance(type_, str):
            if replacement is None:
                raise ValueError(f"Replacement is required for token '{type_}'")

            self._token_registry[type_] = DependencyInfo(
                callback=replacement,
                cache_time=cached,
            )

            return

        callback = replacement or type_

        self._type_registry[type_] = DependencyInfo(
            callback=callback,
            cache_time=cached,
        )

    def unregister(
        self,
        type_: type | str,
    ) -> None:
        if isinstance(type_, str):
            self._token_registry.pop(type_, None)
        else:
            self._type_registry.pop(type_, None)

    def clear_cache(
        self,
        type_: type | str | None = None,
    ) -> None:
        if type_ is None:
            for info in self._type_registry.values():
                info.clear_cache()

            for info in self._token_registry.values():
                info.clear_cache()

            return

        registry = (
            self._token_registry if isinstance(type_, str) else self._type_registry
        )

        info = registry.get(type_)

        if info is not None:
            info.clear_cache()

    # ------------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------------

    def _get_dependency_info(
        self,
        type_: type | str,
    ) -> DependencyInfo:
        registry = (
            self._token_registry if isinstance(type_, str) else self._type_registry
        )

        dependency_info = registry.get(type_)

        if dependency_info is None:
            raise ValueError(f"Could not resolve dependency: {type_!r}")

        return dependency_info

    # ------------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------------

    def resolve(
        self,
        type_: type[T] | str,
        *args: Any,
        **kwargs: Any,
    ) -> T:
        dependency_info = self._get_dependency_info(type_)

        if not dependency_info.is_cache_expired:
            return dependency_info.cached()

        target = dependency_info.callback

        resolved_kwargs = self.resolve_params(target)

        # Explicit arguments always win over injected dependencies.
        resolved_kwargs.update(kwargs)

        instance = target(
            *args,
            **resolved_kwargs,
        )

        if dependency_info.cache_time is not None:
            dependency_info.cache(instance)

        return instance

    # ------------------------------------------------------------------------
    # Parameter resolution
    # ------------------------------------------------------------------------

    def resolve_params(
        self,
        function: Dependency,
    ) -> dict[str, Any]:
        resolved: dict[str, Any] = {}

        for name, parameter in signature(function).parameters.items():

            # *args / **kwargs don't represent dependencies.
            if parameter.kind in (
                Parameter.VAR_POSITIONAL,
                Parameter.VAR_KEYWORD,
            ):
                continue

            # An explicit default value supplied by the caller should be
            # handled by Python itself.
            if parameter.default is Parameter.empty:
                dependency = self._resolve_annotation(parameter.annotation)

                if dependency is not _NOT_RESOLVED:
                    resolved[name] = dependency

                continue

            # Explicit token:
            #
            #     def service(repo=DIToken("repository")):
            #
            if isinstance(parameter.default, DIToken):
                resolved[name] = self.resolve(parameter.default.name)
                continue

            if isinstance(parameter.default, Injector):
                resolved[name] = parameter.default(parameter.annotation)
                continue

            # Normal annotated dependency:
            #
            #     def service(repo: UserRepository):
            #
            # Only inject it if it has been registered.
            if (
                parameter.annotation is not Parameter.empty
                and parameter.annotation in self._type_registry
            ):
                resolved[name] = self.resolve(parameter.annotation)

        return resolved

    def _resolve_annotation(
        self,
        annotation: Any,
    ) -> Any:
        if annotation is Parameter.empty:
            return _NOT_RESOLVED

        if annotation not in self._type_registry:
            return _NOT_RESOLVED

        return self.resolve(annotation)


class _NotResolved:
    pass


_NOT_RESOLVED = _NotResolved()


# ============================================================================
# Flask current container
# ============================================================================


def _get_container() -> DIContainer:
    return DIContainer.current()


container: DIContainer = LocalProxy(
    _get_container,
    unbound_message="DIContainer is not registered",
)


# ============================================================================
# Convenience resolve function
# ============================================================================


def resolve(
    type_: type[T] | str,
    *args: Any,
    **kwargs: Any,
) -> T:
    return DIContainer.current().resolve(
        type_,
        *args,
        **kwargs,
    )


# ============================================================================
# Injected descriptor
# ============================================================================


class Injected:
    """
    Descriptor that resolves a dependency when accessed.

    Example:

        class UserService:

            repository: UserRepository = Injected()

    Accessing:

        service.repository

    resolves UserRepository from the current DI container.

    `cached=True` caches the resolved value per object instance.
    """

    def __init__(
        self,
        cached: bool = False,
    ):
        self.cached = cached
        self.name: str | None = None
        self.type: type | None = None

    def __set_name__(
        self,
        owner: type,
        name: str,
    ) -> None:
        self.name = name

        annotations = getattr(
            owner,
            "__annotations__",
            {},
        )

        self.type = annotations.get(name)

        if self.type is None:
            raise TypeError(
                f"Injected dependency '{owner.__name__}.{name}' "
                "must have a type annotation"
            )

    def __get__(
        self,
        instance: Any,
        owner: type | None = None,
    ) -> Any:
        if instance is None:
            return self

        if self.type is None:
            raise RuntimeError("Injected descriptor has not been initialized")

        if not self.cached:
            return resolve(self.type)

        # Cache belongs to the object instance, not the descriptor.
        cache = instance.__dict__.setdefault(
            "_qivo_injected",
            {},
        )

        if self.name not in cache:
            cache[self.name] = resolve(self.type)

        return cache[self.name]

    def __set__(
        self,
        instance: Any,
        value: Any,
    ) -> None:
        if self.name is None:
            raise RuntimeError("Injected descriptor has not been initialized")

        cache = instance.__dict__.setdefault(
            "_qivo_injected",
            {},
        )

        cache[self.name] = value

    def __delete__(
        self,
        instance: Any,
    ) -> None:
        if self.name is None:
            return

        cache = instance.__dict__.get("_qivo_injected")

        if cache is not None:
            cache.pop(self.name, None)


# ============================================================================
# @inject decorator
# ============================================================================


def inject(
    function: Callable[..., T],
) -> Callable[..., T]:
    """
    Automatically resolves dependencies from function parameters.

    Example:

        @inject
        def create_user(
            service: UserService,
        ):
            return service.create()

    Explicit arguments always override injected dependencies.
    """

    @wraps(function)
    def wrapper(
        *args: Any,
        **kwargs: Any,
    ) -> T:
        resolved = DIContainer.current().resolve_params(function)

        # Explicit arguments win.
        resolved.update(kwargs)

        return function(
            *args,
            **resolved,
        )

    return wrapper
