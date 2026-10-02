from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, Mapping, Protocol, Type, TypeVar, Union
from uuid import UUID

if TYPE_CHECKING:
    from qivo import Qivo

T = TypeVar("T")

type ValidTypes = Union[str, int, float, bool, dict, list, tuple, set, frozenset]


class Serializable(Protocol):

    def to_dict(self) -> ValidTypes: ...


class SerializationRegistry:
    def __init__(self):
        self._type_registry = {}

    def register(self, type_: Type[T], serializer: Callable[[T], ValidTypes]) -> None:
        self._type_registry[type_] = serializer

    def register_many(
        self, types: list[Type], serializer: Callable[[Type], ValidTypes]
    ):
        for type_ in types:
            self.register(type_, serializer)

    def __contains__(self, item_type: Type) -> bool:
        return item_type in self._type_registry or self._is_subclass(item_type)

    def _is_subclass(self, item_type):
        for type_ in self._type_registry:
            if self._matches_type(item_type, type_):
                return True

        return False

    @staticmethod
    def _matches_type(item_type: Type, registered_type: Type) -> bool:
        try:
            return issubclass(item_type, registered_type)
        except RecursionError:
            return False

    def _get_serializer(self, item_type: Type):
        if item_type in self._type_registry:
            return self._type_registry[item_type]

        for type_ in self._type_registry:
            if self._matches_type(item_type, type_):
                return self._type_registry[type_]

    def __getitem__(self, item_type: Type):
        return self._get_serializer(item_type)


class Serializer:
    def __init__(
        self,
        registry: SerializationRegistry | None = None,
    ):
        self.registry = registry or SerializationRegistry()

    def serialize(self, value: Union[Serializable, Any]) -> Any:
        if value is None:
            return None

        if self.registry is not None and type(value) in self.registry:
            return self.registry[type(value)](value)

        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            return self.serialize(to_dict())

        if isinstance(value, dict):
            return {
                self.serialize(key): self.serialize(item) for key, item in value.items()
            }

        if isinstance(value, (list, tuple, set, frozenset)):
            return [self.serialize(item) for item in value]

        if isinstance(value, Enum):
            return self.serialize(value.value)

        if isinstance(value, (datetime, date, time)):
            return value.isoformat()

        if isinstance(value, (UUID, Decimal)):
            return str(value)

        return value


class SerializationExtension:
    def wrap_view(
        self,
        app: Qivo,
        view_func: Callable,
        *,
        options: Mapping[str, Any],
    ) -> Callable:
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            return app._serialize_view_response(view_func(*args, **kwargs))

        return wrapper
