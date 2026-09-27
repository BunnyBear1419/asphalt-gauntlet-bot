"""Shared RSL language catalog and preference helpers.

The website and Discord bot use the same language codes. Preferences are stored
in the existing per-account web_user_preferences collection so the setting
follows a driver across the RSL website and Discord.
"""
from __future__ import annotations

from typing import Any

RSL_LANGUAGES = {
    "en": {"name": "English", "flag": "🇺🇸"},
    "zh-CN": {"name": "Mandarin Chinese", "flag": "🇨🇳"},
    "es": {"name": "Spanish", "flag": "🇪🇸"},
    "ar": {"name": "Arabic", "flag": "🇸🇦"},
    "pt": {"name": "Portuguese", "flag": "🇧🇷"},
    "ru": {"name": "Russian", "flag": "🇷🇺"},
    "fr": {"name": "French", "flag": "🇫🇷"},
    "de": {"name": "German", "flag": "🇩🇪"},
    "ms": {"name": "Malay / Bahasa Melayu", "flag": "🇲🇾"},
    "hi": {"name": "Hindi", "flag": "🇮🇳"},
    "ja": {"name": "Japanese", "flag": "🇯🇵"},
    "ko": {"name": "Korean", "flag": "🇰🇷"},
    "it": {"name": "Italian", "flag": "🇮🇹"},
    "nl": {"name": "Dutch", "flag": "🇳🇱"},
    "tr": {"name": "Turkish", "flag": "🇹🇷"},
    "pl": {"name": "Polish", "flag": "🇵🇱"},
    "vi": {"name": "Vietnamese", "flag": "🇻🇳"},
    "th": {"name": "Thai", "flag": "🇹🇭"},
    "id": {"name": "Indonesian", "flag": "🇮🇩"},
    "uk": {"name": "Ukrainian", "flag": "🇺🇦"},
}
DEFAULT_LANGUAGE = "en"
FLAG_TO_LANGUAGE = {item["flag"]: code for code, item in RSL_LANGUAGES.items()}
LANGUAGE_CODES = tuple(RSL_LANGUAGES)


def normalize_language(value: Any) -> str:
    value = str(value or "").strip()
    return value if value in RSL_LANGUAGES else DEFAULT_LANGUAGE


def language_name(code: Any) -> str:
    return RSL_LANGUAGES[normalize_language(code)]["name"]


def language_flag(code: Any) -> str:
    return RSL_LANGUAGES[normalize_language(code)]["flag"]


async def get_user_language(bot: Any, user_id: int | str) -> str:
    """Read the shared website/Discord account preference."""
    db = getattr(bot, "db", None)
    if db is None:
        return DEFAULT_LANGUAGE
    try:
        row = await db.web_user_preferences.find_one({"_id": str(user_id)}) or {}
        return normalize_language(row.get("language"))
    except Exception:
        return DEFAULT_LANGUAGE


async def set_user_language(bot: Any, user_id: int | str, language: str) -> str:
    """Persist a validated language in the shared account preference document."""
    language = normalize_language(language)
    db = getattr(bot, "db", None)
    if db is None:
        raise RuntimeError("RSL language preferences require the database")
    await db.web_user_preferences.update_one(
        {"_id": str(user_id)},
        {"$set": {"language": language, "updated_at": __import__("time").time()}},
        upsert=True,
    )
    return language
