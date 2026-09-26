"""RSL community activity rewards.

Rewards genuine human participation with a cooldown and daily cap. Bot/system
messages never earn XP or RSL Coins.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from discord.ext import commands

from ..core.rsl_activity import (
    CHAT_CREDITS,
    CHAT_XP,
    DAILY_CHAT_REWARD_CAP,
    chat_reward_available,
)


class ActivityRewardsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot or not message.content.strip():
            return
        if not getattr(self.bot, "db", None):
            return

        guild_id = str(message.guild.id)
        user_id = str(message.author.id)
        profile = await self.bot.db.drivers.find_one(
            {"_id": f"{guild_id}_{user_id}"},
            {"activity_reward_date": 1, "activity_reward_count": 1, "activity_last_reward_at": 1},
        )
        if not profile:
            return

        now = time.time()
        today = self._today()
        reward_date = profile.get("activity_reward_date")
        reward_count = int(profile.get("activity_reward_count", 0) or 0)
        last_reward_at = profile.get("activity_last_reward_at")

        if reward_date != today:
            await self.bot.db.drivers.update_one(
                {"_id": f"{guild_id}_{user_id}"},
                {"$set": {"activity_reward_date": today, "activity_reward_count": 0}},
            )
            reward_count = 0
            last_reward_at = None

        if not chat_reward_available(
            last_reward_at=last_reward_at,
            reward_date=today,
            today=today,
            reward_count=reward_count,
            now=now,
        ):
            return

        updated = await self.bot.db.drivers.update_one(
            {
                "_id": f"{guild_id}_{user_id}",
                "activity_reward_date": today,
                "activity_reward_count": {"$lt": DAILY_CHAT_REWARD_CAP},
                "$or": [
                    {"activity_last_reward_at": {"$exists": False}},
                    {"activity_last_reward_at": {"$lte": now - 120}},
                ],
            },
            {
                "$inc": {
                    "rsl_coins": CHAT_CREDITS,
                    "activity_xp": CHAT_XP,
                    "activity_reward_count": 1,
                },
                "$set": {"activity_last_reward_at": now},
            },
        )
        if getattr(updated, "modified_count", 0) != 1:
            return


async def setup(bot):
    await bot.add_cog(ActivityRewardsCog(bot))
