from enum import Enum
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID
from dataclasses import is_dataclass, asdict

from flask import Flask
from flask.json.provider import DefaultJSONProvider
from sqlalchemy.orm import DeclarativeBase
from qivo.sql.utils import to_dict as sql_to_dict


class ObjectJSONEncoder(DefaultJSONProvider):
    def __init__(self, app: Flask, inner_methods: list = []):
        super().__init__(app)
        self.inner_methods = inner_methods


    def default(self, value: Any) -> Any:
        if isinstance(value, (datetime, date, time)):
            return value.isoformat()

        if isinstance(value, (UUID, Decimal)):
            return str(value)

        if isinstance(value, Enum):
            return value.value

        to_dict = getattr(value, "to_dict", None)

        if callable(to_dict):
            return to_dict()

        if self.inner_methods:
            for method in self.inner_methods:
                if hasattr(value, method) and callable(getattr(value, method)):
                    return getattr(value, method)()

        if is_dataclass(value):
            return asdict(value)

        if isinstance(value, DeclarativeBase):
            return sql_to_dict(value)

        return super().default(value)
