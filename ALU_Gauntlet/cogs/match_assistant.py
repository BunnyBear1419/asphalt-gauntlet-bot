"""RSL Discord match assistant.

Sends deadline reminders for active Gauntlet challenges without adding another
slash-command surface. Support remains Discord-ticket based and is intentionally
separate from this operational reminder service.
"""
from __future__ import annotations

import time

import discord
from discord.ext import commands, tasks
from pymongo.errors import DuplicateKeyError

from .translation import localize_text
from ..core.rsl_recovery import reconcile_processing_challenges

MATCH_CENTER_URL = "https://asph.discloud.app/gauntlet/matches"
REMINDER_WINDOWS = (
    (24 * 3600, "24 hours"),
    (6 * 3600, "6 hours"),
    (3600, "1 hour"),
)


class MatchAssistantCog(commands.Cog):
    """Proactive Discord reminders for active Gauntlet matches."""

    def __init__(self, bot):
        self.bot = bot
        self.loop.start()

    def cog_unload(self):
        self.loop.cancel()

    async def _claim(self, guild_id: str, challenge_id: str, user_id: str, window: str, now: float) -> bool:
        key = {
            "event_id": f"match-deadline:{guild_id}:{challenge_id}:{window}",
            "user_id": user_id,
            "lead_days": 0.0,
        }
        try:
            result = await self.bot.db.notification_deliveries.update_one(
                key,
                {"$setOnInsert": {"created_at": now, "status": "sending", "kind": "match_deadline"}},
                upsert=True,
            )
            return bool(result.upserted_id)
        except DuplicateKeyError:
            return False

    async def _notify(self, challenge, user_id: str, remaining: str, expires_at: float):
        guild_id = str(challenge.get("guild_id") or "")
        challenge_id = str(challenge.get("_id") or "")
        if not guild_id or not challenge_id or not user_id.isdigit():
            return
        now = time.time()
        if not await self._claim(guild_id, challenge_id, user_id, remaining, now):
            return
        try:
            user = self.bot.get_user(int(user_id)) or await self.bot.fetch_user(int(user_id))
            locale = getattr(user, "locale", None)
            opponent_id = str(challenge.get("opponent_id") or challenge.get("challenger_id") or "")
            if opponent_id == user_id:
                opponent_id = str(challenge.get("opponent_id") or "")
            opponent = self.bot.get_user(int(opponent_id)) if opponent_id.isdigit() else None
            opponent_name = getattr(opponent, "display_name", None) or "your RSL opponent"
            embed = discord.Embed(
                title=await localize_text(self.bot, int(user_id), "🏁 RSL Match Assistant", locale),
                description=await localize_text(
                    self.bot,
                    int(user_id),
                    f"Your Gauntlet match with **{opponent_name}** has about **{remaining}** remaining.",
                    locale,
                ),
                color=0x19D3FF,
            )
            embed.add_field(
                name=await localize_text(self.bot, int(user_id), "Deadline", locale),
                value=f"<t:{int(expires_at)}:F>\n<t:{int(expires_at)}:R>",
                inline=True,
            )
            embed.add_field(
                name=await localize_text(self.bot, int(user_id), "Next step", locale),
                value=await localize_text(
                    self.bot,
                    int(user_id),
                    "Open the Match Center to submit the match or review what is still pending.",
                    locale,
                ),
                inline=False,
            )
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(label="Open Match Center", style=discord.ButtonStyle.link, url=MATCH_CENTER_URL))
            await user.send(embed=embed, view=view)
            await self.bot.db.notification_deliveries.update_one(
                {
                    "event_id": f"match-deadline:{guild_id}:{challenge_id}:{remaining}",
                    "user_id": user_id,
                    "lead_days": 0.0,
                },
                {"$set": {"sent_at": now, "status": "sent"}},
            )
        except (discord.Forbidden, discord.HTTPException):
            await self.bot.db.notification_deliveries.delete_one(
                {
                    "event_id": f"match-deadline:{guild_id}:{challenge_id}:{remaining}",
                    "user_id": user_id,
                    "lead_days": 0.0,
                }
            )
        except Exception:
            await self.bot.db.notification_deliveries.delete_one(
                {
                    "event_id": f"match-deadline:{guild_id}:{challenge_id}:{remaining}",
                    "user_id": user_id,
                    "lead_days": 0.0,
                }
            )

    async def _scan(self):
        now = time.time()
        # Recovery also reconciles completed challenges whose deterministic
        # settlement exists but whose RSL margin bonus is still missing. Do
        # not let guild discovery depend solely on an active processing row.
        processing_guild_ids = await self.bot.db.active_challenges.distinct(
            "guild_id", {"status": "processing"}
        )
        completed_bonus_guild_ids = await self.bot.db.active_challenges.distinct(
            "guild_id", {"status": "completed"}
        )
        guild_ids = set(processing_guild_ids) | set(completed_bonus_guild_ids)
        for guild_id in guild_ids:
            try:
                await reconcile_processing_challenges(self.bot.db, str(guild_id))
            except Exception:
                # Recovery must not stop deadline reminders for other guilds.
                continue
        async for challenge in self.bot.db.active_challenges.find({"status": {"$in": ["active", "processing"]}}):
            try:
                expires_at = float(challenge.get("expires_at", 0) or 0)
                if expires_at <= now:
                    continue
                remaining = expires_at - now
                window = next((item for item in REMINDER_WINDOWS if remaining <= item[0] and remaining > item[0] - 90), None)
                if window is None:
                    continue
                for user_id in {str(challenge.get("challenger_id") or ""), str(challenge.get("opponent_id") or "")}:
                    if user_id.isdigit():
                        await self._notify(challenge, user_id, window[1], expires_at)
            except Exception:
                continue

    @tasks.loop(seconds=60)
    async def loop(self):
        try:
            await self._scan()
        except Exception:
            pass

    @loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(MatchAssistantCog(bot))
