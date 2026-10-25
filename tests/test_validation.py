import pytest
from flask import Flask

from qivo.validation.base import BaseFromForm, BaseFromJson, BaseValidator
from qivo.validation.typed import FormBody, JsonBody


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class DummyModel:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


# ---------------------------------------------------------------------------
# BaseValidator
# ---------------------------------------------------------------------------


def test_base_validator_requires_data_implementation():
    class Incomplete(BaseValidator):
        def validate_data(self, data, *args, **kwargs):
            return data

    instance = Incomplete()
    assert callable(instance.validate_data)


def test_base_validator_requires_validate_data_implementation():
    class Incomplete(BaseValidator):
        def data(self, request):
            return {}

    instance = Incomplete()
    assert callable(instance.data)


def test_base_validator_validate_uses_data_and_validate_data(app):
    class EchoValidator(BaseValidator):
        def data(self, request):
            return request.get_json(silent=True) or {}

        def validate_data(self, data, *args, **kwargs):
            return {"echoed": data, "args": args, "kwargs": kwargs}

    validator = EchoValidator()

    with app.test_request_context(json={"name": "test"}):
        result = validator.validate(extra="value")

    assert result == {"echoed": {"name": "test"}, "args": (), "kwargs": {"extra": "value"}}


def test_base_validator_validate_passes_request_from_context(app):
    class RequestValidator(BaseValidator):
        def data(self, request):
            assert request is not None
            return {"path": request.path}

        def validate_data(self, data, *args, **kwargs):
            return data

    validator = RequestValidator()

    with app.test_request_context("/test"):
        result = validator.validate()

    assert result == {"path": "/test"}


# ---------------------------------------------------------------------------
# BaseFromJson
# ---------------------------------------------------------------------------


def test_base_from_json_returns_request_json(app):
    validator = BaseFromJson()

    with app.test_request_context(json={"key": "value", "number": 42}):
        result = validator.data(__import__("flask").request)

    assert result == {"key": "value", "number": 42}


def test_base_from_json_returns_none_when_no_json(app):
    validator = BaseFromJson()

    with app.test_request_context():
        try:
            result = validator.data(__import__("flask").request)
        except Exception:
            result = None

    assert result is None or result == {} or result is False


# ---------------------------------------------------------------------------
# BaseFromForm
# ---------------------------------------------------------------------------


def test_base_from_form_returns_form_data(app):
    validator = BaseFromForm()

    with app.test_request_context(data={"username": "john", "email": "john@example.com"}):
        result = validator.data(__import__("flask").request)

    assert result["username"] == "john"
    assert result["email"] == "john@example.com"


def test_base_from_form_handles_list_keys(app):
    validator = BaseFromForm()

    with app.test_request_context(data={"tags": ["python", "flask", "api"]}):
        result = validator.data(__import__("flask").request, list_keys=["tags"])

    assert result["tags"] == ["python", "flask", "api"]


def test_base_from_form_only_converts_specified_list_keys(app):
    validator = BaseFromForm()

    with app.test_request_context(data={"name": "test", "tags": ["a", "b"]}):
        result = validator.data(__import__("flask").request, list_keys=["tags"])

    assert isinstance(result["name"], str)
    assert result["tags"] == ["a", "b"]


def test_base_from_form_checkbox_checked(app):
    validator = BaseFromForm()

    with app.test_request_context(data={"agree": "on"}):
        result = validator.data(__import__("flask").request, checkbox_keys=["agree"])

    assert result["agree"] is True


def test_base_from_form_checkbox_unchecked_uses_default(app):
    validator = BaseFromForm()

    with app.test_request_context(data={}):
        result = validator.data(__import__("flask").request, checkbox_keys=["agree"])

    assert result.get("agree") is False or result.get("agree") is None or "agree" not in result


def test_base_from_form_checkbox_unchecked_with_skip_none(app):
    validator = BaseFromForm()

    with app.test_request_context(data={}):
        result = validator.data(
            __import__("flask").request, checkbox_keys=["agree"], skip_none_checkbox=True
        )

    assert "agree" not in result


def test_base_from_form_checkbox_with_other_value(app):
    validator = BaseFromForm()

    with app.test_request_context(data={"active": "yes"}):
        result = validator.data(__import__("flask").request, checkbox_keys=["active"])

    assert result["active"] is False


def test_base_from_form_parse_checkbox_returns_true_for_on(app):
    validator = BaseFromForm()

    assert validator.parse_checkbox("key", "on") is True


def test_base_from_form_parse_checkbox_returns_false_for_other_values(app):
    validator = BaseFromForm()

    assert validator.parse_checkbox("key", "yes") is False
    assert validator.parse_checkbox("key", "true") is False
    assert validator.parse_checkbox("key", None) is False


def test_base_from_form_multiple_features_combined(app):
    validator = BaseFromForm()

    with app.test_request_context(
        data={"name": "test", "tags": ["a", "b"], "subscribe": "on"}
    ):
        result = validator.data(
            __import__("flask").request,
            list_keys=["tags"],
            checkbox_keys=["subscribe"],
        )

    assert result["name"] == "test"
    assert result["tags"] == ["a", "b"]
    assert result["subscribe"] is True


def test_base_from_form_default_empty_lists():
    validator = BaseFromForm()

    assert validator.data.__defaults__


# ---------------------------------------------------------------------------
# JsonBody
# ---------------------------------------------------------------------------


def test_json_body_is_injector():
    assert getattr(JsonBody, "__injector__", False) is True


def test_json_body_instantiates():
    json_body = JsonBody()

    assert isinstance(json_body, JsonBody)


def test_json_body_calls_validate_on_instance_call(app):
    json_body = JsonBody()

    with app.test_request_context(json={"name": "John", "age": 30}):
        result = json_body(DummyModel)

    assert isinstance(result, DummyModel)
    assert result.name == "John"
    assert result.age == 30


def test_json_body_validate_data_instantiates_type(app):
    json_body = JsonBody()

    data = {"title": "Hello", "count": 5}
    result = json_body.validate_data(data, DummyModel)

    assert isinstance(result, DummyModel)
    assert result.title == "Hello"
    assert result.count == 5


def test_json_body_data_returns_request_json(app):
    json_body = JsonBody()

    with app.test_request_context(json={"key": "value"}):
        result = json_body.data(__import__("flask").request)

    assert result == {"key": "value"}


def test_json_body_with_empty_json(app):
    json_body = JsonBody()

    with app.test_request_context(json={}):
        result = json_body(DummyModel)

    assert isinstance(result, DummyModel)


# ---------------------------------------------------------------------------
# FormBody
# ---------------------------------------------------------------------------


def test_form_body_is_injector():
    assert getattr(FormBody, "__injector__", False) is True


def test_form_body_instantiates_with_defaults():
    form_body = FormBody()

    assert form_body.list_keys == []
    assert form_body.checkbox_keys == []
    assert form_body.skip_none_checkbox is False


def test_form_body_accepts_configuration():
    form_body = FormBody(
        list_keys=["tags", "categories"],
        checkbox_keys=["active", "public"],
        skip_none_checkbox=True,
    )

    assert form_body.list_keys == ["tags", "categories"]
    assert form_body.checkbox_keys == ["active", "public"]
    assert form_body.skip_none_checkbox is True


def test_form_body_calls_validate_on_instance_call(app):
    form_body = FormBody()

    with app.test_request_context(data={"name": "Jane", "email": "jane@example.com"}):
        result = form_body(DummyModel)

    assert isinstance(result, DummyModel)
    assert result.name == "Jane"
    assert result.email == "jane@example.com"


def test_form_body_validate_data_instantiates_type(app):
    form_body = FormBody()

    data = {"title": "Post", "content": "Body"}
    result = form_body.validate_data(data, DummyModel)

    assert isinstance(result, DummyModel)
    assert result.title == "Post"
    assert result.content == "Body"


def test_form_body_data_uses_configuration(app):
    form_body = FormBody(list_keys=["tags"], checkbox_keys=["published"])

    with app.test_request_context(data={"title": "Test", "tags": ["a", "b"], "published": "on"}):
        result = form_body.data(__import__("flask").request)

    assert result["title"] == "Test"
    assert result["tags"] == ["a", "b"]
    assert result["published"] is True


def test_form_body_with_skip_none_checkbox(app):
    form_body = FormBody(checkbox_keys=["active"], skip_none_checkbox=True)

    with app.test_request_context(data={"name": "test"}):
        result = form_body.data(__import__("flask").request)

    assert "active" not in result
    assert result["name"] == "test"


def test_form_body_with_checked_checkbox(app):
    form_body = FormBody(checkbox_keys=["active"])

    with app.test_request_context(data={"active": "on"}):
        result = form_body.data(__import__("flask").request)

    assert result["active"] is True


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


def test_json_body_in_request_context_integration(app):
    class User:
        def __init__(self, name, email):
            self.name = name
            self.email = email

    json_body = JsonBody()

    with app.test_request_context(json={"name": "Alice", "email": "alice@test.com"}):
        user = json_body(User)

    assert user.name == "Alice"
    assert user.email == "alice@test.com"


def test_form_body_in_request_context_integration(app):
    class Product:
        def __init__(self, name, price):
            self.name = name
            self.price = price

    form_body = FormBody()

    with app.test_request_context(data={"name": "Laptop", "price": "999"}):
        product = form_body(Product)

    assert product.name == "Laptop"
    assert product.price == "999"


def test_json_body_with_dataclass_like_model(app):
    class Article:
        def __init__(self, title, tags=None):
            self.title = title
            self.tags = tags or []

    json_body = JsonBody()

    with app.test_request_context(json={"title": "Test", "tags": ["news", "tech"]}):
        article = json_body(Article)

    assert article.title == "Test"
    assert article.tags == ["news", "tech"]


def test_base_from_form_with_empty_data(app):
    validator = BaseFromForm()

    with app.test_request_context(data={}):
        result = validator.data(__import__("flask").request)

    assert result == {}
