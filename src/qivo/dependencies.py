from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Mapping, Type, Union
from inspect import signature
from functools import wraps

if TYPE_CHECKING:
    from qivo import Qivo


@dataclass
class DIToken:
    name: str


class _Uncalled:
    pass


class CacheInfo:
    time: int
    last_call: datetime = None
    last_result: Any = _Uncalled

    def __init__(self, time: int, last_call: datetime, last_result: Any):
        self.time = time
        self.last_call = last_call
        self.last_result = last_result


def cached_func(f, cache_time: int):
    setattr(
        f,
        "__cache__",
        CacheInfo(time=cache_time, last_call=None, last_result=_Uncalled),
    )

    def _cached_resolver(*args, **kwargs):
        cache_info: CacheInfo = getattr(f, "__cache__")

        if cache_info.last_call is None:
            cache_info.last_call = datetime.now()
            last_result = f(*args, **kwargs)
            cache_info.last_result = last_result
            return last_result

        if (datetime.now() - cache_info.last_call).total_seconds() > cache_info.time:
            cache_info.last_call = datetime.now()
            last_result = f(*args, **kwargs)
            cache_info.last_result = last_result
            return last_result

        return cache_info.last_result

    return _cached_resolver


class DIContainer:
    __type_registry: dict[Type, Callable]
    __token_registry: dict[str, Callable]

    def __init__(self):
        self.__type_registry = {}
        self.__token_registry = {}

    def register(
        self,
        type_: Union[Type, str],
        replacement: Callable[..., Any] = None,
        cached: int = None,
    ):
        is_token = isinstance(type_, str)

        if is_token:
            assert replacement is not None

        to_save = replacement if is_token else replacement or type_

        if cached is not None and cached > 0:
            original = to_save
            to_save = cached_func(original, cached)

        if is_token:
            self.__token_registry[type_] = to_save
        else:
            self.__type_registry[type_] = to_save

    def resolve(self, type_: Union[Type, str], *args, **kwargs):
        target_type = (
            self.__token_registry.get(type_)
            if isinstance(type_, str)
            else self.__type_registry.get(type_)
        )

        if target_type is None:
            raise ValueError(f"Could not resolve type: {type_}")

        resolved_kwargs = self.resolve_params(target_type)
        resolved_kwargs.update(kwargs)

        return target_type(*args, **resolved_kwargs)

    def resolve_params(self, f: Callable):
        resolved_kwargs = {}
        for name, param in signature(f).parameters.items():
            param_type = param.annotation

            if isinstance(param.default, DIToken):
                resolved_kwargs[name] = self.resolve(param.default.name)
                continue

            if param_type in self.__type_registry:
                resolved_kwargs[name] = self.resolve(param_type)
                continue

        return resolved_kwargs


class DependencyInjectionExtension:
    def wrap_view(
        self,
        app: Qivo,
        view_func: Callable,
        *,
        options: Mapping[str, Any],
    ) -> Callable:
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            injected = app.container.resolve_params(view_func)
            injected.update(kwargs)
            return view_func(*args, **injected)

        return wrapper
