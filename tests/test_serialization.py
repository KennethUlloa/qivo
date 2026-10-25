from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum, StrEnum

from flask import Flask, jsonify
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from qivo.serializer import Extension, ObjectJSONEncoder


class Status(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class Level(IntEnum):
    LOW = 1


class Priority(Enum):
    HIGH = "high"


@dataclass
class Address:
    street: str
    zipcode: int


@dataclass
class Person:
    name: str
    age: int
    address: Address
    created_at: datetime
    status: Status
    level: Level
    tags: list[str] = field(default_factory=list)

    def to_model(self):
        return {
            "name": self.name,
            "age": self.age,
            "date": self.created_at
        }


class Account:
    def __init__(self, id, balance, card, created_date):
        self.id = id
        self.balance = balance
        self.card = card
        self.created_date = created_date

    def to_dict(self):
        return {
            "id": self.id,
            "balance": self.balance,
            "card": self.card,
            "created_at": self.created_date,
            "__type__": "object",
        }


class Model(DeclarativeBase):
    pass

class User(Model):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column()
    birthdate: Mapped[datetime] = mapped_column()
    status: Mapped[Status] = mapped_column()


def test_dataclass_serialization(app: Flask):
    app.json = ObjectJSONEncoder(app)

    _date = datetime(2025, 1, 1, 12, 0, 0)
    target_iso = "2025-01-01T12:00:00"

    @app.route("/test")
    def test():
        return jsonify(
            Person(
                name="Test",
                age=34,
                address=Address(street="123", zipcode=123),
                created_at=_date,
                tags=["hello", "world"],
                level=Level.LOW,
                status=Status.ACTIVE,
            )
        )

    client = app.test_client()
    res = client.get("/test")

    assert res.json == {
        "name": "Test",
        "age": 34,
        "address": {"street": "123", "zipcode": 123},
        "tags": ["hello", "world"],
        "created_at": target_iso,
        "level": 1,
        "status": "active",
    }


def test_to_dict_serialization(app: Flask):
    app.json = ObjectJSONEncoder(app)

    created_date = datetime(2025, 1, 1, 12, 0, 0)
    target_iso = "2025-01-01T12:00:00"

    @app.route("/test")
    def test():
        return jsonify(Account(1, 200, "testing", created_date))
    
    client = app.test_client()
    res = client.get("/test")

    assert res.json == {
        "id": 1,
        "balance": 200,
        "card": "testing",
        "created_at": target_iso,
        "__type__": "object"
    }


def test_model_serialization(app: Flask):
    app.json = ObjectJSONEncoder(app)

    created_date = datetime(2025, 1, 1, 12, 0, 0)
    target_iso = "2025-01-01T12:00:00"

    @app.route("/test")
    def test():
        return jsonify(User(
            id=1,
            name="Admin",
            birthdate=created_date,
            status=Status.ACTIVE
        ))
    
    client = app.test_client()
    res = client.get("/test")

    assert res.json == {
        "id": 1,
        "name": "Admin",
        "birthdate": target_iso,
        "status": "active"
    }


def test_serializer_extension(app: Flask):
    class Serializer(Extension):
        def matches(self, obj):
            return hasattr(obj, "to_model") and callable(getattr(obj, "to_model"))

        def serialize(self, obj):
            return obj.to_model()

    app.json = ObjectJSONEncoder(app, extension=Serializer())

    _date = datetime(2025, 1, 1, 12, 0, 0)
    target_iso = "2025-01-01T12:00:00"

    @app.route("/test")
    def test():
        return jsonify(
            Person(
                name="Test",
                age=34,
                address=Address(street="123", zipcode=123),
                created_at=_date,
                tags=["hello", "world"],
                level=Level.LOW,
                status=Status.ACTIVE,
            )
        )

    client = app.test_client()
    res = client.get("/test")

    assert res.json == {
        "name": "Test",
        "age": 34,
        "date": target_iso
    }