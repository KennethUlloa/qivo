from qivo.serialization import SerializationRegistry, Serializer


def test_recursive_subclass_check_does_not_break_serialization():
    class RecursiveMeta(type):
        def __subclasscheck__(cls, subclass):
            return issubclass(subclass, cls)

    class RegisteredBase(metaclass=RecursiveMeta):
        pass

    class Value:
        pass

    registry = SerializationRegistry()
    registry.register(RegisteredBase, lambda value: "serialized")

    value = Value()

    assert Serializer(registry).serialize(value) is value


def test_object_serialization_uses_only_its_explicit_representation():
    class Node:
        def __init__(self):
            self.name = "root"
            self.related = self

        def to_dict(self):
            return {"name": self.name}

    node = Node()

    assert Serializer().serialize(node) == {"name": "root"}


def test_objects_without_explicit_representation_are_not_introspected():
    class ObjectWithRecursiveProperty:
        @property
        def related(self):
            return self

    value = ObjectWithRecursiveProperty()

    assert Serializer().serialize(value) is value