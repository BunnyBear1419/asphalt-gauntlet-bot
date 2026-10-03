import re
import base64
import aiohttp
from bson import ObjectId
from discord.ext import commands
from discord import app_commands
from ..core.core import *
from ..core.rsl_activity import activity_level
from .ticket_economy import BuyTicketView
from .translation import localize_text


async def _club_image_data(image_url: str) -> str:
    """Download and normalize an optional club image for the shared club schema."""
    image_url = str(image_url or "").strip()
    if not image_url:
        return ""
    if not image_url.lower().startswith(("http://", "https://")):
        raise ValueError("Club picture must be an http:// or https:// URL.")
    timeout = aiohttp.ClientTimeout(total=8)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(image_url, allow_redirects=True) as response:
            if response.status != 200:
                raise ValueError("Club picture could not be downloaded.")
            content_type = str(response.headers.get("Content-Type", "")).lower().split(";", 1)[0]
            if content_type not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
                raise ValueError("Club picture must be PNG, JPG, WEBP, or GIF.")
            data = await response.read()
    if len(data) > 3_000_000:
        raise ValueError("Club picture must be 3 MB or smaller.")
    return f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"


def _club_links(value: str) -> list[str]:
    links = []
    for raw in str(value or "").replace("\n", ",").split(",")[:5]:
        link = raw.strip()
        if not link:
            continue
        if not link.lower().startswith(("http://", "https://")):
            raise ValueError("Club links must begin with http:// or https://.")
        links.append(link[:300])
    return links


async def _recount_club_members(club_id: str, guild_id: str) -> int:
    guild_id = str(guild_id)
    count = await bot.db.club_members.count_documents({"club_id": str(club_id), "guild_id": guild_id})
    await bot.db.clubs.update_one(
        {"_id": ObjectId(str(club_id)), "guild_id": guild_id},
        {"$set": {"member_count": count, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return count


async def _club_for_user(guild_id: str, user_id: str):
    member = await bot.db.club_members.find_one({"guild_id": guild_id, "user_id": user_id})
    if not member:
        return None, None
    club = await bot.db.clubs.find_one({"_id": ObjectId(str(member["club_id"])), "guild_id": guild_id})
    return club, member


async def _club_embed(guild_id: str, user_id: str) -> discord.Embed:
    club, membership = await _club_for_user(guild_id, user_id)
    if not club:
        clubs = await bot.db.clubs.find({"guild_id": guild_id}).sort("name_ci", 1).to_list(length=25)
        lines = [
            f"• **{c.get('name', 'Club')}** — {int(c.get('member_count', 0) or 0)}/20 drivers"
            for c in clubs
        ]
        description = (
            "You are not in a club yet.\n\n"
            + ("\n".join(lines) if lines else "No clubs have been created in this server yet.")
            + "\n\nUse **Create Club** or select a club below to join."
        )
        return discord.Embed(title="🏎️ RSL CLUB CENTER", description=description[:4096], color=ASPHALT_THEME_COLOR)

    members = await bot.db.club_members.find({"club_id": str(club["_id"]), "guild_id": guild_id}).sort("joined_at", 1).to_list(length=20)
    wins = int(club.get("tournament_wins", 0) or 0)
    losses = int(club.get("tournament_losses", 0) or 0)
    role = str(membership.get("role", "member")).upper()
    lines = []
    for m in members:
        marker = " 👑" if str(m.get("user_id")) == str(club.get("leader_id")) else ""
        lines.append(f"• <@{m.get('user_id')}> — {str(m.get('role', 'member')).title()}{marker}")
    embed = discord.Embed(
        title=f"🏎️ {club.get('name', 'RSL Club')}",
        description=str(club.get("about") or "No club description has been added yet."),
        color=ASPHALT_THEME_COLOR,
    )
    embed.add_field(name="Club Record", value=f"**{wins}-{losses}**\n{int(club.get('member_count', len(members)) or len(members))}/20 drivers", inline=True)
    embed.add_field(name="Your Role", value=f"**{role.title()}**", inline=True)
    embed.add_field(name="Roster", value="\n".join(lines)[:1024] if lines else "No members found.", inline=False)
    if club.get("discord"):
        embed.add_field(name="Club Discord", value=str(club["discord"])[:1024], inline=False)
    embed.set_footer(text="RSL Club Center • Website and Discord use the same club records")
    return embed


class CreateClubModal(discord.ui.Modal, title="Create RSL Club"):
    name = discord.ui.TextInput(label="Club Name", max_length=40, required=True, placeholder="Night Racers")
    about = discord.ui.TextInput(label="About the Club", style=discord.TextStyle.paragraph, max_length=500, required=False, placeholder="Tell drivers what your club is about.")
    discord_link = discord.ui.TextInput(label="Club Discord Link", max_length=300, required=False, placeholder="https://discord.gg/...")
    links = discord.ui.TextInput(label="Club Links (comma-separated, up to 5)", max_length=1200, required=False, placeholder="https://..., https://...")
    image_url = discord.ui.TextInput(label="Club Picture URL", max_length=500, required=False, placeholder="https://.../club-picture.png")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id, user_id = str(interaction.guild_id), str(interaction.user.id)
        if await bot.db.club_members.find_one({"guild_id": guild_id, "user_id": user_id}):
            await interaction.followup.send(
                await localize_text(bot, interaction.user.id, "❌ You are already in a club in this server.", interaction.locale),
                ephemeral=True
            )
            return
        name = str(self.name.value).strip()
        if not name:
            await interaction.followup.send(
                await localize_text(bot, interaction.user.id, "❌ Club name is required.", interaction.locale),
                ephemeral=True
            )
            return
        if await bot.db.clubs.find_one({"guild_id": guild_id, "name_ci": name.casefold()}):
            await interaction.followup.send(
                await localize_text(bot, interaction.user.id, "❌ That club name is already taken.", interaction.locale),
                ephemeral=True
            )
            return
        discord_link = str(self.discord_link.value or "").strip()
        if discord_link and not discord_link.lower().startswith(("http://", "https://")):
            await interaction.followup.send(
                await localize_text(bot, interaction.user.id, "❌ Club Discord link must begin with http:// or https://.", interaction.locale),
                ephemeral=True
            )
            return
        try:
            links = _club_links(self.links.value)
            image = await _club_image_data(self.image_url.value)
        except ValueError as exc:
            await interaction.followup.send(
                await localize_text(bot, interaction.user.id, f"❌ {exc}", interaction.locale),
                ephemeral=True
            )
            return
        now = datetime.now(timezone.utc).isoformat()
        doc = {"guild_id": guild_id, "name": name, "name_ci": name.casefold(), "about": str(self.about.value or "").strip()[:500], "discord": discord_link[:300], "links": links, "image": image, "leader_id": user_id, "member_count": 1, "created_at": now, "updated_at": now}
        result = None
        try:
            result = await bot.db.clubs.insert_one(doc)
            await bot.db.club_members.insert_one({"club_id": str(result.inserted_id), "guild_id": guild_id, "user_id": user_id, "username": str(interaction.user.global_name or interaction.user.name or user_id), "role": "leader", "joined_at": now})
        except Exception as exc:
            if result is not None:
                await bot.db.clubs.delete_one({"_id": result.inserted_id, "guild_id": guild_id})
            await interaction.followup.send(
                await localize_text(bot, interaction.user.id, "❌ The club could not be created. No partial club was kept.", interaction.locale),
                ephemeral=True
            )
            return
        await interaction.followup.send(
            await localize_text(bot, interaction.user.id, "✅ Club created.", interaction.locale),
            embed=await _club_embed(guild_id, user_id),
            ephemeral=True
        )


class EditClubModal(discord.ui.Modal, title="Edit RSL Club"):
    name = discord.ui.TextInput(label="Club Name", max_length=40, required=True)
    about = discord.ui.TextInput(label="About the Club", style=discord.TextStyle.paragraph, max_length=500, required=False)
    discord_link = discord.ui.TextInput(label="Club Discord Link", max_length=300, required=False)
    links = discord.ui.TextInput(label="Club Links (comma-separated, up to 5)", max_length=1200, required=False)
    image_url = discord.ui.TextInput(label="Club Picture URL", max_length=500, required=False, placeholder="Leave blank to keep current picture")

    def __init__(self, club):
        super().__init__()
        self.club = club
        self.name.default = str(club.get("name", ""))[:40]
        self.about.default = str(club.get("about", ""))[:500]
        self.discord_link.default = str(club.get("discord", ""))[:300]
        self.links.default = ", ".join(str(x) for x in (club.get("links") or [])[:5])[:1200]

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id, user_id = str(interaction.guild_id), str(interaction.user.id)
        club = await bot.db.clubs.find_one({"_id": self.club["_id"], "guild_id": guild_id})
        if not club or str(club.get("leader_id")) != user_id:
            await interaction.followup.send(
                await localize_text(bot, interaction.user.id, "❌ Only the club leader can edit this club.", interaction.locale),
                ephemeral=True
            )
            return
        name = str(self.name.value).strip()
        duplicate = await bot.db.clubs.find_one({"_id": {"$ne": club["_id"]}, "guild_id": guild_id, "name_ci": name.casefold()})
        if not name or duplicate:
            await interaction.followup.send(
                await localize_text(bot, interaction.user.id, "❌ Club name is empty or already taken.", interaction.locale),
                ephemeral=True
            )
            return
        discord_link = str(self.discord_link.value or "").strip()
        if discord_link and not discord_link.lower().startswith(("http://", "https://")):
            await interaction.followup.send(
                await localize_text(bot, interaction.user.id, "❌ Club Discord link must begin with http:// or https://.", interaction.locale),
                ephemeral=True
            )
            return
        try:
            links = _club_links(self.links.value)
            image = await _club_image_data(self.image_url.value) if str(self.image_url.value or "").strip() else str(club.get("image", ""))
        except ValueError as exc:
            await interaction.followup.send(
                await localize_text(bot, interaction.user.id, f"❌ {exc}", interaction.locale),
                ephemeral=True
            )
            return
        await bot.db.clubs.update_one({"_id": club["_id"], "guild_id": guild_id, "leader_id": user_id}, {"$set": {"name": name, "name_ci": name.casefold(), "about": str(self.about.value or "").strip()[:500], "discord": discord_link[:300], "links": links, "image": image, "updated_at": datetime.now(timezone.utc).isoformat()}})
        await interaction.followup.send(
            await localize_text(bot, interaction.user.id, "✅ Club profile updated.", interaction.locale),
            embed=await _club_embed(guild_id, user_id),
            ephemeral=True
        )


class ClubMemberSelect(discord.ui.Select):
    def __init__(self, members):
        options = [discord.SelectOption(label=str(m.get("username") or m.get("user_id"))[:100], value=str(m.get("user_id")), description=str(m.get("role", "member")).title()[:100]) for m in members[:20]]
        super().__init__(placeholder="Select a club member", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, ClubMemberActionView):
            return
        view.target_user_id = str(self.values[0])
        await interaction.response.edit_message(embed=view.action_embed(), view=view)


class ClubMemberActionView(discord.ui.View):
    def __init__(self, club, owner_id, owner_role="leader"):
        super().__init__(timeout=900)
        self.club = club
        self.owner_id = str(owner_id)
        self.owner_role = str(owner_role or "member").casefold()
        self.target_user_id = None

    def action_embed(self):
        target = self.target_user_id or "No member selected"
        return discord.Embed(title=f"🛠️ MANAGE {self.club.get('name', 'CLUB')}", description=f"Selected member: <@{target}>\nChoose an action below.", color=ASPHALT_ADMIN_COLOR)

    async def apply(self, interaction, action):
        if str(interaction.user.id) != self.owner_id:
            await interaction.response.send_message(
                await localize_text(bot, interaction.user.id, "❌ This control belongs to another player session.", interaction.locale),
                ephemeral=True
            )
            return
        if not self.target_user_id:
            await interaction.response.send_message(
                await localize_text(bot, interaction.user.id, "❌ Select a member first.", interaction.locale),
                ephemeral=True
            )
            return
        if str(self.target_user_id) == str(self.club.get("leader_id")):
            await interaction.response.send_message(
                await localize_text(bot, interaction.user.id, "❌ The club leader cannot be changed from this control.", interaction.locale),
                ephemeral=True
            )
            return
        member = await bot.db.club_members.find_one({"club_id": str(self.club["_id"]), "guild_id": str(self.club.get("guild_id")), "user_id": self.target_user_id})
        if not member:
            await interaction.response.send_message(
                await localize_text(bot, interaction.user.id, "❌ Club member not found.", interaction.locale),
                ephemeral=True
            )
            return
        target_role = str(member.get("role", "member")).casefold()
        if action == "kick":
            if target_role == "officer" and self.owner_role != "leader":
                await localize_text(bot, interaction.user.id, "❌ Officers cannot kick another Officer.", interaction.locale)
                return
            await bot.db.club_members.delete_one({"_id": member["_id"], "club_id": str(self.club["_id"]), "guild_id": str(self.club.get("guild_id"))})
            await _recount_club_members(str(self.club["_id"]), str(self.club.get("guild_id")))
            message = "✅ Member removed from the club."
        elif action == "promote":
            if self.owner_role != "leader":
                await localize_text(bot, interaction.user.id, "❌ Only the club leader can promote members to Officer.", interaction.locale)
                return
            await bot.db.club_members.update_one({"_id": member["_id"]}, {"$set": {"role": "officer"}})
            message = "✅ Member promoted to Officer."
        elif action == "demote":
            if self.owner_role != "leader":
                await localize_text(bot, interaction.user.id, "❌ Only the club leader can demote Officers.", interaction.locale)
                return
            await bot.db.club_members.update_one({"_id": member["_id"]}, {"$set": {"role": "member"}})
            message = "✅ Officer demoted to Member."
        else:
            message = "❌ Unsupported member action."
        await interaction.response.send_message(
            await localize_text(bot, interaction.user.id, message, interaction.locale),
            ephemeral=True
        )


class ClubCenterView(discord.ui.View):
    def __init__(self, guild_id, user_id, clubs, current_club=None, membership=None):
        super().__init__(timeout=900)
        self.guild_id = str(guild_id)
        self.user_id = str(user_id)
        self.clubs = clubs
        self.current_club = current_club
        self.membership = membership
        if not current_club and clubs:
            self.add_item(ClubPickerSelect(clubs))

    @discord.ui.button(label="Create Club", style=discord.ButtonStyle.success, emoji="🏁")
    async def create(self, interaction: discord.Interaction, button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                await localize_text(bot, interaction.user.id, "❌ This control belongs to another player session.", interaction.locale),
                ephemeral=True
            )
            return
        await interaction.response.send_modal(CreateClubModal())

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def refresh(self, interaction: discord.Interaction, button):
        await send_club_center(interaction, replace=True)

    @discord.ui.button(label="Leave Club", style=discord.ButtonStyle.danger, emoji="🚪")
    async def leave(self, interaction: discord.Interaction, button):
        if not self.current_club:
            await interaction.response.send_message(
                await localize_text(bot, interaction.user.id, "❌ You are not in a club.", interaction.locale),
                ephemeral=True
            )
            return
        if str(self.current_club.get("leader_id")) == self.user_id:
            await interaction.response.send_message(
                await localize_text(bot, interaction.user.id, "❌ Club leaders must transfer leadership before leaving.", interaction.locale),
                ephemeral=True
            )
            return
        result = await bot.db.club_members.delete_one({"club_id": str(self.current_club["_id"]), "guild_id": str(self.current_club.get("guild_id")), "user_id": self.user_id})
        if result.deleted_count:
            await _recount_club_members(str(self.current_club["_id"]))
        await send_club_center(interaction, replace=True)

    @discord.ui.button(label="Edit Club", style=discord.ButtonStyle.primary, emoji="✏️")
    async def edit(self, interaction: discord.Interaction, button):
        if not self.current_club or str(self.current_club.get("leader_id")) != self.user_id:
            await interaction.response.send_message(
                await localize_text(bot, interaction.user.id, "❌ Only the club leader can edit the club.", interaction.locale),
                ephemeral=True
            )
            return
        await interaction.response.send_modal(EditClubModal(self.current_club))

    @discord.ui.button(label="Manage Members", style=discord.ButtonStyle.primary, emoji="👥")
    async def manage(self, interaction: discord.Interaction, button):
        if not self.current_club or str((self.membership or {}).get("role", "")).casefold() not in {"leader", "officer"}:
            await interaction.response.send_message(
                await localize_text(bot, interaction.user.id, "❌ Only the club leader or an Officer can manage members.", interaction.locale),
                ephemeral=True
            )
            return
        members = await bot.db.club_members.find({"club_id": str(self.current_club["_id"])}).sort("joined_at", 1).to_list(length=20)
        members = [m for m in members if str(m.get("user_id")) != self.user_id]
        if not members:
            await interaction.response.send_message(
                await localize_text(bot, interaction.user.id, "ℹ️ There are no other club members to manage.", interaction.locale),
                ephemeral=True
            )
            return
        view = ClubMemberActionView(self.current_club, self.user_id, (self.membership or {}).get("role", "member"))
        view.add_item(ClubMemberSelect(members))
        class PromoteButton(discord.ui.Button):
            def __init__(self): super().__init__(label="Promote", style=discord.ButtonStyle.success, emoji="⬆️")
            async def callback(btn, inter): await view.apply(inter, "promote")
        class DemoteButton(discord.ui.Button):
            def __init__(self): super().__init__(label="Demote", style=discord.ButtonStyle.secondary, emoji="⬇️")
            async def callback(btn, inter): await view.apply(inter, "demote")
        class KickButton(discord.ui.Button):
            def __init__(self): super().__init__(label="Kick", style=discord.ButtonStyle.danger, emoji="🦵")
            async def callback(btn, inter): await view.apply(inter, "kick")
        if str((self.membership or {}).get("role", "")).casefold() == "leader":
            view.add_item(PromoteButton())
            view.add_item(DemoteButton())
        view.add_item(KickButton())
        await interaction.response.send_message(embed=view.action_embed(), view=view, ephemeral=True)


class ClubPickerSelect(discord.ui.Select):
    def __init__(self, clubs):
        options = [discord.SelectOption(label=str(c.get("name", "Club"))[:100], value=str(c.get("_id")), description=f"{int(c.get('member_count', 0) or 0)}/20 drivers"[:100]) for c in clubs[:25]]
        super().__init__(placeholder="Select a club to join", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if not self.view:
            return
        club_id = str(self.values[0])
        guild_id, user_id = str(interaction.guild_id), str(interaction.user.id)
        club = await bot.db.clubs.find_one({"_id": ObjectId(club_id), "guild_id": guild_id})
        if not club:
            await interaction.response.send_message(
                await localize_text(bot, interaction.user.id, "❌ Club not found.", interaction.locale),
                ephemeral=True
            )
            return
        if await bot.db.club_members.find_one({"guild_id": guild_id, "user_id": user_id}):
            await interaction.response.send_message(
                await localize_text(bot, interaction.user.id, "❌ You are already in a club in this server.", interaction.locale),
                ephemeral=True
            )
            return
        reservation = await bot.db.clubs.update_one({"_id": club["_id"], "guild_id": guild_id, "$or": [{"member_count": {"$lt": 20}}, {"member_count": {"$exists": False}}]}, {"$inc": {"member_count": 1}})
        if not reservation.modified_count:
            await interaction.response.send_message(
                await localize_text(bot, interaction.user.id, "❌ That club is full.", interaction.locale),
                ephemeral=True
            )
            return
        now = datetime.now(timezone.utc).isoformat()
        try:
            await bot.db.club_members.insert_one({"club_id": str(club["_id"]), "guild_id": guild_id, "user_id": user_id, "username": str(interaction.user.global_name or interaction.user.name or user_id), "role": "member", "joined_at": now})
        except Exception as exc:
            await bot.db.clubs.update_one({"_id": club["_id"], "guild_id": guild_id, "member_count": {"$gt": 0}}, {"$inc": {"member_count": -1}})
            if exc.__class__.__name__ == "DuplicateKeyError":
                await interaction.response.send_message(
                    await localize_text(bot, interaction.user.id, "❌ You are already in a club in this server.", interaction.locale),
                    ephemeral=True
                )
                return
            await interaction.response.send_message(
                await localize_text(bot, interaction.user.id, "❌ The club join failed; no partial membership was kept.", interaction.locale),
                ephemeral=True
            )
            return
        await send_club_center(interaction, replace=True)


async def send_club_center(interaction: discord.Interaction, replace: bool = False):
    guild_id, user_id = str(interaction.guild_id), str(interaction.user.id)
    club, membership = await _club_for_user(guild_id, user_id)
    clubs = [] if club else await bot.db.clubs.find({"guild_id": guild_id}).sort("name_ci", 1).to_list(length=25)
    embed = await _club_embed(guild_id, user_id)
    view = ClubCenterView(guild_id, user_id, clubs, club, membership)
    if replace and interaction.response.is_done():
        await interaction.edit_original_response(embed=embed, view=view)
    else:
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class ClubCenterButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Club Center", style=discord.ButtonStyle.primary, emoji="🏎️")

    async def callback(self, interaction: discord.Interaction):
        await send_club_center(interaction)


class DiscordNotificationSettingsView(discord.ui.View):
    """Discord-side calendar notification controls backed by the shared web preferences."""
    def __init__(self, user_id: str):
        super().__init__(timeout=600)
        self.user_id = str(user_id)

    async def _load(self):
        return await bot.db.notification_preferences.find_one({"_id": self.user_id}) or {}

    async def _toggle(self, interaction, field: str):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                await localize_text(bot, interaction.user.id, "❌ This notification panel belongs to another player.", interaction.locale),
                ephemeral=True
            )
            return
        record = await self._load()
        value = not bool(record.get(field, False))
        await bot.db.notification_preferences.update_one(
            {"_id": self.user_id},
            {"$set": {field: value, "updated_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
        await interaction.response.edit_message(embed=await build_notification_settings_embed(self.user_id), view=self)

    async def _set_digest(self, interaction, frequency: str):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                await localize_text(bot, interaction.user.id, "❌ This notification panel belongs to another player.", interaction.locale),
                ephemeral=True
            )
            return
        await bot.db.notification_preferences.update_one(
            {"_id": self.user_id},
            {"$set": {"digest_frequency": frequency, "digest_hour": 9, "guild_id": str(interaction.guild_id or ""), "updated_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
        await interaction.response.edit_message(embed=await build_notification_settings_embed(self.user_id), view=self)

    @discord.ui.button(label="Digest: Daily", style=discord.ButtonStyle.secondary, row=2)
    async def digest_daily(self, interaction, button):
        await self._set_digest(interaction, "daily")

    @discord.ui.button(label="Digest: Weekly", style=discord.ButtonStyle.secondary, row=2)
    async def digest_weekly(self, interaction, button):
        await self._set_digest(interaction, "weekly")

    @discord.ui.button(label="Digest: Off", style=discord.ButtonStyle.secondary, row=2)
    async def digest_off(self, interaction, button):
        await self._set_digest(interaction, "off")

    async def _set_lead(self, interaction, days: float):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                await localize_text(bot, interaction.user.id, "❌ This notification panel belongs to another player.", interaction.locale),
                ephemeral=True
            )
            return
        await bot.db.notification_preferences.update_one(
            {"_id": self.user_id},
            {"$set": {"gauntlet_lead_days": days, "tournament_lead_days": days, "updated_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
        await interaction.response.edit_message(embed=await build_notification_settings_embed(self.user_id), view=self)

    @discord.ui.button(label="Gauntlet: Toggle", style=discord.ButtonStyle.primary, row=0)
    async def gauntlet(self, interaction, button):
        await self._toggle(interaction, "gauntlet_notifications")

    @discord.ui.button(label="Tournament: Toggle", style=discord.ButtonStyle.primary, row=0)
    async def tournament(self, interaction, button):
        await self._toggle(interaction, "tournament_notifications")

    @discord.ui.button(label="7 Days", style=discord.ButtonStyle.secondary, row=1)
    async def seven(self, interaction, button):
        await self._set_lead(interaction, 7)

    @discord.ui.button(label="3 Days", style=discord.ButtonStyle.secondary, row=1)
    async def three(self, interaction, button):
        await self._set_lead(interaction, 3)

    @discord.ui.button(label="1 Day", style=discord.ButtonStyle.secondary, row=1)
    async def one(self, interaction, button):
        await self._set_lead(interaction, 1)

async def build_notification_settings_embed(user_id: str):
    record = await bot.db.notification_preferences.find_one({"_id": str(user_id)}) or {}
    g = "ON" if record.get("gauntlet_notifications") else "OFF"
    t = "ON" if record.get("tournament_notifications") else "OFF"
    lead = record.get("gauntlet_lead_days", record.get("tournament_lead_days", 1))
    try:
        lead_text = f"{float(lead):g} day(s) before"
    except (TypeError, ValueError):
        lead_text = "1 day before"
    return discord.Embed(
        title="🔔 RSL CALENDAR NOTIFICATIONS",
        description="Manage the same Discord DM notification preferences used by the RSL website Calendar. Optional daily/weekly digests bundle your RSL activity into one DM.",
        color=ASPHALT_THEME_COLOR,
    ).add_field(name="Gauntlet Reminders", value=f"**{g}**", inline=True).add_field(name="Tournament Reminders", value=f"**{t}**", inline=True).add_field(name="Reminder Lead Time", value=f"**{lead_text}**", inline=True).add_field(name="Activity Digest", value=f"**{str(record.get('digest_frequency', 'off')).title()}**", inline=True).set_footer(text="Personal calendar reminders remain available on the RSL website Calendar.")

class DiscordNotificationSettingsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Notifications", style=discord.ButtonStyle.secondary, emoji="🔔")
    async def callback(self, interaction):
        await interaction.response.send_message(embed=await build_notification_settings_embed(str(interaction.user.id)), view=DiscordNotificationSettingsView(str(interaction.user.id)), ephemeral=True)
class TicketEconomyButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Tickets & Coins", style=discord.ButtonStyle.secondary, emoji="🎟️")

    async def callback(self, interaction):
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)
        profile = await bot.db.drivers.find_one({"_id": f"{guild_id}_{user_id}"}) or {}
        today = await get_guild_local_date(guild_id)
        ticket_date = str(profile.get("gauntlet_ticket_date") or "")
        if ticket_date != today:
            free = 5
            purchased = 0
            total = 5
        else:
            free = int(profile.get("gauntlet_free_tickets", 0) or 0)
            purchased = int(profile.get("gauntlet_purchased_tickets", 0) or 0)
            total = int(profile.get("gauntlet_tickets", free + purchased) or 0)
        coins = int(profile.get("rsl_coins", 0) or 0)
        embed = discord.Embed(
            title="🎟️ RSL TICKETS & COINS",
            description=(
                f"**Tickets available:** {total}/10\n"
                f"**Free tickets:** {free}/5\n"
                f"**Purchased today:** {purchased}/5\n"
                f"**RSL Coins:** {coins:,}\n\n"
                "Unused tickets expire at the daily reset. Purchasing a ticket is atomic with its Coin debit."
            ),
            color=ASPHALT_THEME_COLOR,
        )
        embed.set_footer(text="RSL Economy • Daily ticket cycle")
        await interaction.response.send_message(
            embed=embed,
            view=BuyTicketView(bot, guild_id, user_id, get_guild_local_date),
            ephemeral=True,
        )

class AbandonGauntletButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Quit Active Match", style=discord.ButtonStyle.danger, emoji="🛑", row=4)

    async def callback(self, interaction):
        guild_id, user_id = str(interaction.guild_id), str(interaction.user.id)
        active = await bot.db.active_challenges.find_one({
            "_id": f"{guild_id}_{user_id}",
            "guild_id": guild_id,
            "challenger_id": user_id,
            "status": "active",
        })
        if not active:
            await interaction.response.send_message(
                await localize_text(bot, interaction.user.id, "ℹ️ You do not have an active Gauntlet match that can be quit.", interaction.locale),
                ephemeral=True,
                )
            return
        await interaction.response.defer(ephemeral=True)
        closed = await abandon_active_challenge(guild_id, user_id, "quit")
        if not closed:
            await interaction.followup.send(
                await localize_text(bot, interaction.user.id, "⚠️ This match changed state before the quit could be recorded. Refresh your dashboard.", interaction.locale),
                ephemeral=True,
                )
            return
        await interaction.followup.send(
            await localize_text(bot, interaction.user.id, "🛑 **Active Gauntlet match closed.** The match was marked abandoned and its consumed ticket was not restored.", interaction.locale),
            ephemeral=True,
            )

class RSLCommandCenterButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="RSL Command Center", style=discord.ButtonStyle.link, emoji="📊", url="https://asph.discloud.app/rsl-center")

async def send_dashboard(interaction: discord.Interaction):
    """Send the canonical player dashboard without removing player access for staff."""
    guild_id = str(interaction.guild_id)
    user_id = str(interaction.user.id)
    view = DashboardView(guild_id, user_id, False)
    view.add_item(ClubCenterButton())
    view.add_item(DiscordNotificationSettingsButton())
    view.add_item(RSLCommandCenterButton())
    view.add_item(TicketEconomyButton())
    view.add_item(AbandonGauntletButton())
    embed = discord.Embed(
        title='🏁 RACING SYNDICATE LEAGUE • PLAYER DASHBOARD',
        description='Race. Compete. Unite.\n\nUse the controls below to manage your driver profile, defense, challenges, rankings, and season activity.',
        color=ASPHALT_THEME_COLOR,
    )
    embed.set_footer(text='Player controls • Staff players retain full player access')
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# Player dashboard access is intentionally independent of staff permissions:
# staff/admin players keep the full player dashboard and gain /staff separately.
class PlayerCog(commands.Cog):

    @app_commands.guild_only()
    @app_commands.command(name='dashboard', description='Open your Racing Syndicate League player dashboard.')
    async def gauntlet_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        await send_dashboard(interaction)

    @app_commands.command(name='whatnext', description='Show your next required Gauntlet step.')
    async def whatnext_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        guild_id, user_id = (str(interaction.guild_id), str(interaction.user.id))
        season = await get_current_season_number(guild_id)
        p = await bot.db.drivers.find_one({'_id': f'{guild_id}_{user_id}'})
        if not p:
            msg = '1️⃣ Open `/dashboard` → **My Gauntlet** → **Register** to open the guided registration form'
        elif not p.get('season_registered') or int(p.get('season_number', 0)) != season:
            msg = f'1️⃣ Re-register for Season {season}: `/dashboard` → **My Gauntlet** → **Register**'
        elif not p.get('defense_locked'):
            msg = '1️⃣ Open `/dashboard` → **Defense** → **Set Defense**\n2️⃣ Complete the guided defense wizard'
        else:
            active = await bot.db.active_challenges.find_one({'_id': f'{guild_id}_{user_id}', 'guild_id': str(guild_id), 'status': {'$in': ['active', 'processing']}})
            msg = '1️⃣ Open `/dashboard` → **Challenges** → **Submit Match**' if active else "✅ You're ready — open `/dashboard` → **Challenges** → **Find Challenge**"
        await interaction.response.send_message(embed=discord.Embed(title='🏁 WHAT NEXT?', description=msg, color=ASPHALT_THEME_COLOR), ephemeral=True)

    @app_commands.command(name='profile', description='Inspects driver file card.')
    async def profile_cmd(self, interaction: discord.Interaction, driver: discord.Member=None):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        await interaction.response.defer()
        target_user = driver or interaction.user
        profile = await bot.db.drivers.find_one({'_id': f'{str(interaction.guild_id)}_{str(target_user.id)}'})
        if not profile:
            await interaction.followup.send('❌ Profile card missing. Open `/dashboard` → **My Gauntlet** → **Register** first.')
            return
        embed = discord.Embed(title='🏁 RACING SYNDICATE LEAGUE DRIVER DOSSIER CARD', color=ASPHALT_THEME_COLOR)
        embed.set_thumbnail(url=ASPHALT_MEDIA['thumb_profile'])
        matches = await bot.db.matches.find({
            'guild_id': str(interaction.guild_id),
            'reverted': {'$ne': True},
            '$or': [{'challenger_id': str(target_user.id)}, {'opponent_id': str(target_user.id)}],
        }).sort('timestamp', -1).to_list(length=1000)
        wins = sum(1 for m in matches if str(m.get('w_id')) == str(target_user.id))
        losses = sum(1 for m in matches if str(m.get('l_id')) == str(target_user.id))
        played = wins + losses
        win_rate = (wins / played * 100) if played else 0.0
        current_season = await get_current_season_number(str(interaction.guild_id))
        rank_cursor = bot.db.drivers.find({'guild_id': str(interaction.guild_id), 'season_registered': True, 'season_number': current_season}).sort('elo', -1)
        ranked = await rank_cursor.to_list(length=5000)
        rank = next((i + 1 for i, row in enumerate(ranked) if str(row.get('user_id')) == str(target_user.id)), None)
        lap_rows = await bot.db.lap_times.find({'guild_id': str(interaction.guild_id), 'user_id': str(target_user.id)}).sort('best_ms', 1).to_list(length=100)
        records = 0
        for row in lap_rows:
            record_id = re.sub(r'[^a-z0-9]+', '_', str(row.get('track', '')).lower()).strip('_')
            global_rec = await bot.db.map_records.find_one({'_id': record_id})
            if global_rec and str(global_rec.get('user_id')) == str(target_user.id) and int(global_rec.get('best_ms', 10**18)) == int(row.get('best_ms', -1)):
                records += 1
        recent = []
        for m in matches[:5]:
            result = '🏆 Win' if str(m.get('w_id')) == str(target_user.id) else '❌ Loss'
            recent.append(f"{result} • `{m.get('courses_beat', 0)}/5` • <t:{int(m.get('timestamp', now_ts()))}:R>")
        embed.add_field(name='👤 Pilot Credentials', value=f'• **User:** {target_user.mention}\n• **Game ID Node:** `{profile.get("game_id")}`', inline=True)
        embed.add_field(name='📊 Rating & Rank', value=f"**{int(profile.get('elo', 1000))} ELO**\nRank: **#{rank or '—'}**\n{get_division_for_pi(int(profile.get('garage_pi', 0)))['name']}\nSeason {current_season}", inline=True)
        activity_xp = int(profile.get('activity_xp', 0) or 0)
        activity_level_value = activity_level(activity_xp)
        rsl_coins = int(profile.get('rsl_coins', 0) or 0)
        embed.add_field(name='🪙 RSL Economy & Activity', value=f"**{rsl_coins:,} RSL Coins**\n⭐ Activity Level: **{activity_level_value}**\n✨ Activity XP: **{activity_xp:,}**", inline=True)
        dominance = profile.get("rsl_dominance") or {}
        buckets = dominance.get("score_buckets") or {}
        race_wins = int(dominance.get("race_wins", 0) or 0)
        race_losses = int(dominance.get("race_losses", 0) or 0)
        embed.add_field(name='📈 Career Performance', value=f"**{wins}-{losses}**\nWin rate: **{win_rate:.1f}%**\nMatches: `{played}`\n🔥 Streak: `{int(profile.get('streak', 0))}`\n🏆 Career wins: `{int(profile.get('career_wins', 0))}`\n🏁 Track records: `{records}`\n🏎️ Race record: `{race_wins}-{race_losses}`", inline=True)
        if dominance:
            embed.add_field(name='⚖️ Match Dominance', value=f"**5-0:** `{buckets.get("5-0", 0)}` • **4-1:** `{buckets.get("4-1", 0)}`\n**3-2:** `{buckets.get("3-2", 0)}` • **2-3:** `{buckets.get("2-3", 0)}`\n**1-4:** `{buckets.get("1-4", 0)}` • **0-5:** `{buckets.get("0-5", 0)}`", inline=True)
        if lap_rows:
            embed.add_field(name='⚡ Best Saved Laps', value='\n'.join(f"`{r.get('best_lap_time', '?')}` — {r.get('track', 'Unknown')}" for r in lap_rows[:5]), inline=False)
        if recent:
            embed.add_field(name='🏁 Recent Matches', value='\n'.join(recent), inline=False)
        if has_5_course_defense(profile):
            courses = profile['defense_locked'].get('courses', [])
            if courses:
                def_lines = ''
                for i, course in enumerate(courses):
                    def_lines += f"🏁 **Course {i + 1}:** `{course['track']}` | 🚗 `{course['car']}` | 📈 `{course.get('car_rank', 'N/A')}` | ⏱️ `{course['lap_time']}`\n"
                total_rank = get_car_rank_total(courses)
                def_lines += f'\n📊 **Total Car Performance Rating:** `{total_rank:,}`'
                embed.add_field(name='🛡️ Deployed Ghost Defense Framework', value=def_lines, inline=False)
        embed.set_footer(text='Profile & Stats • Use /dashboard → Competition → Season History for archived seasons', icon_url=target_user.display_avatar.url)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name='register', description='Open the guided Racing Syndicate League registration form.')
    async def register_launcher_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        await interaction.response.send_modal(RegistrationModal())

    @app_commands.command(name='mystatus', description='Check your current-season driver registration status.')
    async def my_status_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        await interaction.response.defer(ephemeral=True)
        guild_id, user_id = (str(interaction.guild_id), str(interaction.user.id))
        state = await bot.db.season_state.find_one({'_id': f'guild_{guild_id}'})
        season_number = int(state.get('season_number', 1)) if state else 1
        profile = await bot.db.drivers.find_one({'_id': f'{guild_id}_{user_id}'})
        if profile and profile.get('season_registered') and (int(profile.get('season_number', 0)) == season_number):
            division = get_division_for_pi(int(profile.get('garage_pi', 0)))['name']
            defense = profile.get('defense_locked')
            defense_status = '5-course defense locked' if has_5_course_defense(profile) else 'defense still needs to be set'
            await interaction.followup.send(
                await localize_text(bot, interaction.user.id, f"✅ **Season {season_number} Driver:** `{profile.get('elo', 1000)} ELO` / `{profile.get('garage_pi', 0):,} PI` → **{division}**. {defense_status}.", interaction.locale),
                ephemeral=True
            )
            return
        pending = await bot.db.pending.find_one({'_id': f'{guild_id}_{user_id}'})
        if pending and int(pending.get('season_number', season_number)) == season_number:
            division = get_division_for_pi(int(pending.get('rank', 0)))['name']
            await interaction.followup.send(
                await localize_text(bot, interaction.user.id, f"⏳ **Season {season_number} Pending Review:** Garage `{int(pending.get('rank', 0)):,} PI` → projected **{division}**. Staff approval is still required.", interaction.locale),
                ephemeral=True
            )
            return
        career = profile.get('career_wins', 0) if profile else 0
        played = profile.get('career_played', 0) if profile else 0
        await interaction.followup.send(
            await localize_text(bot, interaction.user.id, f'🔄 **Season {season_number} Re-Registration Required.** Your career record remains safe (`{career}` wins / `{played}` matches). Open `/dashboard` → **My Gauntlet** → **Register** with your current Garage PI to enter this season.', interaction.locale),
            ephemeral=True
        )

    @app_commands.command(name='delete_me', description='Permanently delete your Racing Syndicate League data from this server.')
    async def delete_me_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)
        profile = await bot.db.drivers.find_one({'_id': f'{guild_id}_{user_id}'})
        pending = await bot.db.pending.find_one({'_id': f'{guild_id}_{user_id}'})
        if not profile and (not pending):
            await interaction.response.send_message(
                await localize_text(bot, interaction.user.id, 'ℹ️ You do not have an active Racing Syndicate League record in this server.', interaction.locale),
                ephemeral=True
            )
            return
        await interaction.response.send_message(
            await localize_text(bot, interaction.user.id, '⚠️ **Permanently delete your Racing Syndicate League data?**\n\nThis removes your driver profile, current/past match records, active challenges, pending submissions, and your archived season-standing entries from **this server**. This cannot be undone.\n\nIf you join again, you will start as a new player.', interaction.locale),
            ephemeral=True
        )

async def setup(bot):
    await bot.add_cog(PlayerCog(bot))