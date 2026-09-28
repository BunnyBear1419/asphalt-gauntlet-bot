from discord.ext import commands
from discord import app_commands
from ..core.core import *
from .translation import localize_text

# Canonical Help Center categories.
# Keep these in the Help Cog so the Cogs architecture has an explicit,
# testable contract for the public help organization.
PLAYER_HELP_CATEGORIES = (
    "getting_started",
    "defense",
    "racing",
    "rankings",
    "account",
)

ADMIN_HELP_CATEGORIES = (
    "admin_setup",
    "admin_seasons",
    "admin_players",
    "admin_tools",
)


class HelpCog(commands.Cog):

    @app_commands.command(name='help', description='Interactive help and command reference.')
    async def help_cmd(self, interaction: discord.Interaction):
        is_admin = bool(
            interaction.guild
            and (
                interaction.user.guild_permissions.administrator
                or await check_admin_privileges(interaction)
            )
        )

        embed = discord.Embed(
            title=await localize_text(bot, interaction.user.id, '🏁 RACING SYNDICATE LEAGUE — HELP', getattr(interaction, 'locale', None)),
            description=await localize_text(bot, interaction.user.id, 'Choose a section below.\\n\\n📘 Overview  •  📜 Rules  •  🎮 Player Help  •  🛠️ Staff Help\\n\\n**Quick access:** `/dashboard` for players • `/staff` for staff\\n\\n📤 **Submit Match** is inside `/dashboard` → **Challenges**.', getattr(interaction, 'locale', None)),
            color=ASPHALT_THEME_COLOR,
        )
        embed.set_thumbnail(url=ASPHALT_MEDIA['thumb_profile'])
        embed.set_image(url=ASPHALT_MEDIA['banner_help'])
        embed.set_footer(text=await localize_text(bot, interaction.user.id, 'Racing Syndicate League • Quick reference', getattr(interaction, 'locale', None)))

        # HelpView remains the shared interactive renderer in core.py.
        # It contains Overview/Rules plus the player and staff categories above.
        await interaction.response.send_message(
            embed=embed,
            view=HelpView(is_admin=is_admin),
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(HelpCog(bot))
