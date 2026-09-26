"""Conservative RSL Coin deductions for clear/repeated chat violations."""
from __future__ import annotations
import re
import time
from datetime import datetime, timezone
from discord.ext import commands
from ..core.rsl_economy import MAX_AUTOMATED_MODERATION_PENALTY_PER_DAY, moderation_penalty

_AD = re.compile(r"\b(?:buy|sell|promo|promotion|advertise|advertisement|discount|free\s+nitro|join\s+my\s+server)\b", re.I)
_URL = re.compile(r"https?://\S+|discord\.gg/\S+", re.I)
_SHORT = re.compile(r"https?://(?:bit\.ly|tinyurl\.com|t\.co|goo\.gl)/\S+", re.I)
_INVITE = re.compile(r"(?:https?://)?discord\.gg/\S+", re.I)
_SWEAR = re.compile(r"\b(?:fuck|fucking|shit|bitch|asshole)\b", re.I)

def classify_violation(content: str, *, repeat_count: int = 0) -> str | None:
    text = str(content or "").strip()
    if not text:
        return None
    if repeat_count >= 3:
        return "spam"
    if len(_SWEAR.findall(text)) >= 3:
        return "swearing"
    if _AD.search(text) and _URL.search(text):
        return "advertising"
    if _SHORT.search(text) or _INVITE.search(text):
        return "unwanted_link"
    return None

class EconomyModerationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot or not message.content.strip() or not getattr(self.bot, "db", None):
            return
        guild_id, user_id = str(message.guild.id), str(message.author.id)
        driver_id, now, today = f"{guild_id}_{user_id}", time.time(), self._today()
        profile = await self.bot.db.drivers.find_one(
            {"_id": driver_id},
            {"moderation_last_content": 1, "moderation_last_content_at": 1,
             "moderation_repeat_count": 1, "moderation_penalty_date": 1,
             "moderation_penalty_total": 1},
        )
        if not profile:
            return
        last = str(profile.get("moderation_last_content") or "")
        last_at = float(profile.get("moderation_last_content_at", 0) or 0)
        repeats = int(profile.get("moderation_repeat_count", 0) or 0)
        repeats = repeats + 1 if message.content.strip().casefold() == last.casefold() and now - last_at <= 60 else 1
        category = classify_violation(message.content, repeat_count=repeats)
        penalty_total = int(profile.get("moderation_penalty_total", 0) or 0) if profile.get("moderation_penalty_date") == today else 0
        await self.bot.db.drivers.update_one({"_id": driver_id}, {"$set": {
            "moderation_last_content": message.content[:500], "moderation_last_content_at": now,
            "moderation_repeat_count": repeats, "moderation_penalty_date": today,
            "moderation_penalty_total": penalty_total,
        }})
        if not category:
            return
        penalty = moderation_penalty(category)
        if penalty <= 0 or penalty_total + penalty > MAX_AUTOMATED_MODERATION_PENALTY_PER_DAY:
            return
        updated = await self.bot.db.drivers.update_one(
            {"_id": driver_id, "rsl_coins": {"$gte": penalty},
             "moderation_penalty_date": today,
             "moderation_penalty_total": {"$lte": MAX_AUTOMATED_MODERATION_PENALTY_PER_DAY - penalty}},
            {"$inc": {"rsl_coins": -penalty, "moderation_penalty_total": penalty}},
        )
        if getattr(updated, "modified_count", 0) != 1:
            return
        try:
            await self.bot.db.rsl_economy_transactions.insert_one({
                "guild_id": guild_id, "user_id": user_id, "type": "moderation_penalty",
                "reason": category, "amount": -penalty, "message_id": str(message.id), "created_at": now,
            })
        except Exception:
            pass

async def setup(bot):
    await bot.add_cog(EconomyModerationCog(bot))
