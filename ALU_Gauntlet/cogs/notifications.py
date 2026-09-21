"""Discord DM notifications for scheduled RSL calendar events."""

import time
from datetime import datetime, timezone
import discord
from discord.ext import commands, tasks

from ..core.core import bot


def _iso_timestamp(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


class NotificationCog(commands.Cog):
    """Deliver opted-in calendar notifications by Discord DM."""

    def __init__(self, bot_instance):
        self.bot = bot_instance
        self.notification_loop.start()

    def cog_unload(self):
        self.notification_loop.cancel()

    async def _calendar_events(self):
        events = []
        async for state in self.bot.db.season_state.find({}):
            guild_id = str(state.get("guild_id") or str(state.get("_id", "")).removeprefix("guild_"))
            season = int(state.get("season_number", 1) or 1)
            start = float(state.get("starts_at", 0) or 0)
            end = float(state.get("ends_at", 0) or 0)
            guild = self.bot.get_guild(int(guild_id)) if guild_id.isdigit() else None
            guild_name = getattr(guild, "name", guild_id) or guild_id
            if start:
                events.append({
                    "id": f"season-start-{guild_id}-{season}",
                    "type": "gauntlet",
                    "kind": "start",
                    "title": f"Gauntlet Season {season} Starts",
                    "guild_name": guild_name,
                    "timestamp": start,
                })
            if end:
                events.append({
                    "id": f"season-end-{guild_id}-{season}",
                    "type": "gauntlet",
                    "kind": "end",
                    "title": f"Gauntlet Season {season} Ends",
                    "guild_name": guild_name,
                    "timestamp": end,
                })

        async for item in self.bot.db.tournaments.find({}):
            tid = str(item.get("_id"))
            title = str(item.get("name", "Tournament"))
            guild_id = str(item.get("guild_id", ""))
            guild = self.bot.get_guild(int(guild_id)) if guild_id.isdigit() else None
            guild_name = getattr(guild, "name", guild_id) or guild_id
            base = {
                "type": "tournament",
                "guild_name": guild_name,
                "title": title,
            }
            start = _iso_timestamp(item.get("start_time"))
            end = _iso_timestamp(item.get("end_time") or item.get("completed_at"))
            registration = _iso_timestamp(item.get("registration_deadline"))
            if start:
                events.append({**base, "id": tid, "kind": "start", "timestamp": start})
            if end:
                events.append({**base, "id": tid + "-end", "kind": "end", "timestamp": end})
            if registration:
                events.append({
                    **base,
                    "id": tid + "-registration",
                    "kind": "registration",
                    "title": title + " Registration Closes",
                    "timestamp": registration,
                })
        return events

    @staticmethod
    def _lead_days(record, event):
        event_id = str(event["id"])
        overrides = record.get("event_lead_days") or {}
        if event_id in overrides:
            try:
                return float(overrides[event_id])
            except (TypeError, ValueError):
                pass
        try:
            return float(record.get(f'{event["type"]}_lead_days', 1) or 1)
        except (TypeError, ValueError):
            return 1.0

    @staticmethod
    def _wants(record, event):
        event_id = str(event["id"])
        if event_id in {str(x) for x in (record.get("muted_event_ids") or [])}:
            return False
        if event_id in {str(x) for x in (record.get("subscribed_event_ids") or [])}:
            return True
        return bool(record.get(f'{event["type"]}_notifications', False))

    async def _notify_event(self, event, lead_days, now):
        target = float(event["timestamp"])
        lead_seconds = max(0.0, float(lead_days)) * 86400.0
        target_time = target - lead_seconds
        if abs(now - target_time) > 90:
            return

        async for record in self.bot.db.notification_preferences.find({}):
            if not self._wants(record, event):
                continue
            selected_days = self._lead_days(record, event)
            if float(lead_days) > 0 and abs(selected_days - float(lead_days)) > 0.001:
                continue
            user_id = str(record.get("_id", ""))
            if not user_id.isdigit():
                continue
            delivery_id = f"{user_id}:{event['id']}:{lead_days:g}"
            claimed = await self.bot.db.notification_deliveries.update_one(
                {"_id": delivery_id},
                {"$setOnInsert": {"created_at": now, "event_id": event["id"], "user_id": user_id, "lead_days": float(lead_days)}},
                upsert=True,
            )
            if not claimed.upserted_id:
                continue
            try:
                user = self.bot.get_user(int(user_id)) or await self.bot.fetch_user(int(user_id))
                when = "is happening now" if lead_days <= 0 else (f"is coming up in {lead_days:g} day" + ("." if lead_days == 1 else "s."))
                icon = "🏎️" if event["type"] == "gauntlet" else "🏆"
                embed = discord.Embed(
                    title=f"{icon} RSL Calendar Reminder",
                    description=f"**{event['title']}** {when}.",
                    color=0x19D3FF if event["type"] == "gauntlet" else 0x7C4DFF,
                )
                embed.add_field(name="Server", value=str(event.get("guild_name") or "Racing Syndicate League"), inline=True)
                embed.add_field(name="When", value=f"<t:{int(target)}:F>\n<t:{int(target)}:R>", inline=True)
                embed.add_field(name="Calendar", value="Open the RSL Calendar to manage this notification.", inline=False)
                embed.set_footer(text="Manage notification preferences anytime from your RSL profile.")
                await user.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                # A closed DM is not a reason to retry the same notification forever.
                pass

    @tasks.loop(seconds=60)
    async def notification_loop(self):
        now = time.time()
        try:
            events = await self._calendar_events()
            for event in events:
                for record in await self.bot.db.notification_preferences.find({}).to_list(length=None):
                    if not self._wants(record, event):
                        continue
                    lead_days = self._lead_days(record, event)
                    # Send the selected lead-time reminder and the event-time reminder.
                    await self._notify_event(event, lead_days, now)
                    if lead_days > 0:
                        await self._notify_event(event, 0, now)
        except Exception:
            # Keep the background scheduler alive if one malformed event or
            # transient database/Discord failure occurs.
            pass

    @notification_loop.before_loop
    async def before_notification_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(NotificationCog(bot))
