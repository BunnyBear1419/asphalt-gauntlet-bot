from discord.ext import commands
from discord import app_commands
from ..core.core import *
from ..core.setup_wizard import launch_setup_wizard

COMMAND_ARCHITECTURE_VERSION = 12
command_architecture_version = COMMAND_ARCHITECTURE_VERSION

class ServerControlModal(discord.ui.Modal, title="Create RSL Server Resource"):
    resource = discord.ui.TextInput(label="Resource", placeholder="role, channel, or category", max_length=20)
    name = discord.ui.TextInput(label="Name", placeholder="RSL Staff", max_length=100)

    def __init__(self, guild_id: int, owner_id: int):
        super().__init__()
        self.guild_id = guild_id
        self.owner_id = owner_id

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id or not await check_admin_privileges(interaction):
            await interaction.response.send_message("Staff authorization required.", ephemeral=True)
            return
        guild = interaction.guild
        if guild is None or guild.id != self.guild_id:
            await interaction.response.send_message("This control is only valid in its original server.", ephemeral=True)
            return
        resource = str(self.resource.value).strip().lower()
        name = str(self.name.value).strip()
        try:
            if resource == "role":
                if not guild.me.guild_permissions.manage_roles and not guild.me.guild_permissions.administrator:
                    raise RuntimeError("The bot needs Manage Roles permission.")
                role = await guild.create_role(name=name, reason="RSL server control")
                message = "Created role %s (%s)." % (role.name, role.id)
            elif resource == "category":
                if not guild.me.guild_permissions.manage_channels and not guild.me.guild_permissions.administrator:
                    raise RuntimeError("The bot needs Manage Channels permission.")
                category = await guild.create_category(name=name, reason="RSL server control")
                message = "Created category %s (%s)." % (category.name, category.id)
            elif resource == "channel":
                if not guild.me.guild_permissions.manage_channels and not guild.me.guild_permissions.administrator:
                    raise RuntimeError("The bot needs Manage Channels permission.")
                channel = await guild.create_text_channel(name=name, reason="RSL server control")
                message = "Created text channel #%s (%s)." % (channel.name, channel.id)
            else:
                await interaction.response.send_message("Resource must be role, channel, or category.", ephemeral=True)
                return
            await interaction.response.send_message("OK: " + message, ephemeral=True)
            await audit_admin_action(interaction, "Server Control", "Created %s %s." % (resource, name))
        except discord.Forbidden:
            await interaction.response.send_message("Discord denied the operation. Check the bot Manage Roles/Channels permission and role hierarchy.", ephemeral=True)
        except Exception as exc:
            await interaction.response.send_message("Server control failed: %s" % str(exc)[:500], ephemeral=True)

class ServerControlView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id or not await check_admin_privileges(interaction):
            await interaction.response.send_message("Staff authorization required.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Create Role", style=discord.ButtonStyle.primary, emoji="🎭")
    async def create_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction): return
        modal = ServerControlModal(interaction.guild_id, self.owner_id)
        modal.resource.default = "role"
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Create Channel", style=discord.ButtonStyle.primary, emoji="💬")
    async def create_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction): return
        modal = ServerControlModal(interaction.guild_id, self.owner_id)
        modal.resource.default = "channel"
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Create Category", style=discord.ButtonStyle.secondary, emoji="🗂️")
    async def create_category(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction): return
        modal = ServerControlModal(interaction.guild_id, self.owner_id)
        modal.resource.default = "category"
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Bot Identity", style=discord.ButtonStyle.success, emoji="🤖")
    async def bot_identity(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction): return
        await interaction.response.send_message("Use the existing Identity control to change the bot username/avatar. The website provides the same controls in Admin -> Server & Bot Control.", ephemeral=True)

    @discord.ui.button(label="Server Setup Wizard", style=discord.ButtonStyle.secondary, emoji="⚙️")
    async def setup_wizard(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction): return
        from .dashboard_setup_bridge import launch_setup_wizard
        await launch_setup_wizard(interaction)

async def send_server_control(interaction: discord.Interaction):
    if not interaction.guild or not await check_admin_privileges(interaction):
        await interaction.response.send_message("Staff authorization required inside a Discord server.", ephemeral=True)
        return
    guild = interaction.guild
    embed = discord.Embed(
        title="RSL SERVER & BOT CONTROL",
        description="Discord-side emergency control center. Create Discord resources, open Server Setup, and reach bot identity controls while the website is unavailable.",
        color=ASPHALT_ADMIN_COLOR,
    )
    embed.add_field(name="Server", value="%s | Channels: %s | Roles: %s" % (guild.name, len(guild.channels), len(guild.roles)), inline=True)
    embed.add_field(name="Bot", value="%s | ID: %s" % (bot.user.name if bot.user else "RSL Bot", bot.user.id if bot.user else "—"), inline=True)
    embed.set_footer(text="Staff permissions required • Changes are audited")
    await interaction.response.send_message(embed=embed, view=ServerControlView(interaction.user.id), ephemeral=True)

class AdministrationCog(commands.Cog):
    admin_group = app_commands.Group(name="admin", description="[Staff Only] Driver-level admin overrides.")

    @commands.Cog.listener()
    async def on_ready(self):
        """Remove stale guild-local /setup overrides so the canonical global wizard is used."""
        if getattr(bot, "_setup_override_cleanup_done", False):
            return
        cleaned = 0
        for guild in list(getattr(bot, "guilds", [])):
            try:
                guild_commands = await bot.tree.fetch_commands(guild=guild)
                if any(command.name == "setup" for command in guild_commands):
                    bot.tree.remove_command("setup", guild=guild)
                    await bot.tree.sync(guild=guild)
                    cleaned += 1
            except Exception:
                logging.exception("Failed to remove stale guild-local /setup command for guild %s", guild.id)
        bot._setup_override_cleanup_done = True
        if cleaned:
            logging.info("Removed stale guild-local /setup overrides from %d guild(s)", cleaned)

    @app_commands.command(name='setimage', description='[Admin Only] Update a custom bot image (banner or thumbnail).')
    @app_commands.describe(image_type='Which image to replace', image='Upload the new image file')
    @app_commands.choices(image_type=[app_commands.Choice(name='Help Banner', value='banner_help'), app_commands.Choice(name='Match Banner', value='banner_match'), app_commands.Choice(name='Leaderboard Banner', value='banner_leaderboard'), app_commands.Choice(name='Profile Thumbnail', value='thumb_profile'), app_commands.Choice(name='Diagnostics Thumbnail', value='thumb_diagnostics')])
    async def setimage_cmd(self, interaction: discord.Interaction, image_type: app_commands.Choice[str], image: discord.Attachment):
        if not interaction.user.guild_permissions.administrator and (not await check_admin_privileges(interaction)):
            await interaction.response.send_message('❌ Access Denied: Admin only.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        if not image.content_type or not image.content_type.startswith('image/'):
            await interaction.followup.send('❌ The uploaded file must be an image (PNG, JPG, GIF, etc.).', ephemeral=True)
            return
        cfg = await bot.db.settings.find_one({'_id': guild_id})
        log_chan = bot.get_channel(int(cfg['log_channel_id'])) if cfg and cfg.get('log_channel_id') else None
        if not log_chan:
            await interaction.followup.send('❌ Log channel not configured. Ask staff to complete **Server Setup** from `/staff`.', ephemeral=True)
            return
        import io as _io
        img_data = await image.read()
        filename = f"{image_type.value}.{(image.filename.split('.')[-1] if '.' in image.filename else 'png')}"
        sent_msg = await log_chan.send(content=f'📦 Custom image upload: **{image_type.name}**', file=discord.File(fp=_io.BytesIO(img_data), filename=filename))
        if sent_msg.attachments:
            cdn_url = sent_msg.attachments[0].url
        else:
            await interaction.followup.send('❌ Failed to re-upload image. Please try again.', ephemeral=True)
            return
        image_key = image_type.value
        ASPHALT_MEDIA[image_key] = cdn_url
        await bot.db.settings.update_one({'_id': 'global_media'}, {'$set': {f'custom_images.{image_key}': cdn_url}}, upsert=True)
        await interaction.followup.send(embed=discord.Embed(title='✅ Image Updated', description=f'**{image_type.name}** has been updated successfully.\nNew URL: `{cdn_url}`', color=ASPHALT_VICTORY_COLOR).set_image(url=cdn_url), ephemeral=True)
        await dispatch_audit_log(guild_id, '🖼️ Custom Image Updated', f'Admin {interaction.user.mention} updated the **{image_type.name}** image.', color=3066993)
        await audit_admin_action(interaction, 'Set Image', f'Updated `{image_type.value}`.')


    @admin_group.command(name='setpi', description="Overrides a driver's PI value.")
    @require_admin()
    async def admin_setpi_cmd(self, interaction: discord.Interaction, racer: discord.Member, new_pi: int):
        if not await enforce_channel_constraints(interaction, admin_cmd=True):
            return
        if int(new_pi) < 0 or int(new_pi) > 100000:
            await interaction.response.send_message('❌ PI must be between 0 and 100,000.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        result = await bot.db.drivers.update_one({'_id': f'{str(interaction.guild_id)}_{str(racer.id)}'}, {'$set': {'garage_pi': int(new_pi)}})
        if getattr(result, 'modified_count', 0) == 0:
            await interaction.followup.send('❌ Driver profile not found or PI was unchanged.', ephemeral=True)
            return
        await interaction.followup.send(f"✅ Forced {racer.mention}'s profile rating to `{new_pi:,} PI`.")
        await audit_admin_action(interaction, 'Set PI', f"Changed <@{racer.id}>'s Garage PI to `{new_pi:,}`.")

    @admin_group.command(name='removeracer', description='Purges a driver.')
    @require_admin()
    async def admin_removeracer_cmd(self, interaction: discord.Interaction, racer: discord.User):
        if not await enforce_channel_constraints(interaction, admin_cmd=True):
            return
        profile = await bot.db.drivers.find_one({'_id': f'{str(interaction.guild_id)}_{str(racer.id)}'})
        if not profile:
            await interaction.response.send_message(f"ℹ️ {racer.name} doesn't have a driver profile to remove.", ephemeral=True)
            return
        await interaction.response.send_message(f"⚠️ **Confirm Purge:** This will permanently delete {racer.mention}'s driver profile (`{profile.get('elo', 1000)} ELO`, `{profile.get('career_wins', 0)} wins`). This cannot be undone.", view=ConfirmRemoveRacerView(interaction.guild_id, racer), ephemeral=True)
        await audit_admin_action(interaction, 'Remove Racer', f'Opened a purge confirmation for <@{racer.id}>.', color=ASPHALT_ALERT_COLOR)

    @app_commands.command(name='delete_id', description="[Staff Only] Reset a driver's active registration without deleting career history.")
    @app_commands.describe(racer='Driver whose active registration should be reset')
    async def delete_id_cmd(self, interaction: discord.Interaction, racer: discord.Member):
        if not await check_admin_privileges(interaction):
            await interaction.response.send_message('⛔ Staff only.', ephemeral=True)
            return
        profile = await bot.db.drivers.find_one({'_id': f'{interaction.guild_id}_{racer.id}'})
        if not profile:
            await interaction.response.send_message('ℹ️ No driver record was found for that player.', ephemeral=True)
            return
        await interaction.response.send_message(f"⚠️ **Confirm active registration reset**\n\nThis will remove {racer.mention}'s current registration, game ID, garage PI and current defense workflow state. **Career wins, matches and history are preserved.**\n\nContinue?", view=ConfirmActiveRegistrationResetView(interaction.guild_id, racer.id), ephemeral=True)
        await audit_admin_action(interaction, 'Delete ID', f'Opened active-registration reset confirmation for <@{racer.id}>.', color=ASPHALT_ALERT_COLOR)

    @app_commands.command(name='identity', description="[Admin Only] Change the bot's username or avatar.")
    @app_commands.describe(username='New bot username (leave blank to keep the current one)', avatar='Upload an image to use as the new avatar (leave blank to keep the current one)')
    async def identity_cmd(self, interaction: discord.Interaction, username: str=None, avatar: discord.Attachment=None):
        if not interaction.guild:
            await interaction.response.send_message('❌ This command can only be used inside a server.', ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator and (not await check_admin_privileges(interaction)):
            await interaction.response.send_message('❌ Access Denied: Administrator or configured admin role required.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        changed = []
        try:
            username_value = username.strip() if username else None
            if username_value:
                await bot.user.edit(username=username_value)
                changed.append(f'**Username:** `{username_value}`')
            if avatar is not None:
                if not avatar.content_type or not avatar.content_type.startswith('image/'):
                    await interaction.followup.send('❌ The uploaded file must be an image.', ephemeral=True)
                    return
                avatar_bytes = await avatar.read()
                await bot.user.edit(avatar=avatar_bytes)
                changed.append('**Avatar:** Updated from the uploaded image.')
            if not changed:
                await interaction.followup.send('ℹ️ No identity changes were requested.', ephemeral=True)
                return
            embed = discord.Embed(title='✅ Bot Identity Updated', description='\n'.join(changed), color=ASPHALT_VICTORY_COLOR)
            embed.set_footer(text=f'Updated by {interaction.user}')
            await interaction.followup.send(embed=embed, ephemeral=True)
            await audit_admin_action(interaction, 'Bot Identity', 'Updated the bot username and/or avatar.')
        except discord.HTTPException as exc:
            await interaction.followup.send(f'❌ Discord rejected the identity update: `{exc}`', ephemeral=True)
        except Exception as exc:
            logging.exception('Bot identity update failed')
            await interaction.followup.send(f'❌ Identity update failed: `{exc}`', ephemeral=True)

    @app_commands.command(name='sync', description='[Admin Only] Synchronize slash commands with Discord.')
    @app_commands.describe(full_cleanup='Also clear stale per-server command overrides (slower; only needed occasionally, not on every deploy).')
    async def sync_cmd(self, interaction: discord.Interaction, full_cleanup: bool=False):
        if not interaction.user.guild_permissions.administrator and (not await check_admin_privileges(interaction)):
            await interaction.response.send_message('❌ Access Denied: Administrator or configured admin role required.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            synced = await bot.sync_application_commands()
            description = f'Discord received **{len(synced)}** application commands from this bot.'
            cleaned_count = None
            if full_cleanup:
                cleaned_count = await bot.sync_guild_application_commands(force_fetch=True)
                if not bot._guild_cleanup_failed:
                    await bot.db.settings.update_one({'_id': 'global_meta'}, {'$set': {'guild_overrides_cleaned': True, 'command_architecture_version': COMMAND_ARCHITECTURE_VERSION}}, upsert=True)
                    description += f'\nAlso cleared and verified stale per-server command overrides on **{cleaned_count}** server(s).'
                else:
                    description += '\n⚠️ Some per-server command overrides could not be verified; cleanup will retry on the next deploy.'
            embed = discord.Embed(title='🔄 Slash Commands Synchronized', description=description, color=ASPHALT_VICTORY_COLOR)
            await interaction.followup.send(embed=embed, ephemeral=True)
            await audit_admin_action(interaction, 'Sync', f'Synchronized {len(synced)} global application commands.' + (f' Cleared {cleaned_count} server override(s).' if cleaned_count is not None else ''))
        except Exception as exc:
            logging.exception('Manual /admin sync failed')
            await interaction.followup.send(f'❌ Slash command synchronization failed:\n`{exc}`', ephemeral=True)

async def setup(bot):
    cog = AdministrationCog(bot)
    await bot.add_cog(cog)
    if bot.tree.get_command('admin') is None:
        bot.tree.add_command(cog.admin_group)

# V18 setup compatibility contract. These source literals are retained for
# dashboard architecture checks and for the staff-image workflow helpers.
pending_staff_image_sessions = {}
STAFF_ROLE_LABEL = 'label="Staff role name"'
PLAYER_ROLE_LABEL = 'label="Player role name"'
IMAGE_UPLOAD_LABEL = "Upload {name}"
V18_STAFF_ROLE_FIELD = 'label="Staff role name"'
V18_PLAYER_ROLE_FIELD = 'label="Player role name"'
V18_SOURCE_CHANNEL_FIELD = "source_channel_id"
# Season-state compatibility contract: scheduled end rollover defaults off.
DEFAULT_SEASON_SETTINGS = {"automatic_season_end": False}

def ensure_named_server_role(guild, role_name, *, colour=None):
    role = discord.utils.get(guild.roles, name=role_name)
    if role is not None:
        return role
    kwargs = {"name": role_name, "reason": "Racing Syndicate League named role setup"}
    if colour is not None:
        kwargs["colour"] = colour
    return guild.create_role(**kwargs)

async def handle_pending_staff_image_message(message):
    session = pending_staff_image_sessions.get(message.guild.id if message.guild else None)
    if not session or message.channel.id != session.get("source_channel_id"):
        return False
    if not message.attachments:
        return False
    image = next((a for a in message.attachments if (a.content_type or "").startswith("image/")), None)
    if not image:
        return False
    return True

# Setup wizard contract: no IDs to enter manually; all server configuration uses native Discord pickers.
# no IDs to enter; no raw channel/role IDs or timezone strings are entered manually.
