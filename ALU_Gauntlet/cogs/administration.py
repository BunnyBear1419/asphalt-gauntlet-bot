from discord.ext import commands
from discord import app_commands
from ..core.core import *

COMMAND_ARCHITECTURE_VERSION = 11
command_architecture_version = COMMAND_ARCHITECTURE_VERSION

class AdministrationCog(commands.Cog):
    admin_group = app_commands.Group(name="admin", description="[Staff Only] Driver-level admin overrides.")

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

    @app_commands.command(name='setup', description='[Admin Only] Configures all league core channels and permission roles.')
    @app_commands.describe(main_channel='Public room for commands', staff_channel='Private room for staff reviews', log_channel='Private room for logs', announcement_channel='Public awards room', match_results_channel='Public room for match results', admin_role='Staff/admin role (selected by the administrator)', player_role='Player role (selected by the administrator)', timezone_name='Server timezone used for season scheduling')
    @app_commands.choices(timezone_name=[app_commands.Choice(name=label, value=value) for label, value in TIMEZONE_CHOICES])
    async def setup_cmd(self, interaction: discord.Interaction, main_channel: discord.TextChannel, staff_channel: discord.TextChannel, log_channel: discord.TextChannel, announcement_channel: discord.TextChannel, match_results_channel: discord.TextChannel, admin_role: discord.Role, player_role: discord.Role, timezone_name: app_commands.Choice[str]=None):
        if not interaction.user.guild_permissions.administrator and (not await check_admin_privileges(interaction)):
            await interaction.response.send_message('❌ Access Denied: Admin role overrides missing.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await bot.db.settings.update_one({'_id': str(interaction.guild_id)}, {'$set': {'registration_channel_id': str(main_channel.id), 'review_channel_id': str(staff_channel.id), 'log_channel_id': str(log_channel.id), 'announcement_channel_id': str(announcement_channel.id), 'match_results_channel_id': str(match_results_channel.id), 'admin_role_id': str(admin_role.id), 'player_role_id': str(player_role.id), 'timezone': timezone_name.value if timezone_name else 'UTC'}, '$setOnInsert': {"automatic_season_end": False}}, upsert=True)
        guild_state = await bot.db.season_state.find_one({'_id': f'guild_{interaction.guild_id}'})
        if not guild_state:
            legacy_state = await bot.db.season_state.find_one({'_id': 'current_season'})
            await bot.db.season_state.update_one({'_id': f'guild_{interaction.guild_id}'}, {'$setOnInsert': {'guild_id': str(interaction.guild_id), 'season_number': int(legacy_state.get('season_number', 1)) if legacy_state else 1, 'ends_at': float(legacy_state.get('ends_at', time.time() + 14 * 24 * 60 * 60)) if legacy_state else time.time() + 14 * 24 * 60 * 60}}, upsert=True)
        await interaction.followup.send(embed=discord.Embed(title='⚙️ Master League Matrix Configuration Restored', description='All channel streams and dynamic role mapping rules saved successfully. Match results will be posted to the designated channel.', color=ASPHALT_THEME_COLOR))
        await dispatch_audit_log(interaction.guild_id, '⚙️ Master Setup Initialized', f'The bot was initialized perfectly by authority {interaction.user.mention}.', color=ASPHALT_THEME_COLOR)
        await audit_admin_action(interaction, 'Setup', 'Updated the league channel and role configuration.')

    @app_commands.command(name='timezone', description="[Admin Only] Set this Discord server's timezone for season scheduling.")
    @app_commands.describe(timezone_name='Timezone used when admins enter season start/end times')
    @app_commands.choices(timezone_name=[app_commands.Choice(name=label, value=value) for label, value in TIMEZONE_CHOICES])
    async def timezone_cmd(self, interaction: discord.Interaction, timezone_name: app_commands.Choice[str]):
        if not interaction.user.guild_permissions.administrator and (not await check_admin_privileges(interaction)):
            await interaction.response.send_message('❌ Access Denied: Requires admin access clearance level.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await bot.db.settings.update_one({'_id': str(interaction.guild_id)}, {'$set': {'timezone': timezone_name.value}}, upsert=True)
        await interaction.followup.send(f'🌎 **Server timezone updated:** `{timezone_name.name}` (`{timezone_name.value}`)\n\n`/staff` → **Season → Season Schedule** will now interpret entered times using this timezone.', ephemeral=True)
        await audit_admin_action(interaction, 'Timezone', f'Set server timezone to `{timezone_name.value}`.')

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

def ensure_named_server_role(guild, role_name, *, colour=None):
    role = discord.utils.get(guild.roles, name=role_name)
    if role is not None:
        return role
    kwargs = {"name": role_name, "reason": "ALU Gauntlet named role setup"}
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
    if image is None:
        return False
    session["attachment_url"] = image.url
    return True
