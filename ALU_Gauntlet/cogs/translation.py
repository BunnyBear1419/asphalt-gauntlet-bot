"""RSL Discord language preferences and on-demand message translation."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import OrderedDict

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from ..core.rsl_language import (
    FLAG_TO_LANGUAGE,
    RSL_LANGUAGES,
    get_user_language,
    discord_locale_language,
    language_flag,
    language_name,
    normalize_language,
    set_user_language,
)

log = logging.getLogger(__name__)

# MyMemory is used through its public HTTP endpoint so RSL does not require
# another Python dependency. Deployments can override it with RSL_TRANSLATION_URL.
TRANSLATION_URL = os.getenv("RSL_TRANSLATION_URL", "https://api.mymemory.translated.net/get")
TRANSLATION_EMAIL = os.getenv("RSL_TRANSLATION_EMAIL", "")
MAX_TRANSLATION_CHARS = 1800
TRANSLATION_TTL_SECONDS = 600
TEMP_MESSAGE_SECONDS = 45
_CACHE: OrderedDict[tuple[str, str], tuple[float, str]] = OrderedDict()
_CACHE_MAX = 512

UI_TEXT = {
    "en": {"settings": "🌐 RSL Language", "choose": "Choose the language RSL should use for your Discord experience.", "saved": "Language saved", "translation": "Translation", "dismiss": "Dismiss", "failed": "Translation unavailable right now.", "owner": "Only the person who requested this translation can dismiss it."},
    "es": {"settings": "🌐 Idioma de RSL", "choose": "Elige el idioma que RSL debe usar para tu experiencia en Discord.", "saved": "Idioma guardado", "translation": "Traducción", "dismiss": "Descartar", "failed": "La traducción no está disponible en este momento.", "owner": "Solo la persona que solicitó esta traducción puede cerrarla."},
    "fr": {"settings": "🌐 Langue RSL", "choose": "Choisissez la langue que RSL doit utiliser dans Discord.", "saved": "Langue enregistrée", "translation": "Traduction", "dismiss": "Fermer", "failed": "Traduction indisponible pour le moment.", "owner": "Seule la personne qui a demandé cette traduction peut la fermer."},
    "de": {"settings": "🌐 RSL-Sprache", "choose": "Wählen Sie die Sprache, die RSL in Discord verwenden soll.", "saved": "Sprache gespeichert", "translation": "Übersetzung", "dismiss": "Schließen", "failed": "Übersetzung derzeit nicht verfügbar.", "owner": "Nur die Person, die diese Übersetzung angefordert hat, kann sie schließen."},
    "pt": {"settings": "🌐 Idioma do RSL", "choose": "Escolha o idioma que o RSL deve usar no Discord.", "saved": "Idioma salvo", "translation": "Tradução", "dismiss": "Dispensar", "failed": "Tradução indisponível no momento.", "owner": "Somente a pessoa que solicitou esta tradução pode fechá-la."},
    "it": {"settings": "🌐 Lingua RSL", "choose": "Scegli la lingua che RSL deve usare su Discord.", "saved": "Lingua salvata", "translation": "Traduzione", "dismiss": "Chiudi", "failed": "Traduzione non disponibile al momento.", "owner": "Solo la persona che ha richiesto questa traduzione può chiuderla."},
    "nl": {"settings": "🌐 RSL-taal", "choose": "Kies de taal die RSL op Discord moet gebruiken.", "saved": "Taal opgeslagen", "translation": "Vertaling", "dismiss": "Sluiten", "failed": "Vertaling is momenteel niet beschikbaar.", "owner": "Alleen de persoon die deze vertaling heeft aangevraagd kan deze sluiten."},
    "tr": {"settings": "🌐 RSL Dili", "choose": "RSL'nin Discord deneyiminizde kullanacağı dili seçin.", "saved": "Dil kaydedildi", "translation": "Çeviri", "dismiss": "Kapat", "failed": "Çeviri şu anda kullanılamıyor.", "owner": "Bu çeviriyi isteyen kişi onu kapatabilir."},
    "pl": {"settings": "🌐 Język RSL", "choose": "Wybierz język, którego RSL ma używać na Discordzie.", "saved": "Język zapisany", "translation": "Tłumaczenie", "dismiss": "Zamknij", "failed": "Tłumaczenie jest obecnie niedostępne.", "owner": "Tylko osoba, która poprosiła o to tłumaczenie, może je zamknąć."},
    "vi": {"settings": "🌐 Ngôn ngữ RSL", "choose": "Chọn ngôn ngữ RSL sẽ sử dụng trên Discord.", "saved": "Đã lưu ngôn ngữ", "translation": "Bản dịch", "dismiss": "Đóng", "failed": "Bản dịch hiện không khả dụng.", "owner": "Chỉ người yêu cầu bản dịch này mới có thể đóng bản dịch."},
    "id": {"settings": "🌐 Bahasa RSL", "choose": "Pilih bahasa yang akan digunakan RSL di Discord.", "saved": "Bahasa disimpan", "translation": "Terjemahan", "dismiss": "Tutup", "failed": "Terjemahan sedang tidak tersedia.", "owner": "Hanya orang yang meminta terjemahan ini yang dapat menutupnya."},
    "ja": {"settings": "🌐 RSL言語", "choose": "DiscordでRSLが使用する言語を選択してください。", "saved": "言語を保存しました", "translation": "翻訳", "dismiss": "閉じる", "failed": "現在、翻訳を利用できません。", "owner": "この翻訳をリクエストした本人のみ閉じることができます。"},
    "ko": {"settings": "🌐 RSL 언어", "choose": "Discord에서 RSL이 사용할 언어를 선택하세요.", "saved": "언어가 저장되었습니다", "translation": "번역", "dismiss": "닫기", "failed": "현재 번역을 사용할 수 없습니다.", "owner": "이 번역을 요청한 사람만 닫을 수 있습니다."},
    "zh-CN": {"settings": "🌐 RSL 语言", "choose": "选择 RSL 在 Discord 中使用的语言。", "saved": "语言已保存", "translation": "翻译", "dismiss": "关闭", "failed": "翻译暂时不可用。", "owner": "只有请求此翻译的人可以关闭它。"},
    "ar": {"settings": "🌐 لغة RSL", "choose": "اختر اللغة التي سيستخدمها RSL في Discord.", "saved": "تم حفظ اللغة", "translation": "الترجمة", "dismiss": "إغلاق", "failed": "الترجمة غير متاحة حالياً.", "owner": "يمكن للشخص الذي طلب هذه الترجمة فقط إغلاقها."},
    "ru": {"settings": "🌐 Язык RSL", "choose": "Выберите язык, который RSL будет использовать в Discord.", "saved": "Язык сохранён", "translation": "Перевод", "dismiss": "Закрыть", "failed": "Перевод сейчас недоступен.", "owner": "Закрыть этот перевод может только тот, кто его запросил."},
    "hi": {"settings": "🌐 RSL भाषा", "choose": "Discord में RSL द्वारा उपयोग की जाने वाली भाषा चुनें।", "saved": "भाषा सहेजी गई", "translation": "अनुवाद", "dismiss": "बंद करें", "failed": "अनुवाद अभी उपलब्ध नहीं है।", "owner": "केवल इस अनुवाद का अनुरोध करने वाला व्यक्ति इसे बंद कर सकता है।"},
    "ms": {"settings": "🌐 Bahasa RSL", "choose": "Pilih bahasa yang akan digunakan RSL di Discord.", "saved": "Bahasa disimpan", "translation": "Terjemahan", "dismiss": "Tutup", "failed": "Terjemahan tidak tersedia buat masa ini.", "owner": "Hanya orang yang meminta terjemahan ini boleh menutupnya."},
    "th": {"settings": "🌐 ภาษา RSL", "choose": "เลือกภาษาที่ RSL จะใช้ใน Discord", "saved": "บันทึกภาษาแล้ว", "translation": "คำแปล", "dismiss": "ปิด", "failed": "ขณะนี้ไม่สามารถแปลได้", "owner": "เฉพาะผู้ที่ขอการแปลนี้เท่านั้นที่สามารถปิดได้"},
    "uk": {"settings": "🌐 Мова RSL", "choose": "Виберіть мову, яку RSL використовуватиме в Discord.", "saved": "Мову збережено", "translation": "Переклад", "dismiss": "Закрити", "failed": "Переклад наразі недоступний.", "owner": "Лише особа, яка запросила цей переклад, може його закрити."},
}


def ui(code: str, key: str) -> str:
    code = normalize_language(code)
    return UI_TEXT.get(code, UI_TEXT["en"]).get(key, UI_TEXT["en"][key])


async def translate_text(text: str, target: str) -> str:
    target = normalize_language(target)
    text = text.strip()
    if target == "en":
        return text
    if not text:
        return ""
    if len(text) > MAX_TRANSLATION_CHARS:
        text = text[:MAX_TRANSLATION_CHARS - 1] + "…"
    if target == "en" and not text:
        return text

    cache_key = (target, text)
    cached = _CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < TRANSLATION_TTL_SECONDS:
        return cached[1]

    params = {
        "q": text,
        "langpair": f"autodetect|{target}",
        **({"de": TRANSLATION_EMAIL} if TRANSLATION_EMAIL else {}),
    }
    timeout = aiohttp.ClientTimeout(total=12)
    headers = {"User-Agent": "RacingSyndicateLeague/1.0"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(TRANSLATION_URL, params=params) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
    translated = str((data.get("responseData") or {}).get("translatedText") or "").strip()
    if not translated:
        raise RuntimeError("Translation provider returned no translation")
    _CACHE[cache_key] = (time.monotonic(), translated)
    _CACHE.move_to_end(cache_key)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return translated


class LanguageSelect(discord.ui.Select):
    def __init__(self, cog: "TranslationCog", current: str):
        self.cog = cog
        options = [
            discord.SelectOption(
                label=item["name"],
                value=code,
                emoji=item["flag"],
                default=code == current,
            )
            for code, item in RSL_LANGUAGES.items()
        ]
        super().__init__(placeholder=f"{language_flag(current)} {language_name(current)}", options=options, custom_id="rsl:language")


    async def callback(self, interaction: discord.Interaction) -> None:
        code = normalize_language(self.values[0])
        await set_user_language(self.cog.bot, interaction.user.id, code)
        await interaction.response.edit_message(
            content=f"{language_flag(code)} **{ui(code, 'saved')}** — {language_name(code)}",
            view=LanguageView(self.cog, code),
        )


class LanguageView(discord.ui.View):
    def __init__(self, cog: "TranslationCog", current: str):
        super().__init__(timeout=300)
        self.add_item(LanguageSelect(cog, current))
        self.add_item(DismissButton(ui(current, "dismiss")))


class DismissButton(discord.ui.Button):
    def __init__(self, label: str = "Dismiss"):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, custom_id="rsl:dismiss")

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(content=" ", view=None, embed=None)


class TranslationDismissView(discord.ui.View):
    def __init__(self, owner_id: int, label: str, language: str):
        super().__init__(timeout=TEMP_MESSAGE_SECONDS)
        self.owner_id = owner_id
        self.label = label
        self.language = normalize_language(language)
        self.add_item(self.Dismiss(label))

    class Dismiss(discord.ui.Button):
        def __init__(self, label: str = "Dismiss"):
            super().__init__(label=label, style=discord.ButtonStyle.secondary, custom_id="rsl:translation-dismiss")

        async def callback(self, interaction: discord.Interaction) -> None:
            parent = self.view
            if parent and interaction.user.id != parent.owner_id:
                await interaction.response.send_message(ui(parent.language, "owner"), ephemeral=True)
                return
            await interaction.response.edit_message(content=" ", view=None)


@app_commands.context_menu(name="RSL Language")
async def language_context(interaction: discord.Interaction, message: discord.Message):
    cog = interaction.client.get_cog("TranslationCog")
    if cog is None:
        language = discord_locale_language(interaction.locale)
        await interaction.response.send_message(ui(language, "failed"), ephemeral=True)
        return
    current = await get_user_language(cog.bot, interaction.user.id, interaction.locale)
    await interaction.response.send_message(
        f"{ui(current, 'settings')}\n{ui(current, 'choose')}\n\nCurrent: {language_flag(current)} **{language_name(current)}**",
        view=LanguageView(cog, current),
        ephemeral=True,
    )


@app_commands.context_menu(name="Translate Message")
async def translate_context(interaction: discord.Interaction, message: discord.Message):
    cog = interaction.client.get_cog("TranslationCog")
    if cog is None:
        await interaction.response.send_message("RSL translation is currently unavailable.", ephemeral=True)
        return
    target = await get_user_language(cog.bot, interaction.user.id, interaction.locale)
    if not message.content.strip():
        await interaction.response.send_message(ui(target, "failed"), ephemeral=True)
        return
    try:
        translated = await translate_text(message.content, target)
    except Exception:
        log.exception("Message translation failed")
        await interaction.response.send_message(ui(target, "failed"), ephemeral=True)
        return
    await interaction.response.send_message(
        f"{language_flag(target)} **{ui(target, 'translation')} — {language_name(target)}**\n{translated}",
        ephemeral=True,
    )


class TranslationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._reaction_cooldowns: dict[tuple[int, int], float] = {}

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        emoji = str(payload.emoji)
        target = FLAG_TO_LANGUAGE.get(emoji)
        if not target or not payload.guild_id:
            return

        key = (payload.user_id, payload.message_id)
        now = time.monotonic()
        if now - self._reaction_cooldowns.get(key, 0) < 5:
            return
        self._reaction_cooldowns[key] = now

        channel = self.bot.get_channel(payload.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(payload.channel_id)
            except Exception:
                return
        try:
            message = await channel.fetch_message(payload.message_id)
        except Exception:
            return
        if message.author.bot or not message.content.strip():
            return

        try:
            translated = await translate_text(message.content, target)
            text = (
                f"{language_flag(target)} **{ui(target, 'translation')} — {language_name(target)}** "
                f"for <@{payload.user_id}>\n{translated}"
            )
            sent = await channel.send(
                text,
                allowed_mentions=discord.AllowedMentions(users=[discord.Object(id=payload.user_id)]),
                view=TranslationDismissView(payload.user_id, ui(target, "dismiss"), target),
            )
            try:
                await asyncio.sleep(TEMP_MESSAGE_SECONDS)
                await sent.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        except Exception:
            log.exception("Reaction translation failed for message %s", payload.message_id)




async def setup(bot):
    await bot.add_cog(TranslationCog(bot))
    bot.tree.add_command(language_context)
    bot.tree.add_command(translate_context)
