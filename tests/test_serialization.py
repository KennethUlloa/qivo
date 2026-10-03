from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal
from enum import Enum, IntEnum, StrEnum
from uuid import UUID

import pytest

from qivo.ext.serialization import Serializer, serialized


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
    tags: list[str] = field(default_factory=list)


class Account:
    def __init__(self, id, balance):
        self.id = id
        self.balance = balance

    def to_dict(self):
        return {"id": self.id, "balance": self.balance}


@pytest.fixture
def serializer(app):
    return Serializer(app)


# ---------------------------------------------------------------------------
# Scalars and containers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["text", 1, 1.5, True, None])
def test_scalars_are_returned_as_is(serializer, value):
    assert serializer.serialize(value) == value


def test_none_is_serialized(serializer):
    assert serializer.serialize(None) is None


def test_dicts_are_serialized_recursively(serializer):
    value = {"name": "Ada", "meta": {"created_at": datetime(2024, 1, 2, 3, 4, 5)}}

    assert serializer.serialize(value) == {
        "name": "Ada",
        "meta": {"created_at": "2024-01-02T03:04:05"},
    }


def test_dict_keys_are_serialized(serializer):
    identifier = UUID("12345678-1234-5678-1234-567812345678")

    assert serializer.serialize({identifier: 1}) == {str(identifier): 1}


def test_tuples_and_sets_become_lists(serializer):
    assert serializer.serialize((1, 2)) == [1, 2]
    assert serializer.serialize(frozenset({3})) == [3]
    assert sorted(serializer.serialize({1, 2})) == [1, 2]


def test_nested_containers(serializer):
    assert serializer.serialize([{"values": (1, 2)}]) == [{"values": [1, 2]}]


# ---------------------------------------------------------------------------
# Objects
# ---------------------------------------------------------------------------


def test_dataclasses_are_converted(serializer):
    person = Person(
        name="Ada",
        age=36,
        address=Address(street="Main", zipcode=12345),
        created_at=datetime(2024, 1, 2, 3, 4, 5),
        tags=["math"],
    )

    assert serializer.serialize(person) == {
        "name": "Ada",
        "age": 36,
        "address": {"street": "Main", "zipcode": 12345},
        "created_at": "2024-01-02T03:04:05",
        "tags": ["math"],
    }


def test_to_dict_objects_are_serialized(serializer):
    account = Account(id=UUID("12345678-1234-5678-1234-567812345678"), balance=Decimal("10.50"))

    assert serializer.serialize(account) == {
        "id": "12345678-1234-5678-1234-567812345678",
        "balance": "10.50",
    }


def test_objects_without_to_dict_are_returned_as_is(serializer):
    class Plain:
        pass

    plain = Plain()

    assert serializer.serialize(plain) is plain


def test_enums_are_serialized_by_value(serializer):
    assert serializer.serialize(Status.ACTIVE) == "active"
    assert serializer.serialize(Level.LOW) == 1
    assert serializer.serialize(Priority.HIGH) == "high"


def test_enums_inside_containers(serializer):
    assert serializer.serialize([Status.ACTIVE, Status.INACTIVE]) == [
        "active",
        "inactive",
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05"),
        (
            datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
            "2024-01-02T03:04:05+00:00",
        ),
        (date(2024, 1, 2), "2024-01-02"),
        (time(3, 4, 5), "03:04:05"),
    ],
)
def test_temporal_values_use_isoformat(serializer, value, expected):
    assert serializer.serialize(value) == expected


def test_uuid_and_decimal_become_strings(serializer):
    identifier = UUID("12345678-1234-5678-1234-567812345678")

    assert serializer.serialize(identifier) == str(identifier)
    assert serializer.serialize(Decimal("3.14")) == "3.14"


# ---------------------------------------------------------------------------
# Custom serializers
# ---------------------------------------------------------------------------


def test_custom_serializer_takes_precedence(serializer):
    class AccountSerializer:
        def match(self, value):
            return isinstance(value, Account)

        def serialize(self, value):
            return {"id": value.id, "currency": "EUR"}

    serializer.add(AccountSerializer())

    assert serializer.serialize(Account(id=1, balance=Decimal("1"))) == {
        "id": 1,
        "currency": "EUR",
    }


def test_only_the_first_matching_custom_serializer_is_used(serializer):
    class UpperSerializer:
        def match(self, value):
            return isinstance(value, str)

        def serialize(self, value):
            return value.upper()

    class ExclaimSerializer:
        def match(self, value):
            return isinstance(value, str)

        def serialize(self, value):
            return value + "!"

    serializer.add(UpperSerializer())
    serializer.add(ExclaimSerializer())

    assert serializer.serialize("hello") == "HELLO"


def test_custom_serializers_apply_to_nested_values(serializer):
    class AccountSerializer:
        def match(self, value):
            return isinstance(value, Account)

        def serialize(self, value):
            return value.id

    serializer.add(AccountSerializer())

    assert serializer.serialize({"accounts": [Account(id=1, balance=0)]}) == {
        "accounts": [1]
    }


# ---------------------------------------------------------------------------
# Flask integration
# ---------------------------------------------------------------------------


def test_serializer_current_returns_the_attached_instance(app, serializer):
    with app.app_context():
        assert Serializer.current() is serializer


def test_serializer_current_requires_an_app_context(serializer):
    with pytest.raises(RuntimeError):
        Serializer.current()


def test_serialized_decorator(app, serializer):
    @serialized
    def handler():
        return Person(
            name="Ada",
            age=36,
            address=Address(street="Main", zipcode=12345),
            created_at=datetime(2024, 1, 2, 3, 4, 5),
        )

    with app.app_context():
        assert handler() == {
            "name": "Ada",
            "age": 36,
            "address": {"street": "Main", "zipcode": 12345},
            "created_at": "2024-01-02T03:04:05",
            "tags": [],
        }


def test_serialized_decorator_preserves_the_function_metadata(serializer):
    @serialized
    def handler():
        """Docstring."""

    assert handler.__name__ == "handler"
    assert handler.__doc__ == "Docstring."


def test_serialized_in_a_flask_view(app, serializer):
    @app.get("/accounts")
    @serialized
    def index():
        return [Account(id=1, balance=Decimal("9.99"))]

    client = app.test_client()

    assert client.get("/accounts").json == [{"id": 1, "balance": "9.99"}]