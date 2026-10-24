from typing import Any, Self, Type, Union

from flask import g


class GField:
    def __init__(
        self,
        cls: Type = None,
        *,
        strict_type: bool = False,
        default: Any = None,
        nullable: bool = True,
    ):
        self.name = None
        self._strict_type = strict_type
        self.default = default
        self.type = cls
        self.nullable = nullable

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name
        annotation = owner.__annotations__.get(name)

        if self._strict_type and self.type is None and annotation is None:
            raise ValueError(
                f"The field {name} must have a type annotation or a type passed in the constructor if strict_type is enabled."
            )

        if self.type is None and annotation is not None:
            self.type = annotation

        if not self.nullable and self.default is None:
            raise ValueError(f"The field {name} is not nullable, provide a default value different than None")

    def __get__(
        self,
        instance: Any,
        owner: type | None = None,
    ) -> Union[Self, Any]:

        if instance is None:
            return self

        if not self.name:
            raise ValueError("Property name is not ready")

        return getattr(g, self.name, self.default)

    def __set__(
        self,
        instance: Any,
        value: Any,
    ) -> None:
        if self.name is None:
            raise RuntimeError("GField descriptor has not been initialized")

        if value is None:
            if not self.nullable:
                raise ValueError(f"{self.name} can not be None")

            setattr(g, self.name, value)
            return

        if self._strict_type:
            if self.type is None:
                raise ValueError(
                    f"The field {self.name} must have a type annotation or a type passed in the constructor if strict_type is enabled."
                )

            if not isinstance(value, self.type):
                raise ValueError(
                    f"Expected an instance of {self.type.__class__}, got {type(value).__class__}"
                )

        setattr(g, self.name, value)
