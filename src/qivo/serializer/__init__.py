from enum import Enum
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Union
from uuid import UUID
from dataclasses import is_dataclass, asdict

from flask import Flask
from flask.json.provider import DefaultJSONProvider
from sqlalchemy.orm import DeclarativeBase
from qivo.sql.utils import to_dict as sql_to_dict


class Extension:
    def matches(self, obj: Any) -> bool:
        pass

    def serialize(self, obj: Any) -> Union[dict, list]:
        pass


class ObjectJSONEncoder(DefaultJSONProvider):
    def __init__(self, app: Flask, extension: Extension = None):
        super().__init__(app)
        self.extension = None
        if isinstance(extension, Extension):
            self.extension = extension

    def default(self, value: Any) -> Any:
        if self.extension and self.extension.matches(value):
            return self.extension.serialize(value)

        if isinstance(value, (datetime, date, time)):
            return value.isoformat()

        if isinstance(value, (UUID, Decimal)):
            return str(value)

        if isinstance(value, Enum):
            return value.value

        to_dict = getattr(value, "to_dict", None)

        if callable(to_dict):
            return to_dict()

        if is_dataclass(value):
            return asdict(value)

        if isinstance(value, DeclarativeBase):
            return sql_to_dict(value)

        return super().default(value)
