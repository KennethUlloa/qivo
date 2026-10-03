from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from functools import wraps
from typing import Any, Union
from uuid import UUID

from flask import Flask, current_app

from qivo.ext.base import BaseExtension
from qivo.contracts.serializer import Serializable, SerializerDefinition


class Serializer(BaseExtension):
    name = "qivo.serializer"

    def __init__(self, app: Flask | None = None):
        super().__init__(app)
        self.serializers: list[SerializerDefinition] = []

    def add(self, serializer: SerializerDefinition):
        self.serializers.append(serializer)

    def serialize(self, value: Union[Serializable, Any]) -> Any:
        if value is None:
            return None

        for serializer in self.serializers:
            if serializer.match(value):
                return serializer.serialize(value)

        to_dict = getattr(value, "to_dict", None)

        if callable(to_dict):
            return self.serialize(to_dict())

        if isinstance(value, dict):
            return {
                self.serialize(key): self.serialize(item) for key, item in value.items()
            }

        if is_dataclass(value):
            return self.serialize(asdict(value))

        if isinstance(value, (list, tuple, set, frozenset)):
            return [self.serialize(item) for item in value]

        if isinstance(value, Enum):
            return self.serialize(value.value)

        if isinstance(value, (datetime, date, time)):
            return value.isoformat()

        if isinstance(value, (UUID, Decimal)):
            return str(value)

        return value


def serializer() -> Serializer:
    return Serializer.current()


def serialized(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return serializer().serialize(f(*args, **kwargs))

    return wrapper
