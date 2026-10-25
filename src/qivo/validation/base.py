from abc import abstractmethod
from typing import Any

from flask import Request, request


class BaseValidator:
    @abstractmethod
    def data(self, request: Request) -> Any:
        raise NotImplementedError()

    @abstractmethod
    def validate_data(self, data: Any, *args, **kwargs) -> Any:
        raise NotImplementedError()

    def validate(self, *args, **kwargs):
        return self.validate_data(self.data(request), *args, **kwargs)


class BaseFromJson(BaseValidator):
    def data(self, request: Request) -> dict:
        return request.get_json()


class BaseFromForm(BaseValidator):
    def data(self, request: Request, list_keys: list[str] = [], checkbox_keys: list[str] = [], skip_none_checkbox: bool = False) -> dict:
        data = dict(request.form)

        for key in list_keys:
            if key in request.form:
                data[key] = request.form.getlist(key)

        for key in checkbox_keys:
            value = request.form.get(key, None)
            if value is None and skip_none_checkbox:
                continue
            data[key] = self.parse_checkbox(key, value)

        return data

    def parse_checkbox(self, key: str, value: Any) -> Any:
        return value == "on"
