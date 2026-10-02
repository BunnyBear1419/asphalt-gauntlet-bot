"""Event-driven advanced RSL XP progression."""
from __future__ import annotations
import time
from datetime import datetime, timezone
from discord.ext import commands, tasks
from .translation import localize_text
from ..core.rsl_role_sync import XP_LEVEL_ROLES, sync_xp_rank_role
from ..core.rsl_xp import award_xp, get_settings, progress_for_xp, xp_is_allowed

class RSLXPCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_tick.start()
        self.role_reconcile_tick.start()

    def cog_unload(self):
        self.voice_tick.cancel()
        self.role_reconcile_tick.cancel()

    async def _settings(self, guild_id):
        return await get_settings(self.bot.db, str(guild_id))

    async def _sync_level(self, guild_id, user_id, member, settings):
        if not member:
            return 0
        doc = await self.bot.db.drivers.find_one({"_id": f"{guild_id}_{user_id}"}, {"rsl_xp": 1}) or {}
        try:
            level = progress_for_xp(int(doc.get("rsl_xp", 0) or 0), settings)["level"]
            await sync_xp_rank_role(member, level, settings.get("achievement_role_names"), settings.get("achievement_role_ids"))
            role_sync_ok = True
            managed_role_ids = set()
            for reward in settings.get("role_rewards", []) or []:
                try:
                    threshold = int(reward.get("level", 0) or 0)
                    role = member.guild.get_role(int(reward.get("role_id", 0) or 0))
                except (TypeError, ValueError):
                    role, threshold = None, 0
                if role:
                    managed_role_ids.add(role.id)
                    if level >= threshold and role not in member.roles:
                        try:
                            await member.add_roles(role, reason="RSL XP role reward")
                        except Exception:
                            role_sync_ok = False
                            import logging
                            logging.getLogger(__name__).exception(
                                "Failed to grant RSL XP reward role %s to %s",
                                getattr(role, "id", "unknown"),
                                user_id,
                            )
            if level >= 5:
                rank_role_name = next(
                    (name for threshold, name in sorted(XP_LEVEL_ROLES.items())
                     if level >= threshold),
                    None,
                )
                rank_ids = settings.get("achievement_role_ids") or {}
                if rank_role_name and rank_role_name in rank_ids:
                    rank_role = member.guild.get_role(int(rank_ids[rank_role_name]))
                    if rank_role is not None and rank_role not in member.roles:
                        role_sync_ok = False
            if role_sync_ok:
                await self.bot.db.drivers.update_one(
                    {"_id": f"{guild_id}_{user_id}"},
                    {"$set": {"rsl_xp_role_sync_pending": False}},
                )
            return level
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "Failed to synchronize RSL XP roles for %s/%s",
                guild_id,
                user_id,
            )
            return 0

    async def _announce_level(self, guild, member, level, channel):
        settings = await self._settings(guild.id)
        if not settings.get("level_up_enabled", True) or not channel:
            return
        template = str(settings.get("level_up_message") or "🏁 {mention} reached Level {level}!")
        text = template.replace("{mention}", member.mention).replace("{username}", member.display_name).replace("{level}", str(level))
        text = await localize_text(self.bot, member.id, text, getattr(member, "locale", None))
        target = channel
        if settings.get("level_up_channel_id"):
            try:
                target = guild.get_channel(int(settings["level_up_channel_id"])) or channel
            except (TypeError, ValueError):
                target = channel
        try:
            await target.send(text)
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
        candidates = {member.id: member for member in getattr(role, "members", [])}
        if winner_id:
            winner = guild.get_member(int(winner_id)) if winner_id.isdigit() else None
            if winner is not None:
                candidates[winner.id] = winner
        for member in candidates.values():
            has = role in member.roles
            wants = str(member.id) == winner_id
            if wants and not has:
                try:
                    await member.add_roles(role, reason="RSL XP leaderboard leader")
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception(
                        "Failed to grant RSL XP leaderboard role to %s in guild %s",
                        member.id, guild.id,
                    )
            elif has and not wants:
                try:
                    await member.remove_roles(role, reason="RSL XP leaderboard rotation")
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception(
                        "Failed to remove RSL XP leaderboard role from %s in guild %s",
                        member.id, guild.id,
                    )

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot or not message.content.strip() or getattr(self.bot, "db", None) is None:
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
            old_level = progress_for_xp(int(profile.get("rsl_xp", 0) or 0), settings)["level"]
            new_level = await self._sync_level(message.guild.id, message.author.id, message.author, settings)
            if new_level > old_level:
                await self._announce_level(message.guild, message.author, new_level, message.channel)
            await self._sync_leader_role(message.guild, settings)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot or not reaction.message.guild or getattr(self.bot, "db", None) is None:
            return
        settings = await self._settings(reaction.message.guild.id)
        if not settings.get("reaction_enabled", True):
            return
        if not xp_is_allowed(settings, [str(r.id) for r in getattr(user, "roles", [])], str(reaction.message.channel.id)):
            return
        reaction_now = time.time()
        reaction_cooldown = int(settings.get("reaction_cooldown", 300) or 300)
        reaction_profile_id = f"{reaction.message.guild.id}_{user.id}"
        reaction_claim = await self.bot.db.drivers.update_one(
            {"_id": reaction_profile_id, "$or": [
                {"rsl_xp_last_reaction": {"$exists": False}},
                {"rsl_xp_last_reaction": {"$lte": reaction_now - reaction_cooldown}},
            ]},
            {"$set": {"rsl_xp_last_reaction": reaction_now}},
            upsert=False,
        )
        if getattr(reaction_claim, "modified_count", 0) != 1:
            return
        result = await award_xp(self.bot.db, guild_id=str(reaction.message.guild.id), user_id=str(user.id),
                       amount=int(settings.get("reaction_xp", 5) or 5), source="reaction",
                       event_id=f"{reaction.message.id}:{user.id}:{reaction.emoji}",
                       role_ids=[str(r.id) for r in getattr(user, "roles", [])], channel_id=str(reaction.message.channel.id), settings=settings)
        if result.get("ok") and not result.get("duplicate"):
            member = reaction.message.guild.get_member(user.id)
            if member:
                old_doc = await self.bot.db.drivers.find_one({"_id": f"{reaction.message.guild.id}_{user.id}"}, {"rsl_xp": 1}) or {}
                old_level = progress_for_xp(max(0, int(old_doc.get("rsl_xp", 0) or 0) - int(result.get("amount", 0) or 0)), settings)["level"]
                new_level = await self._sync_level(reaction.message.guild.id, user.id, member, settings)
                if new_level > old_level:
                    await self._announce_level(reaction.message.guild, member, new_level, reaction.message.channel)
            await self._sync_leader_role(reaction.message.guild, settings)

    @tasks.loop(minutes=10)
    async def role_reconcile_tick(self):
        """Durably retry XP role delivery after transient Discord failures."""
        if getattr(self.bot, "db", None) is None:
            return
        for guild in self.bot.guilds:
            try:
                settings = await self._settings(guild.id)
                cursor = self.bot.db.drivers.find(
                    {"guild_id": str(guild.id), "rsl_xp": {"$exists": True}, "rsl_xp_role_sync_pending": {"$ne": False}},
                    {"user_id": 1, "rsl_xp": 1},
                )
                async for driver in cursor:
                    user_id = str(driver.get("user_id") or "")
                    if not user_id.isdigit():
                        continue
                    member = guild.get_member(int(user_id))
                    if member is None:
                        continue
                    await self._sync_level(guild.id, user_id, member, settings)
                await self._sync_leader_role(guild, settings)
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "RSL XP role reconciliation failed for guild %s", guild.id
                )

    @role_reconcile_tick.before_loop
    async def before_role_reconcile_tick(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=3)
    async def voice_tick(self):
        if getattr(self.bot, "db", None) is None:
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
                    voice_cooldown = max(1, int(settings.get("voice_cooldown", 180) or 180))
                    voice_now = time.time()
                    voice_profile_id = f"{guild.id}_{member.id}"
                    voice_bucket = int(voice_now // voice_cooldown)
                    voice_claim = await self.bot.db.drivers.update_one(
                        {"_id": voice_profile_id, "$or": [
                            {"rsl_xp_last_voice_bucket": {"$exists": False}},
                            {"rsl_xp_last_voice_bucket": {"$ne": voice_bucket}},
                        ]},
                        {"$set": {"rsl_xp_last_voice_bucket": voice_bucket}},
                        upsert=False,
                    )
                    if getattr(voice_claim, "modified_count", 0) != 1:
                        continue
                    result = await award_xp(self.bot.db, guild_id=str(guild.id), user_id=str(member.id),
                                   amount=int(settings.get("voice_xp", 10) or 10), source="voice",
                                   event_id=f"{channel.id}:{member.id}:{voice_bucket}",
                                   role_ids=[str(r.id) for r in member.roles], channel_id=str(channel.id),
                                   metadata={"voice_seconds": voice_cooldown}, settings=settings)
                    if result.get("ok") and not result.get("duplicate"):
                        await self._sync_level(guild.id, member.id, member, settings)
            await self._sync_leader_role(guild, settings)

    @voice_tick.before_loop
    async def before_voice_tick(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(RSLXPCog(bot))
