import discord
from discord.ext import commands
from discord import app_commands
import aiohttp

class HelpDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Bot Information", description="Learn about the bot and admin setup.", emoji="ℹ️"),
            discord.SelectOption(label="Player Commands", description="View available commands for all players.", emoji="🎮"),
            discord.SelectOption(label="Admin Commands", description="View restrictive tools for administrators.", emoji="🛡️")
        ]
        super().__init__(placeholder="Choose a category...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "Bot Information":
            embed = discord.Embed(
                title="🤖 Bot Information & Setup Guide",
                description="This versatile bot serves your community with interactive utility, entertainment, and administrative controls.",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="📋 Setup Instructions (For Admins)",
                value=(
                    "1. **Token**: Place your Discord bot token in a secure `.env` file or environment variable.\n"
                    "2. **Privileged Intents**: Ensure **Message Content Intent** and **Guild Members Intent** are enabled in the Discord Developer Portal.\n"
                    "3. **Permissions**: Invite the bot using the application-commands scope with administrator or appropriate channel permissions.\n"
                    "4. **Deployment**: Run the script using Python 3.8+ with `discord.py` installed."
                ),
                inline=False
            )
            await interaction.response.edit_message(embed=embed, view=self.view)

        elif self.values[0] == "Player Commands":
            embed = discord.Embed(
                title="🎮 Player Commands List",
                description="Standard commands available to all members of the server.",
                color=discord.Color.green()
            )
            embed.add_field(name="`/help`", value="Opens this interactive help menu with dropdown categories.", inline=False)
            embed.add_field(name="`/ping`", value="Checks the bot's latency and connection responsiveness.", inline=False)
            embed.add_field(name="`/userinfo [member]`", value="Displays account creation date, server join date, and roles for a specified user or yourself.", inline=False)
            embed.add_field(name="`/serverinfo`", value="Displays server statistics, including member counts, creation date, and region.", inline=False)
            embed.add_field(name="`/roll [dice]`", value="Rolls custom dice (e.g., 1d20, 2d6) and outputs individual results and totals.", inline=False)
            embed.add_field(name="`/avatar [member]`", value="Provides a high-resolution download link and view of a user's avatar.", inline=False)
            await interaction.response.edit_message(embed=embed, view=self.view)

        elif self.values[0] == "Admin Commands":
            embed = discord.Embed(
                title="🛡️ Admin Commands List",
                description="Restricted management utilities requiring Administrator or specific permissions.",
                color=discord.Color.red()
            )
            embed.add_field(name="`/identity [name] [avatar]`", value="Modifies the bot's global username and profile picture. Supports direct text input for names and interactive file uploads for avatars.", inline=False)
            embed.add_field(name="`/kick [member] [reason]`", value="Removes a disruptive member from the guild safely.", inline=False)
            embed.add_field(name="`/ban [member] [reason]`", value="Permanently bans a malicious user and purges recent message history.", inline=False)
            embed.add_field(name="`/clear [amount]`", value="Bulk deletes a specified number of recent messages from the current channel.", inline=False)
            await interaction.response.edit_message(embed=embed, view=self.view)

class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(HelpDropdown())

class CoreBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()

bot = CoreBot()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} (ID: {bot.user.id})')

@bot.tree.command(name="help", description="Open the interactive dropdown help menu.")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📚 Help & Documentation System",
        description="Select an option from the dropdown menu below to navigate through Bot Information, Player Commands, or Admin Commands.",
        color=discord.Color.blurple()
    )
    await interaction.response.send_message(embed=embed, view=HelpView())

@bot.tree.command(name="identity", description="Modify the bot's global name and avatar image.")
@app_commands.describe(name="The new name for the bot", avatar="Upload a new profile picture file from Discord")
@commands.has_permissions(administrator=True)
async def identity(interaction: discord.Interaction, name: str = None, avatar: discord.Attachment = None):
    if not name and not avatar:
        await interaction.response.send_message("❌ Please provide either a new `name`, an uploaded `avatar` file, or both.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    update_log = []

    try:
        if name:
            await bot.user.edit(username=name)
            update_log.append(f"✅ Name updated successfully to **{name}**.")

        if avatar:
            # Check content type to ensure it is an image
            if avatar.content_type and not avatar.content_type.startswith("image/"):
                await interaction.followup.send("❌ The uploaded file must be a valid image format (PNG, JPEG, etc.).", ephemeral=True)
                return

            async with aiohttp.ClientSession() as session:
                async with session.get(avatar.url) as resp:
                    if resp.status == 200:
                        avatar_bytes = await resp.read()
                        await bot.user.edit(avatar=avatar_bytes)
                        update_log.append("✅ Profile avatar updated successfully.")
                    else:
                        update_log.append("❌ Failed to download the uploaded image from Discord attachments.")

        await interaction.followup.send("\n".join(update_log), ephemeral=True)

    except discord.HTTPException as e:
        await interaction.followup.send(f"❌ Discord API Error: Changing identity too fast or invalid input. Detailed error: {e}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ An unexpected error occurred: {e}", ephemeral=True)

@identity.error
async def identity_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You lack the required Administrator permissions to execute this command.", ephemeral=True)

# Add basic implementations for populated player commands so they are usable right away
@bot.tree.command(name="ping", description="Check the responsiveness of the bot.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! Latency is {round(bot.latency * 1000)}ms.")

@bot.tree.command(name="serverinfo", description="Display current server diagnostics.")
async def serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(title=f"📊 {guild.name} Diagnostics", color=discord.Color.blue())
    embed.add_field(name="Total Members", value=str(guild.member_count))
    embed.add_field(name="Creation Date", value=guild.created_at.strftime('%Y-%m-%d'))
    await interaction.response.send_message(embed=embed)

if __name__ == "__main__":
    # bot.run('YOUR_BOT_TOKEN_HERE')
    pass
