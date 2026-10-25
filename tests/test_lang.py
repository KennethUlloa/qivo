import json

import pytest
from flask import Flask

from qivo.lang import Lang, TranslationDict, plain_dict, t_


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_translations():
    return {
        "greeting": "Hello",
        "messages": {
            "welcome": "Welcome, {name}!",
            "error": "Something went wrong",
        },
    }


# ---------------------------------------------------------------------------
# TranslationDict
# ---------------------------------------------------------------------------


def test_translation_dict_returns_formatted_key_when_missing():
    ctx = TranslationDict({})

    assert ctx["missing_key"] == "{missing_key}"


def test_translation_dict_returns_value_when_present():
    ctx = TranslationDict({"name": "Alice"})

    assert ctx["name"] == "Alice"


def test_translation_dict_works_with_format_map():
    template = "Hello {missing}, welcome {name}"
    result = template.format_map(TranslationDict({"name": "Bob"}))

    assert result == "Hello {missing}, welcome Bob"


# ---------------------------------------------------------------------------
# plain_dict
# ---------------------------------------------------------------------------


def test_plain_dict_flattens_nested_dictionaries():
    data = {
        "home": {
            "title": "Home",
            "subtitle": "Welcome",
        },
        "footer": {
            "about": "About us",
        },
    }

    result = plain_dict(data)

    assert result == {
        "home.title": "Home",
        "home.subtitle": "Welcome",
        "footer.about": "About us",
    }


def test_plain_dict_with_empty_prefix():
    data = {"hello": "world"}
    result = plain_dict(data, "")

    assert result == {"hello": "world"}


def test_plain_dict_uses_custom_prefix():
    data = {"greet": "hi"}
    result = plain_dict(data, "app.")

    assert result == {"app.greet": "hi"}


def test_plain_dict_handles_mixed_depths():
    data = {
        "level1": {
            "level2": {
                "level3": "deep value",
            },
            "simple": "flat",
        },
    }

    result = plain_dict(data)

    assert result["level1.level2.level3"] == "deep value"
    assert result["level1.simple"] == "flat"


def test_plain_dict_raises_for_non_string_non_dict_values():
    data = {"invalid": 123}

    with pytest.raises(ValueError, match="'invalid' must be of type str or dict"):
        plain_dict(data)


def test_plain_dict_raises_for_list_values():
    data = {"items": ["a", "b"]}

    with pytest.raises(ValueError, match="'items' must be of type str or dict"):
        plain_dict(data)


def test_plain_dict_raises_for_none_values():
    data = {"missing": None}

    with pytest.raises(ValueError, match="'missing' must be of type str or dict"):
        plain_dict(data)


# ---------------------------------------------------------------------------
# Lang extension
# ---------------------------------------------------------------------------


def test_lang_has_correct_name():
    lang = Lang()

    assert lang.name == "qivo.lang"


def test_lang_initializes_with_defaults():
    lang = Lang()

    assert lang._lang == "en"
    assert lang._template_handler_name == "t_"
    assert lang._request_lang_resolver is None
    assert lang._translations == {}


def test_lang_accepts_custom_parameters():
    def resolver():
        return "es"

    lang = Lang(lang="fr", template_global_name="translate", request_lang_resolver=resolver)

    assert lang._lang == "fr"
    assert lang._template_handler_name == "translate"
    assert lang._request_lang_resolver is resolver


def test_lang_registers_itself_on_the_app(app):
    lang = Lang(app)

    assert lang.app is app
    assert app.extensions["qivo.lang"] is lang


def test_lang_can_be_attached_to_multiple_apps():
    first = Flask("first")
    second = Flask("second")
    lang = Lang()

    lang.init_app(first)
    lang.init_app(second)

    assert first.extensions["qivo.lang"] is lang
    assert second.extensions["qivo.lang"] is lang
    assert lang.app is second


def test_lang_setup_registers_template_global(app):
    lang = Lang(app, template_global_name="t_")

    with app.app_context():
        assert "t_" in app.jinja_env.globals


def test_lang_setup_uses_custom_template_global_name(app):
    lang = Lang(app, template_global_name="translate")

    with app.app_context():
        assert "translate" in app.jinja_env.globals


def test_lang_setup_with_empty_name_uses_default(app):
    lang = Lang(app, template_global_name="")

    with app.app_context():
        assert "t_" in app.jinja_env.globals


# ---------------------------------------------------------------------------
# Loading translations
# ---------------------------------------------------------------------------


def test_load_translations_from_dict():
    lang = Lang()
    translations = make_translations()

    lang.load_translations(translations)

    assert lang._translations["en"] == {
        "greeting": "Hello",
        "messages.welcome": "Welcome, {name}!",
        "messages.error": "Something went wrong",
    }


def test_load_translations_for_specific_language():
    lang = Lang()
    translations = make_translations()

    lang.load_translations(translations, lang="es")

    assert "es" in lang._translations
    assert lang._translations["es"]["greeting"] == "Hello"


def test_load_translations_overwrites_existing_language():
    lang = Lang()
    lang.load_translations({"hello": "world"}, lang="en")
    lang.load_translations({"hello": "world2", "goodbye": "adios"}, lang="en")

    assert lang._translations["en"]["hello"] == "world2"
    assert lang._translations["en"]["goodbye"] == "adios"


def test_load_translations_from_json_file(tmp_path):
    lang = Lang()
    translations_file = tmp_path / "en.json"
    translations_file.write_text(
        json.dumps(make_translations()), encoding="utf-8"
    )

    lang.load_translations(str(translations_file))

    assert lang._translations["en"]["messages.welcome"] == "Welcome, {name}!"


def test_load_translations_from_json_file_with_custom_encoding(tmp_path):
    lang = Lang()
    translations_file = tmp_path / "es.json"
    content = {"saludo": "¡Hola!"}
    translations_file.write_text(json.dumps(content), encoding="utf-8")

    lang.load_translations(str(translations_file), lang="es", encoding="utf-8")

    assert lang._translations["es"]["saludo"] == "¡Hola!"


def test_load_translations_from_json_file_with_specific_language(tmp_path):
    lang = Lang()
    translations_file = tmp_path / "translations.json"
    translations_file.write_text(json.dumps({"hello": "bonjour"}), encoding="utf-8")

    lang.load_translations(str(translations_file), lang="fr")

    assert "fr" in lang._translations


def test_prepare_translations_validates_dict():
    lang = Lang()

    with pytest.raises(ValueError, match="Translations must be an instance of dict"):
        lang.prepare_translations([])


def test_prepare_translations_validates_none():
    lang = Lang()

    with pytest.raises(ValueError, match="Translations must be an instance of dict"):
        lang.prepare_translations(None)


def test_prepare_translations_returns_flat_dict():
    lang = Lang()
    result = lang.prepare_translations(make_translations())

    assert isinstance(result, dict)
    assert "greeting" in result
    assert "messages.welcome" in result


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------


def test_translate_returns_translated_string():
    lang = Lang()
    lang.load_translations({"hello": "Hola"}, lang="es")

    assert lang.translate("es", "hello") == "Hola"


def test_translate_uses_default_language_when_lang_is_none():
    lang = Lang(lang="fr")
    lang.load_translations({"hello": "Bonjour"}, lang="fr")

    assert lang.translate(None, "hello") == "Bonjour"


def test_translate_falls_back_to_default_language_when_key_not_in_requested_lang():
    lang = Lang(lang="en")
    lang.load_translations({"hello": "Hello"}, lang="en")
    lang.load_translations({"goodbye": "Adiós"}, lang="es")

    assert lang.translate("es", "hello") == "Hello"


def test_translate_falls_back_to_default_when_requested_language_not_loaded():
    lang = Lang(lang="en")
    lang.load_translations({"hello": "Hello"}, lang="en")

    assert lang.translate("de", "hello") == "Hello"


def test_translate_returns_key_when_not_found():
    lang = Lang(lang="en")
    lang.load_translations({"hello": "Hello"}, lang="en")

    assert lang.translate("en", "missing_key") == "missing_key"


def test_translate_formats_with_context():
    lang = Lang()
    lang.load_translations({"welcome": "Hello, {name}!"})

    result = lang.translate("en", "welcome", name="Alice")

    assert result == "Hello, Alice!"


def test_translate_formats_with_multiple_context_values():
    lang = Lang()
    lang.load_translations(
        {"greeting": "{greeting}, {name} from {city}!"}
    )

    result = lang.translate("en", "greeting", greeting="Hi", name="Bob", city="Paris")

    assert result == "Hi, Bob from Paris!"


def test_translate_handles_missing_context_keys_gracefully():
    lang = Lang()
    lang.load_translations({"message": "Hello {name}, your order {order_id} is ready"})

    result = lang.translate("en", "message", name="Alice")

    assert result == "Hello Alice, your order {order_id} is ready"


def test_translate_with_nested_keys():
    lang = Lang()
    lang.load_translations(
        {
            "user": {
                "profile": {
                    "title": "User Profile for {username}",
                }
            }
        }
    )

    result = lang.translate("en", "user.profile.title", username="john_doe")

    assert result == "User Profile for john_doe"


# ---------------------------------------------------------------------------
# Request language resolution
# ---------------------------------------------------------------------------


def test_get_current_request_lang_returns_default_when_no_resolver():
    lang = Lang(lang="fr")

    assert lang.get_current_request_lang() == "fr"


def test_get_current_request_lang_uses_resolver():
    lang = Lang(lang="en", request_lang_resolver=lambda: "es")

    assert lang.get_current_request_lang() == "es"


def test_get_current_request_lang_falls_back_to_default_when_resolver_returns_none():
    lang = Lang(lang="en", request_lang_resolver=lambda: None)

    assert lang.get_current_request_lang() == "en"


def test_get_current_request_lang_falls_back_to_default_when_resolver_returns_empty():
    lang = Lang(lang="de", request_lang_resolver=lambda: "")

    assert lang.get_current_request_lang() == "de"


def test_request_translate_uses_resolver_language(app):
    lang = Lang(app, lang="en", request_lang_resolver=lambda: "es")
    lang.load_translations({"hello": "Hola"}, lang="es")

    with app.app_context():
        result = lang.request_translate("hello")

    assert result == "Hola"


def test_request_translate_uses_default_language_without_resolver(app):
    lang = Lang(app, lang="fr")
    lang.load_translations({"hello": "Bonjour"}, lang="fr")

    with app.app_context():
        result = lang.request_translate("hello")

    assert result == "Bonjour"


# ---------------------------------------------------------------------------
# Template global function
# ---------------------------------------------------------------------------


def test_template_global_t_handler_registered(app):
    lang = Lang(app, template_global_name="t_")
    lang.load_translations({"hello": "Hola"}, lang="es")
    lang._request_lang_resolver = lambda: "es"

    with app.app_context():
        t_handler = app.jinja_env.globals["t_"]
        result = t_handler("hello")

    assert result == "Hola"


def test_template_global_uses_context(app):
    lang = Lang(app, template_global_name="tr")
    lang.load_translations({"welcome": "Welcome {name}"}, lang="en")

    with app.app_context():
        tr = app.jinja_env.globals["tr"]
        result = tr("welcome", name="Test")

    assert result == "Welcome Test"


# ---------------------------------------------------------------------------
# Global t_ function
# ---------------------------------------------------------------------------


def test_t_global_function_uses_current_lang(app):
    lang = Lang(app, lang="it")
    lang.load_translations({"hello": "Ciao"}, lang="it")

    with app.app_context():
        result = t_("hello")

    assert result == "Ciao"


def test_t_global_function_with_context(app):
    lang = Lang(app)
    lang.load_translations({"greet": "Hi {user}!"})

    with app.app_context():
        result = t_("greet", user="Charlie")

    assert result == "Hi Charlie!"


def test_t_global_function_uses_resolver(app):
    lang = Lang(app, lang="en", request_lang_resolver=lambda: "pt")
    lang.load_translations({"hello": "Olá"}, lang="pt")

    with app.app_context():
        result = t_("hello")

    assert result == "Olá"


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


def test_full_workflow_with_multiple_languages(app):
    lang = Lang(app, lang="en", template_global_name="t")
    lang.load_translations(
        {"nav": {"home": "Home", "about": "About"}}, lang="en"
    )
    lang.load_translations(
        {"nav": {"home": "Inicio", "about": "Acerca de"}}, lang="es"
    )

    lang._request_lang_resolver = lambda: "es"

    with app.app_context():
        assert lang.translate("es", "nav.home") == "Inicio"
        assert t_("nav.about") == "Acerca de"
        assert app.jinja_env.globals["t"]("nav.home") == "Inicio"


def test_translation_with_format_map_and_missing_keys(app):
    lang = Lang(app)
    lang.load_translations(
        {"message": "Hello {name}, {missing} items"}
    )

    with app.app_context():
        result = lang.translate("en", "message", name="User")
        assert result == "Hello User, {missing} items"
