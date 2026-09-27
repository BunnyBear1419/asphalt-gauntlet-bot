from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "ALU_Gauntlet" / "main.py"
LANG = ROOT / "ALU_Gauntlet" / "core" / "rsl_language.py"
COG = ROOT / "ALU_Gauntlet" / "cogs" / "translation.py"


def test_rsl_has_exact_shared_twenty_language_catalog():
    text = LANG.read_text(encoding="utf-8")
    for code in ("en","zh-CN","es","ar","pt","ru","fr","de","ms","hi","ja","ko","it","nl","tr","pl","vi","th","id","uk"):
        assert f'"{code}":' in text
    assert "RSL_LANGUAGES" in text
    assert "web_user_preferences" in text


def test_discord_translation_uses_shared_account_language_preference():
    text = COG.read_text(encoding="utf-8")
    assert "get_user_language" in text
    assert "set_user_language" in text
    assert '@app_commands.context_menu(name="RSL Language")' in text
    assert '@app_commands.context_menu(name="Translate Message")' in text


def test_flag_reaction_translation_and_dismissal_are_present():
    text = COG.read_text(encoding="utf-8")
    for marker in ("on_raw_reaction_add", "FLAG_TO_LANGUAGE", "TranslationDismissView", "TEMP_MESSAGE_SECONDS", "translate_text"):
        assert marker in text
    assert "message.author.bot" in text
    assert "allowed_mentions=discord.AllowedMentions" in text


def test_translation_cog_is_loaded_without_adding_a_slash_command():
    text = MAIN.read_text(encoding="utf-8")
    assert '"ALU_Gauntlet.cogs.translation"' in text
    assert '"/setup"' not in text


def test_discord_translation_provider_is_configurable_and_ui_dismiss_labels_are_localized():
    text = COG.read_text(encoding="utf-8")
    assert "RSL_TRANSLATION_URL" in text
    assert "RSL_TRANSLATION_EMAIL" in text
    assert "ClientSession(timeout=timeout, headers=headers)" in text
    assert "DismissButton(ui(current, \"dismiss\"))" in text
    assert "self.Dismiss(label)" in text
