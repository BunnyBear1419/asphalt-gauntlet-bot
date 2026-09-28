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
    assert '"owner":' in text
    assert 'ui(parent.language, "owner")' in text


def test_context_menus_are_module_level_and_registered_during_setup():
    text = COG.read_text(encoding="utf-8")
    class_start = text.index("class TranslationCog")
    assert text.index('@app_commands.context_menu(name="RSL Language")') < class_start
    assert text.index('@app_commands.context_menu(name="Translate Message")') < class_start
    assert "bot.tree.add_command(language_context)" in text
    assert "bot.tree.add_command(translate_context)" in text


def test_flag_reaction_listener_stays_on_translation_cog():
    text = COG.read_text(encoding="utf-8")
    class_start = text.index("class TranslationCog")
    class_end = text.index("\n\nasync def setup(bot):", class_start)
    listener = text.index("    @commands.Cog.listener()\n    async def on_raw_reaction_add", class_start)
    context_menu = text.index('@app_commands.context_menu(name="RSL Language")')
    assert class_start < listener < class_end
    assert context_menu < class_start
    assert text.count("async def on_raw_reaction_add") == 1


def test_rsl_language_preference_falls_back_to_discord_locale():
    text = LANG.read_text(encoding="utf-8")
    assert "DISCORD_LOCALE_TO_RSL" in text
    assert "def discord_locale_language" in text
    assert "discord_locale: Any = None" in text
    assert "saved in RSL_LANGUAGES" in text
    translation = COG.read_text(encoding="utf-8")
    assert "get_user_language(cog.bot, interaction.user.id, interaction.locale)" in translation


def test_english_translation_is_local_only_and_unavailable_context_menu_is_localized():
    text = COG.read_text(encoding="utf-8")
    assert 'if target == "en":' in text
    assert 'return text' in text
    assert "discord_locale_language(interaction.locale)" in text
    assert 'ui(language, "failed")' in text


def test_localized_response_helper_and_ticket_purchase_use_shared_language():
    translation = COG.read_text(encoding="utf-8")
    ticket = (ROOT / "ALU_Gauntlet" / "cogs" / "ticket_economy.py").read_text(encoding="utf-8")
    assert "async def localize_text" in translation
    assert "get_user_language(bot, user_id, discord_locale)" in translation
    assert "await translate_text(text, target)" in translation
    assert "from .translation import localize_text" in ticket
    assert "await localize_text(self.bot, interaction.user.id" in ticket


def test_gauntlet_response_surfaces_use_shared_localization():
    root = ROOT / "ALU_Gauntlet" / "cogs"
    for name in ("defense.py", "challenges.py", "competition.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "from .translation import localize_text" in text
        assert "await localize_text(bot, interaction.user.id" in text
