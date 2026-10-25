from typing import Type

from qivo.validation.base import BaseFromForm, BaseFromJson


class FormBody(BaseFromForm):
    __injector__ = True

    def __init__(
            self,
            list_keys: list[str] = None,
            checkbox_keys: list[str] = None,
            skip_none_checkbox: bool = False,
        ):
            self.list_keys = list_keys or []
            self.checkbox_keys = checkbox_keys or []
            self.skip_none_checkbox = skip_none_checkbox

    def __call__(self, type_: Type):
        return self.validate(type_=type_)

    def validate_data(self, data: dict, type_: Type):
        return type_(**data)

    def data(self, request):
         return super().data(request, self.list_keys, self.checkbox_keys, self.skip_none_checkbox)


class JsonBody(BaseFromJson):
    __injector__ = True

    def __call__(self, type_: Type):
        return self.validate(type_=type_)

    def validate_data(self, data: dict, type_: Type):
        return type_(**data)
