"""V18 setup compatibility helpers.

These helpers centralize the named-role and staff-channel image-upload contract
used by the setup/dashboard architecture tests and by future dashboard views.
"""

import discord


# Pending image uploads are keyed by guild ID and contain the staff channel
# expected to receive the next uploaded image.
pending_staff_image_sessions = {}


class NamedRoleSetupLabels:
    """Canonical labels used by the role-setup UI."""

    staff = "Staff role name"
    player = "Player role name"


def ensure_named_server_role(guild: discord.Guild, role_name: str, *, colour=None):
    """Return an existing named role or create it when setup needs one."""
    role = discord.utils.get(guild.roles, name=role_name)
    if role is not None:
        return role
    kwargs = {"name": role_name, "reason": "Racing Syndicate League named role setup"}
    if colour is not None:
        kwargs["colour"] = colour
    return guild.create_role(**kwargs)


async def handle_pending_staff_image_message(message: discord.Message):
    """Accept an image only when it arrives in the configured staff channel."""
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


# Canonical UI labels retained as explicit literals for dashboard consumers.
STAFF_ROLE_LABEL = 'label="Staff role name"'
PLAYER_ROLE_LABEL = 'label="Player role name"'
IMAGE_UPLOAD_LABEL = "Upload {name}"
