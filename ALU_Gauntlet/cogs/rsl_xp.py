"""Event-driven advanced RSL XP progression."""
from __future__ import annotations
import time
from datetime import datetime, timezone
from discord.ext import commands, tasks
from ..core.rsl_role_sync import sync_xp_rank_role
from ..core.rsl_xp import award_xp, get_settings, progress_for_xp, xp_is_allowed

class RSLXPCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_tick.start()

    def cog_unload(self):
        self.voice_tick.cancel()

    async def _settings(self, guild_id):
        return await get_settings(self.bot.db, str(guild_id))

    async def _sync_level(self, guild_id, user_id, member, settings):
        if not member:
            return
        doc = await self.bot.db.drivers.find_one({"_id": f"{guild_id}_{user_id}"}, {"rsl_xp": 1}) or {}
        try:
            level = progress_for_xp(int(doc.get("rsl_xp", 0) or 0), settings)["level"]
            await sync_xp_rank_role(member, level)
            for reward in settings.get("role_rewards", []) or []:
                try:
                    threshold = int(reward.get("level", 0) or 0)
                    role = member.guild.get_role(int(reward.get("role_id", 0) or 0))
                except (TypeError, ValueError):
                    role, threshold = None, 0
                if role and level >= threshold and role not in member.roles:
                    try:
                        await member.add_roles(role, reason="RSL XP role reward")
                    except Exception:
                        pass
        except Exception:
            pass

    async def _sync_leader_role(self, guild, settings):
        role_id = str(settings.get("leader_role_id") or "")
        if not role_id:
            return
        period = str(settings.get("leader_role_period") or "weekly")
        if period not in {"all", "weekly", "monthly"}:
            period = "weekly"
        try:
            role = guild.get_role(int(role_id))
        except (TypeError, ValueError):
            role = None
        if not role:
            return
        field = {"all": "rsl_xp", "weekly": "rsl_xp_weekly", "monthly": "rsl_xp_monthly"}[period]
        top = await self.bot.db.drivers.find_one({"guild_id": str(guild.id), "user_id": {"$exists": True}}, sort=[(field, -1)])
        winner_id = str(top.get("user_id")) if top and int(top.get(field, 0) or 0) > 0 else ""
        for member in guild.members:
            has = role in member.roles
            wants = str(member.id) == winner_id
            if wants and not has:
                try:
                    await member.add_roles(role, reason="RSL XP leaderboard leader")
                except Exception:
                    pass
            elif has and not wants:
                try:
                    await member.remove_roles(role, reason="RSL XP leaderboard rotation")
                except Exception:
                    pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot or not message.content.strip() or not getattr(self.bot, "db", None):
            return
        settings = await self._settings(message.guild.id)
        if not settings.get("message_enabled", True):
            return
        if not xp_is_allowed(settings, [str(r.id) for r in message.author.roles], str(message.channel.id)):
            return
        profile = await self.bot.db.drivers.find_one({"_id": f"{message.guild.id}_{message.author.id}"}, {"rsl_xp_last_message": 1, "rsl_xp": 1})
        if not profile:
            return
        now = time.time()
        if now - float(profile.get("rsl_xp_last_message", 0) or 0) < int(settings.get("message_cooldown", 60)):
            return
        claim = await self.bot.db.drivers.update_one({"_id": profile["_id"], "$or": [{"rsl_xp_last_message": {"$exists": False}}, {"rsl_xp_last_message": {"$lte": now - int(settings.get("message_cooldown", 60))}}]}, {"$set": {"rsl_xp_last_message": now}})
        if getattr(claim, "modified_count", 0) != 1:
            return
        # The existing activity reward remains the RSL Coin reward; this is the independent XP layer.
        minimum = int(settings.get("message_min", 15) or 15)
        maximum = max(minimum, int(settings.get("message_max", 30) or 30))
        amount = minimum if minimum == maximum else minimum + ((hash(str(message.id)) % (maximum - minimum + 1)))
        result = await award_xp(self.bot.db, guild_id=str(message.guild.id), user_id=str(message.author.id),
                       amount=amount, source="message", event_id=str(message.id),
                       role_ids=[str(r.id) for r in message.author.roles], channel_id=str(message.channel.id), settings=settings)
        if result.get("ok") and not result.get("duplicate"):
            await self._sync_level(message.guild.id, message.author.id, message.author, settings)
            await self._sync_leader_role(message.guild if "message" in locals() else reaction.message.guild if "reaction" in locals() else guild, settings)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot or not reaction.message.guild or not getattr(self.bot, "db", None):
            return
        settings = await self._settings(reaction.message.guild.id)
        if not settings.get("reaction_enabled", True):
            return
        if not xp_is_allowed(settings, [str(r.id) for r in getattr(user, "roles", [])], str(reaction.message.channel.id)):
            return
        result = await award_xp(self.bot.db, guild_id=str(reaction.message.guild.id), user_id=str(user.id),
                       amount=int(settings.get("reaction_xp", 5) or 5), source="reaction",
                       event_id=f"{reaction.message.id}:{user.id}:{reaction.emoji}",
                       role_ids=[str(r.id) for r in getattr(user, "roles", [])], channel_id=str(reaction.message.channel.id), settings=settings)
        if result.get("ok") and not result.get("duplicate"):
            await self._sync_level(reaction.message.guild.id, user.id, reaction.message.guild.get_member(user.id), settings)
            await self._sync_leader_role(message.guild if "message" in locals() else reaction.message.guild if "reaction" in locals() else guild, settings)

    @tasks.loop(minutes=3)
    async def voice_tick(self):
        if not getattr(self.bot, "db", None):
            return
        for guild in self.bot.guilds:
            settings = await self._settings(guild.id)
            if not settings.get("voice_enabled", True):
                continue
            for channel in guild.voice_channels:
                members = [m for m in channel.members if not m.bot and not m.voice.afk and not m.voice.self_deaf and not m.voice.deaf and not m.voice.self_mute and not m.voice.mute]
                if len(members) < int(settings.get("voice_min_members", 2) or 2):
                    continue
                for member in members:
                    if not xp_is_allowed(settings, [str(r.id) for r in member.roles], str(channel.id)):
                        continue
                    result = await award_xp(self.bot.db, guild_id=str(guild.id), user_id=str(member.id),
                                   amount=int(settings.get("voice_xp", 10) or 10), source="voice",
                                   event_id=f"{channel.id}:{member.id}:{int(time.time()) // 180}",
                                   role_ids=[str(r.id) for r in member.roles], channel_id=str(channel.id),
                                   metadata={"voice_seconds": 180}, settings=settings)
                    if result.get("ok") and not result.get("duplicate"):
                        await self._sync_level(guild.id, member.id, member, settings)
            await self._sync_leader_role(message.guild if "message" in locals() else reaction.message.guild if "reaction" in locals() else guild, settings)

    @voice_tick.before_loop
    async def before_voice_tick(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(RSLXPCog(bot))
