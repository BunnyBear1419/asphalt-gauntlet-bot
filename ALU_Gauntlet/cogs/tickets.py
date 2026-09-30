"""RSL Discord Ticket Center.

Discord is the conversation surface; MongoDB is the canonical case/history store.
The web admin dashboard configures panels, teams, automation and reviews cases.
"""
from __future__ import annotations

import io
import time
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..core.core import bot, check_admin_privileges, audit_admin_action

DEFAULT_TYPES = [
    {"key": "support", "label": "General Support", "emoji": "🎫", "description": "Website, account, or general RSL help.", "priority": "normal"},
    {"key": "dispute", "label": "Match / Dispute", "emoji": "⚖️", "description": "Gauntlet, tournament, result, or fairness dispute.", "priority": "high"},
    {"key": "integrity", "label": "Report / Integrity", "emoji": "🚨", "description": "Report suspected cheating, abuse, or suspicious activity.", "priority": "urgent"},
    {"key": "technical", "label": "Technical Issue", "emoji": "🛠️", "description": "Website, bot, login, or notification issue.", "priority": "normal"},
    {"key": "economy", "label": "Economy Issue", "emoji": "💰", "description": "Credits, XP, tickets, rewards, or ledger issue.", "priority": "normal"},
    {"key": "tournament", "label": "Tournament Issue", "emoji": "🏆", "description": "Tournament registration, bracket, or result issue.", "priority": "high"},
]
DEFAULT_QUESTIONS = {
    "support": ["What do you need help with?", "What have you already tried?"],
    "dispute": ["Match/tournament ID or opponent:", "What happened?", "Evidence links or attachments:"],
    "integrity": ["Who/what are you reporting?", "What happened?", "Evidence links or attachments:"],
    "technical": ["What is broken?", "What device/browser are you using?", "What error did you see?"],
    "economy": ["What transaction/reward is affected?", "What should your balance have been?", "Evidence or transaction details:"],
    "tournament": ["Tournament name/ID:", "What happened?", "Evidence or result details:"],
}

async def settings_for(guild_id: str) -> dict:
    doc = await bot.db.rsl_ticket_settings.find_one({"_id": str(guild_id)}) or {}
    types = doc.get("types") or DEFAULT_TYPES
    return {
        "enabled": doc.get("enabled", True),
        "panel_channel_id": str(doc.get("panel_channel_id") or ""),
        "transcript_channel_id": str(doc.get("transcript_channel_id") or ""),
        "closed_category_id": str(doc.get("closed_category_id") or ""),
        "default_category_id": str(doc.get("default_category_id") or ""),
        "staff_role_ids": [str(x) for x in doc.get("staff_role_ids") or []],
        "max_open_per_user": max(1, min(10, int(doc.get("max_open_per_user", 2) or 2))),
        "auto_close_hours": max(0, min(720, int(doc.get("auto_close_hours", 168) or 168))),
        "reminder_hours": max(0, min(168, int(doc.get("reminder_hours", 24) or 24))),
        "sla_minutes": max(0, min(10080, int(doc.get("sla_minutes", 60) or 60))),
        "types": types[:25],
    }

async def ensure_defaults(guild_id: str) -> dict:
    current = await settings_for(guild_id)
    await bot.db.rsl_ticket_settings.update_one(
        {"_id": str(guild_id)},
        {"$setOnInsert": {"types": DEFAULT_TYPES, "enabled": True, "max_open_per_user": 2, "auto_close_hours": 168, "reminder_hours": 24, "sla_minutes": 60}},
        upsert=True,
    )
    return await settings_for(guild_id)

async def log_event(guild_id: str, ticket_id: str, event: str, actor_id: str | None = None, details: dict | None = None):
    await bot.db.rsl_ticket_events.insert_one({
        "guild_id": str(guild_id), "ticket_id": str(ticket_id), "event": event,
        "actor_id": str(actor_id) if actor_id else "system",
        "details": details or {}, "timestamp": time.time(),
    })

def is_staff(member: discord.Member, settings: dict) -> bool:
    if member.guild_permissions.administrator:
        return True
    role_ids = {str(r.id) for r in member.roles}
    return bool(role_ids.intersection(set(settings.get("staff_role_ids") or [])))

async def ticket_type(guild_id: str, key: str) -> dict | None:
    settings = await settings_for(guild_id)
    return next((x for x in settings["types"] if str(x.get("key")) == key), None)

class TicketModal(discord.ui.Modal):
    def __init__(self, cog: "TicketCog", guild_id: str, ticket_key: str, questions: list[str]):
        super().__init__(title=(awaitable_title(ticket_key)))
        self.cog = cog
        self.guild_id = guild_id
        self.ticket_key = ticket_key
        self.inputs = []
        for index, question in enumerate(questions[:5]):
            field = discord.ui.TextInput(
                label=str(question)[:45] or f"Question {index + 1}",
                custom_id=f"q{index}",
                style=discord.TextStyle.paragraph if len(str(question)) > 35 else discord.TextStyle.short,
                required=True,
                max_length=1000,
            )
            self.inputs.append(field)
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction):
        answers = {str(q.label): str(q.value).strip() for q in self.inputs}
        await self.cog.open_ticket(interaction, self.guild_id, self.ticket_key, answers)

def awaitable_title(key: str) -> str:
    names = {"support": "RSL Support Request", "dispute": "RSL Dispute Request", "integrity": "RSL Integrity Report", "technical": "RSL Technical Issue", "economy": "RSL Economy Issue", "tournament": "RSL Tournament Issue"}
    return names.get(key, "RSL Support Request")

class TicketTypeSelect(discord.ui.Select):
    def __init__(self, cog: "TicketCog", types: list[dict]):
        options = [
            discord.SelectOption(label=str(x.get("label") or x.get("key"))[:100], value=str(x.get("key"))[:100], description=str(x.get("description") or "")[:100], emoji=x.get("emoji") or None)
            for x in types[:25]
        ]
        super().__init__(placeholder="Choose what you need help with…", min_values=1, max_values=1, options=options, custom_id="rsl_ticket:type_select")
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        key = self.values[0]
        t = await ticket_type(str(interaction.guild_id), key)
        if not t:
            await interaction.response.send_message("That ticket type is no longer available.", ephemeral=True)
            return
        questions = t.get("questions") or DEFAULT_QUESTIONS.get(key) or ["What can we help you with?"]
        await interaction.response.send_modal(TicketModal(self.cog, str(interaction.guild_id), key, questions))

class TicketPanelView(discord.ui.View):
    def __init__(self, cog: "TicketCog", types: list[dict]):
        super().__init__(timeout=None)
        self.add_item(TicketTypeSelect(cog, types))

class TicketActions(discord.ui.View):
    def __init__(self, cog: "TicketCog", ticket_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.ticket_id = ticket_id

    @discord.ui.button(label="Claim", emoji="🙋", style=discord.ButtonStyle.primary, custom_id="rsl_ticket:claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.claim(interaction, self.ticket_id)

    @discord.ui.button(label="Priority", emoji="🔴", style=discord.ButtonStyle.secondary, custom_id="rsl_ticket:priority")
    async def priority(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.cycle_priority(interaction, self.ticket_id)

    @discord.ui.button(label="Close", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="rsl_ticket:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.close(interaction, self.ticket_id)

class TicketCog(commands.Cog):
    def __init__(self, bot_instance):
        self.bot = bot_instance
        self.autoclose_loop.start()

    def cog_unload(self):
        self.autoclose_loop.cancel()

    async def open_ticket(self, interaction: discord.Interaction, guild_id: str, key: str, answers: dict):
        if not interaction.guild:
            return
        settings = await settings_for(guild_id)
        if not settings["enabled"]:
            await interaction.response.send_message("🎫 Ticket support is temporarily unavailable.", ephemeral=True)
            return
        existing = await self.bot.db.rsl_tickets.count_documents({"guild_id": guild_id, "user_id": str(interaction.user.id), "status": {"$in": ["open", "assigned", "investigating", "awaiting_player", "escalated"]}})
        if existing >= settings["max_open_per_user"]:
            await interaction.response.send_message(f"⚠️ You already have {existing} open ticket(s).", ephemeral=True)
            return
        t = await ticket_type(guild_id, key)
        if not t:
            await interaction.response.send_message("Ticket type unavailable.", ephemeral=True)
            return
        category = interaction.guild.get_channel(int(t.get("category_id") or settings.get("default_category_id") or 0)) if (t.get("category_id") or settings.get("default_category_id")) else None
        staff_ids = [str(x) for x in (t.get("staff_role_ids") or settings.get("staff_role_ids") or [])]
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True),
        }
        for rid in staff_ids:
            role = interaction.guild.get_role(int(rid))
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True)
        channel_name = f"ticket-{str(interaction.user.name).lower().replace(' ', '-')[:18]}-{int(time.time()) % 100000:05d}"
        channel = await interaction.guild.create_text_channel(channel_name, category=category if isinstance(category, discord.CategoryChannel) else None, overwrites=overwrites, reason="RSL ticket created")
        now = time.time()
        doc = {
            "guild_id": guild_id, "channel_id": str(channel.id), "user_id": str(interaction.user.id),
            "type": key, "status": "open", "priority": str(t.get("priority") or "normal"),
            "claimed_by": None, "participants": [str(interaction.user.id)], "answers": answers,
            "created_at": now, "updated_at": now, "message_id": None, "first_response_at": None, "closed_at": None,
            "close_reason": None, "last_user_message_at": now, "last_staff_message_at": None,
        }
        result = await self.bot.db.rsl_tickets.insert_one(doc)
        ticket_id = str(result.inserted_id)
        await log_event(guild_id, ticket_id, "created", str(interaction.user.id), {"type": key, "channel_id": str(channel.id)})
        embed = discord.Embed(title=f"{t.get('emoji','🎫')} {t.get('label','Support')} • #{ticket_id[-6:]}", description="Your private RSL support case is open. A staff member will assist you here.", color=discord.Color.blurple())
        embed.add_field(name="Status", value="🟢 Open", inline=True)
        embed.add_field(name="Priority", value=str(doc["priority"]).title(), inline=True)
        for question, answer in answers.items():
            embed.add_field(name=str(question)[:256], value=str(answer)[:1024], inline=False)
        sent = await channel.send(content=interaction.user.mention, embed=embed, view=TicketActions(self, ticket_id))
        await interaction.response.send_message(f"🎫 Your ticket is ready: {channel.mention}", ephemeral=True)

    async def _staff_check(self, interaction: discord.Interaction) -> tuple[bool, dict]:
        settings = await settings_for(str(interaction.guild_id))
        return bool(interaction.guild and is_staff(interaction.user, settings)), settings

    async def claim(self, interaction: discord.Interaction, ticket_id: str):
        ok, settings = await self._staff_check(interaction)
        if not ok:
            await interaction.response.send_message("Staff access required.", ephemeral=True); return
        updated = await self.bot.db.rsl_tickets.update_one({"_id": __import__("bson").ObjectId(ticket_id), "status": {"$in": ["open", "awaiting_player", "escalated"]}, "claimed_by": None}, {"$set": {"claimed_by": str(interaction.user.id), "status": "assigned", "updated_at": time.time()}})
        if not updated.modified_count:
            await interaction.response.send_message("This ticket is already claimed or closed.", ephemeral=True); return
        await log_event(str(interaction.guild_id), ticket_id, "claimed", str(interaction.user.id))
        await interaction.response.send_message(f"🙋 Ticket claimed by {interaction.user.mention}.", ephemeral=False)

    async def cycle_priority(self, interaction: discord.Interaction, ticket_id: str):
        ok, _ = await self._staff_check(interaction)
        if not ok:
            await interaction.response.send_message("Staff access required.", ephemeral=True); return
        row = await self.bot.db.rsl_tickets.find_one({"_id": __import__("bson").ObjectId(ticket_id)}) or {}
        order = ["low", "normal", "high", "urgent"]
        nxt = order[(order.index(str(row.get("priority") or "normal")) + 1) % len(order)] if str(row.get("priority")) in order else "normal"
        await self.bot.db.rsl_tickets.update_one({"_id": row["_id"]}, {"$set": {"priority": nxt, "updated_at": time.time()}})
        await log_event(str(interaction.guild_id), ticket_id, "priority_changed", str(interaction.user.id), {"priority": nxt})
        await interaction.response.send_message(f"Priority changed to **{nxt.upper()}**.", ephemeral=False)

    async def close(self, interaction: discord.Interaction, ticket_id: str):
        ok, _ = await self._staff_check(interaction)
        if not ok:
            await interaction.response.send_message("Staff access required.", ephemeral=True); return
        await self._close_ticket(interaction.guild_id, ticket_id, str(interaction.user.id), "staff_closed")
        await interaction.response.send_message("🔒 Ticket closed and archived.", ephemeral=False)

    async def _close_ticket(self, guild_id, ticket_id, actor_id, reason):
        from bson import ObjectId
        row = await self.bot.db.rsl_tickets.find_one({"_id": ObjectId(ticket_id)})
        if not row or row.get("status") == "closed":
            return False
        channel = self.bot.get_channel(int(row.get("channel_id", 0)))
        now = time.time()
        await self.bot.db.rsl_tickets.update_one({"_id": row["_id"]}, {"$set": {"status": "closed", "closed_at": now, "updated_at": now, "close_reason": reason}})
        await log_event(str(guild_id), ticket_id, "closed", actor_id, {"reason": reason})
        if channel:
            try:
                await channel.send("🔒 This ticket is now closed. Staff can reopen it from the Admin Ticket Center.")
                await channel.edit(name=f"closed-{channel.name}"[:90])
                await channel.set_permissions(channel.guild.default_role, view_channel=False)
                member = channel.guild.get_member(int(row["user_id"]))
                if member:
                    await channel.set_permissions(member, view_channel=True, send_messages=False, read_message_history=True)
                settings = await settings_for(str(guild_id))
                closed_cat = channel.guild.get_channel(int(settings["closed_category_id"])) if settings["closed_category_id"] else None
                if isinstance(closed_cat, discord.CategoryChannel):
                    await channel.edit(category=closed_cat)
            except Exception:
                pass
        return True

    async def reopen(self, guild_id: str, ticket_id: str, actor_id: str):
        from bson import ObjectId
        row = await self.bot.db.rsl_tickets.find_one({"_id": ObjectId(ticket_id)})
        if not row or row.get("status") != "closed":
            return False
        channel = self.bot.get_channel(int(row.get("channel_id", 0)))
        if not channel:
            return False
        await self.bot.db.rsl_tickets.update_one({"_id": row["_id"]}, {"$set": {"status": "open", "closed_at": None, "close_reason": None, "updated_at": time.time()}})
        await log_event(str(guild_id), ticket_id, "reopened", actor_id)
        await channel.set_permissions(channel.guild.default_role, view_channel=False)
        member = channel.guild.get_member(int(row["user_id"]))
        if member:
            await channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True, attach_files=True)
        await channel.send("♻️ This ticket has been reopened.")
        return True

    @tasks.loop(minutes=5)
    async def autoclose_loop(self):
        await self.bot.wait_until_ready()
        now = time.time()
        for guild in self.bot.guilds:
            settings = await settings_for(str(guild.id))
            if not settings["auto_close_hours"]:
                continue
            cutoff = now - settings["auto_close_hours"] * 3600
            cursor = self.bot.db.rsl_tickets.find({"guild_id": str(guild.id), "status": {"$in": ["open", "assigned", "awaiting_player", "investigating"]}, "updated_at": {"$lt": cutoff}})
            async for row in cursor:
                await self._close_ticket(str(guild.id), str(row["_id"]), "system", "auto_close_inactive")

    @app_commands.guild_only()
    @app_commands.command(name="ticket", description="[Staff] Manage the current RSL ticket.")
    @app_commands.describe(action="Action: claim, close, reopen, priority", ticket_id="Ticket ID for admin actions")
    async def ticket_cmd(self, interaction: discord.Interaction, action: str, ticket_id: str | None = None):
        settings = await settings_for(str(interaction.guild_id))
        if action.lower() in {"claim", "close", "priority"}:
            if not await check_admin_privileges(interaction):
                await interaction.response.send_message("Staff access required.", ephemeral=True); return
        if action.lower() == "claim":
            await self.claim(interaction, ticket_id or "")
        elif action.lower() == "close":
            await self.close(interaction, ticket_id or "")
        elif action.lower() == "reopen":
            if not await check_admin_privileges(interaction):
                await interaction.response.send_message("Admin access required.", ephemeral=True); return
            ok = await self.reopen(str(interaction.guild_id), ticket_id or "", str(interaction.user.id))
            await interaction.response.send_message("♻️ Reopened." if ok else "Ticket could not be reopened.", ephemeral=True)
        elif action.lower() == "priority":
            await self.cycle_priority(interaction, ticket_id or "")
        else:
            await interaction.response.send_message("Use claim, close, reopen, or priority.", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name="ticketpanel", description="[Staff] Post the RSL ticket panel in this channel.")
    async def ticket_panel_cmd(self, interaction: discord.Interaction):
        if not await check_admin_privileges(interaction):
            await interaction.response.send_message("Staff access required.", ephemeral=True); return
        settings = await settings_for(str(interaction.guild_id))
        embed = discord.Embed(title="🎫 RACING SYNDICATE LEAGUE • SUPPORT CENTER", description="Choose the type of help you need below. Your ticket will be private to you and the appropriate RSL support team.", color=discord.Color.blurple())
        await interaction.channel.send(embed=embed, view=TicketPanelView(self, settings["types"]))
        await interaction.response.send_message("Ticket panel posted.", ephemeral=True)

async def setup(bot_instance):
    cog = TicketCog(bot_instance)
    await bot_instance.add_cog(cog)
    bot_instance.add_view(TicketPanelView(cog, DEFAULT_TYPES))
