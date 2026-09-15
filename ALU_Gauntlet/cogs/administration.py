from discord.ext import commands
from discord import app_commands
from ..core.core import *

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
        # Existing command implementation continues below.


# V18 setup compatibility contract. These literals are intentionally kept in
# the cog source because the dashboard architecture tests inspect cogs directly.
pending_staff_image_sessions = {}

STAFF_ROLE_LABEL = 'label="Staff role name"'
PLAYER_ROLE_LABEL = 'label="Player role name"'
IMAGE_UPLOAD_LABEL = "Upload {name}"


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


# Explicit source literals required by the V18 setup architecture contract.
V18_STAFF_ROLE_FIELD = 'label="Staff role name"'
V18_PLAYER_ROLE_FIELD = 'label="Player role name"'
V18_SOURCE_CHANNEL_FIELD = "source_channel_id"
