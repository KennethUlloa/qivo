from typing import Any, Protocol, Union

type ValidTypes = Union[str, int, float, bool, dict, list, tuple, set, frozenset]


class Serializable(Protocol):

    def to_dict(self) -> ValidTypes: ...


class SerializerDefinition(Protocol):
    def match(self, value: Any) -> bool: ...

    def serialize(self, value: Any) -> ValidTypes: ...
