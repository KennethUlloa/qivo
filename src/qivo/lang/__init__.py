import json
from typing import Callable, Union

from flask import Flask

from qivo.ext.base import BaseExtension


class TranslationDict(dict):
    def __getitem__(self, key):
        if not self.__contains__(key):
            return "{%s}" % key

        return super().__getitem__(key)


def plain_dict(data: dict, preffix: str = ""):
    plain = {}

    for key, value in data.items():
        if isinstance(value, str):
            plain[preffix + key] = value
        elif isinstance(value, dict):
            children = plain_dict(value, preffix + f"{key}.")
            plain.update(children)
        else:
            raise ValueError(
                f"'{key}' must be of type str or dict, got {type(value).__name__}"
            )

    return plain


class Lang(BaseExtension):
    name = "qivo.lang"
    def __init__(
        self,
        app: Flask = None,
        lang: str = "en",
        template_global_name: str = "t_",
        request_lang_resolver: Callable[[], str] = None,
    ):
        self._translations: dict[str, dict[str, str]] = dict()
        self._template_handler_name = template_global_name or "t_"
        self._lang = lang
        self._request_lang_resolver = request_lang_resolver
        super().__init__(app)

    def setup(self, app):
        name = self._template_handler_name
        @app.template_global(name=name)
        def _t_handler(key: str, **ctx):
            return self.request_translate(key, **ctx)

    def load_translations(
        self, path_or_dict: Union[dict, str], lang: str = None, encoding: str = "utf-8"
    ):
        translations = {}
        if isinstance(path_or_dict, str):
            with open(path_or_dict, "r", encoding=encoding) as f:
                translations = self.prepare_translations(json.load(f))
        else:
            translations = self.prepare_translations(path_or_dict)

        self._translations[lang or self._lang] = translations

    def prepare_translations(self, data: dict) -> dict:
        if not isinstance(data, dict):
            raise ValueError(
                f"Translations must be an instance of dict, got {type(data).__name__}"
            )

        return plain_dict(data)

    def translate(self, lang: str, key: str, **ctx) -> str:
        _lang = lang or self._lang
        if _lang in self._translations:
            translations = self._translations[_lang]
            if key in translations:
                return translations[key].format_map(TranslationDict(ctx))
            if self._lang != _lang and self._lang in self._translations:
                translations = self._translations[self._lang]
                if key in translations:
                    return translations[key].format_map(TranslationDict(ctx))
                return key
            return key
        translations = self._translations.get(self._lang, {})

        if key not in translations:
            return key

        return translations[key].format_map(TranslationDict(ctx))

    def request_translate(self, key: str, **ctx):
        return self.translate(self.get_current_request_lang(), key, **ctx)

    def get_current_request_lang(self):
        if callable(self._request_lang_resolver):
            return self._request_lang_resolver() or self._lang

        return self._lang


def t_(key: str, **ctx):
    return Lang.current().request_translate(key, **ctx)
