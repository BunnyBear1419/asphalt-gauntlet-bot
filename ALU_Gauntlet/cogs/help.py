from discord.ext import commands
from discord import app_commands
from ..core.core import *

class HelpCog(commands.Cog):

    @app_commands.command(name='help', description='Interactive help and command reference.')
    async def help_cmd(self, interaction: discord.Interaction):
        is_admin = bool(interaction.guild and (interaction.user.guild_permissions.administrator or await check_admin_privileges(interaction)))
        embed = discord.Embed(title='🏁 ALU GAUNTLET — HELP', description='Choose a section below.\n\n📘 Overview  •  📜 Rules  •  🎮 Player Help  •  🛠️ Staff Help\n\n**Quick commands:** `/gauntlet` • `/register` • `/staff` • `/help`\n\n📤 **Submit Match** is inside `/gauntlet` → **Challenges**.', color=ASPHALT_THEME_COLOR)
        embed.set_thumbnail(url=ASPHALT_MEDIA['thumb_profile'])
        embed.set_image(url=ASPHALT_MEDIA['banner_help'])
        embed.set_footer(text='ALU Gauntlet • Quick reference')
        await interaction.response.send_message(embed=embed, view=HelpView(is_admin=is_admin), ephemeral=True)

async def setup(bot):
    await bot.add_cog(HelpCog(bot))
