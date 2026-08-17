"""
Multilingual support.

Two kinds of text reach the user, and they are handled differently:

1. Text the platform itself writes (confirmations, refusals, field
   labels). These are fixed strings, translated once and stored in
   locales/*.json. They must be exact, so they are never machine
   translated at runtime.

2. Text the model writes (answers drawn from the knowledge base, short
   restatements of what was understood). The model is asked to write
   these directly in the user's language.

Field values extracted from a request are deliberately NOT translated.
An audit trail and a maintenance ticket must record what the person
actually wrote.
"""

import os
import json


LOCALES_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "locales"
)

DEFAULT_LANGUAGE = "en"


# Languages the interface has reviewed translations for. The agent can
# still converse in others; only these change the fixed interface text.
SUPPORTED_LANGUAGES = {
    "en": "English",
    "hi": "हिन्दी",
    "ta": "தமிழ்",
    "bn": "বাংলা",
    "es": "Español",
    "fr": "Français"
}


_CATALOGUE = {}


def _load(language):
    """
    Load one locale file, falling back to English if it is missing.
    """

    path = os.path.join(LOCALES_DIR, f"{language}.json")

    if not os.path.isfile(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    except (OSError, json.JSONDecodeError) as error:
        print("LOCALE ERROR:", language, error)
        return {}


def catalogue(language):
    """
    Return the cached string table for a language.
    """

    language = normalize(language)

    if language not in _CATALOGUE:
        _CATALOGUE[language] = _load(language)

    return _CATALOGUE[language]


def normalize(language):
    """
    Reduce a language tag to a supported code.
    """

    if not language:
        return DEFAULT_LANGUAGE

    code = str(language).strip().lower().replace("_", "-").split("-")[0]

    return code if code in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def translate(key, language=DEFAULT_LANGUAGE, **values):
    """
    Look up a fixed interface string.

    Falls back to English, then to the key itself, so a missing
    translation degrades to something readable rather than blank.
    """

    language = normalize(language)

    text = catalogue(language).get(key)

    if text is None:
        text = catalogue(DEFAULT_LANGUAGE).get(key, key)

    if values:
        try:
            return text.format(**values)
        except (KeyError, IndexError):
            return text

    return text


def field_label(field, language=DEFAULT_LANGUAGE):
    """
    Translate a request field name for display.
    """

    return translate(f"field.{field}", language)


def language_name(language):
    """
    Human readable name for a language code.
    """

    return SUPPORTED_LANGUAGES.get(
        normalize(language),
        SUPPORTED_LANGUAGES[DEFAULT_LANGUAGE]
    )
