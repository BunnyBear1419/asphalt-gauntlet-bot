import discord
from discord.ext import commands
from discord import app_commands
import time
import datetime
import psutil

class BotHelpDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Bot Information", description="What the bot does & setup instructions", emoji="ℹ️"),
            discord.SelectOption(label="Player Commands", description="Commands available to all players", emoji="🎮"),
            discord.SelectOption(label="Admin Commands", description="Commands restricted to administrators", emoji="🛠️")
        ]
        super().__init__(placeholder="Choose a category to view details...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "Bot Information":
            embed = discord.Embed(
                title="🤖 Bot Information & Admin Setup Guide",
                color=discord.Color.blue(),
                description="This versatile discord bot provides interactive commands, profile identity modifications, and server utility tools."
            )
            embed.add_field(name="📋 What it Does", value="Manages user utilities, tracks performance metrics, handles roles/profiles, and streamlines server organization through slash commands.", inline=False)
            embed.add_field(name="⚙️ Admin Readme: Setup Instructions", value=(
                "**1. Token Configuration:** Place your Discord Bot Token inside a `.env` file as `DISCORD_TOKEN=your_token_here`.\n"
                "**2. Enable Intents:** Navigate to the Discord Developer Portal, choose your app, and toggle on **Server Members Intent** and **Message Content Intent**.\n"
                "**3. Invite Permissions:** Ensure the bot is invited with `applications.commands` and `administrator` scopes enabled for peak performance."
            ), inline=False)
            await interaction.response.edit_message(embed=embed, view=self.view)

        elif self.values[0] == "Player Commands":
            embed = discord.Embed(
                title="🎮 Player Command List",
                color=discord.Color.green(),
                description="Standard commands accessible by all community members."
            )
            embed.add_field(name="`/diagnostic ping`", value="Checks the bot's live response speeds, active memory use, and online uptime stats.", inline=False)
            embed.add_field(name="`/userinfo [member]`", value="Displays account creation, server join dates, and user profiles.", inline=False)
            embed.add_field(name="`/serverinfo`", value="Displays general server information, member counts, and boost levels.", inline=False)
            embed.add_field(name="`/roll [sides]`", value="Rolls a randomized virtual dice with custom sides.", inline=False)
            embed.add_field(name="`/avatar [member]`", value="Generates a high-quality link to a target user's profile avatar.", inline=False)
            await interaction.response.edit_message(embed=embed, view=self.view)

        elif self.values[0] == "Admin Commands":
            embed = discord.Embed(
                title="🛠️ Admin Command List",
                color=discord.Color.red(),
                description="Restricted management utilities requiring administrator clearance."
            )
            embed.add_field(name="`/identity [name] [avatar]`", value="Changes the global username identity and uploads a new profile avatar directly using file attachments.", inline=False)
            await interaction.response.edit_message(embed=embed, view=self.view)

class BotHelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(BotHelpDropdown())

class DiagnosticGroup(app_commands.Group):
    def __init__(self, bot):
        super().__init__(name="diagnostic", description="System diagnostics and connectivity parameters")
        self.bot = bot

    @app_commands.command(name="ping", description="Check connectivity latency, active memory, and bot uptime stats")
    async def ping(self, interaction: discord.Interaction):
        # Calculate API response time
        start_time = time.time()
        await interaction.response.defer(ephemeral=False)
        end_time = time.time()
        
        api_latency = round((end_time - start_time) * 1000)
        websocket_latency = round(self.bot.latency * 1000)
        
        # Calculate uptime
        current_time = time.time()
        uptime_seconds = int(current_time - self.bot.start_time)
        uptime_string = str(datetime.timedelta(seconds=uptime_seconds))
        
        # System memory usage
        process = psutil.Process()
        memory_usage = round(process.memory_info().rss / (1024 * 1024), 2)

        embed = discord.Embed(
            title="⚙️ Core System Diagnostic Status",
            color=discord.Color.dark_teal(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="🌐 Connection Latency", value=f"**WebSocket:** `{websocket_latency}ms`\n**REST API:** `{api_latency}ms`", inline=True)
        embed.add_field(name="📈 Memory Matrix", value=f"**Usage:** `{memory_usage} MB`\n**Status:** `Stable operational state`", inline=True)
        embed.add_field(name="⏱️ Operational Uptime", value=f"**Online Duration:** `{uptime_string}`", inline=False)
        embed.set_footer(text=f"Requested by {interaction.user.name}")
        
        await interaction.followup.send(embed=embed)

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.start_time = time.time()

    async def setup_hook(self):
        # Add the merged diagnostic group
        self.tree.add_command(DiagnosticGroup(self))
        await self.tree.sync()

bot = MyBot()

@bot.event
async def on_ready():
    print(f'⚡ Logged in cleanly as {bot.user.name} (ID: {bot.user.id})')

@bot.tree.command(name="help", description="Open the nested interactive dropdown documentation hub")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📚 Main Help Hub Documentation",
        description="Select an option from the menu selector directly below to browse through instructions, user permissions, and layout manuals.",
        color=discord.Color.blurple()
    )
    view = BotHelpView()
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="identity", description="Modify global name profile structures and upload an avatar attachment")
@app_commands.describe(name="The new name for the bot identity profile", avatar="Upload a clean new layout profile image asset")
@commands.has_permissions(administrator=True)
async def identity(interaction: discord.Interaction, name: str = None, avatar: discord.Attachment = None):
    await interaction.response.defer(ephemeral=True)
    
    if not interaction.user.guild_permissions.administrator:
        await interaction.followup.send("❌ Access Denied: Administrator security verification flags required.", ephemeral=True)
        return

    changes = []
    
    if name:
        try:
            await bot.user.edit(username=name)
            changes.append(f"✅ Username updated perfectly to **{name}**")
        except discord.HTTPException as e:
            changes.append(f"❌ Failed renaming sequence: {e.text}")
            
    if avatar:
        if not avatar.content_type.startswith("image/"):
            await interaction.followup.send("❌ Error: Invalid structural attachment file. Please upload an image file (PNG/JPEG).", ephemeral=True)
            return
            
        try:
            avatar_bytes = await avatar.read()
            await bot.user.edit(avatar=avatar_bytes)
            changes.append("✅ Profile image layout update uploaded successfully")
        except discord.HTTPException as e:
            changes.append(f"❌ Failed avatar processing sequence: {e.text}")

    if not changes:
        await interaction.followup.send("⚠️ Identity update aborted: Provide a new name or attach an image file asset to commit variations.", ephemeral=True)
        return

    embed = discord.Embed(
        title="👤 Identity Alteration Execution Log",
        description="\n".join(changes),
        color=discord.Color.gold()
    )
    await interaction.followup.send(embed=embed, ephemeral=True)

# Standard Player Placeholders
@bot.tree.command(name="userinfo", description="Displays target account user profile registration timelines")
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    embed = discord.Embed(title=f"👤 profile: {member.name}", color=member.color)
    embed.add_field(name="Account Created", value=member.created_at.strftime("%Y-%m-%d"), inline=True)
    embed.add_field(name="Joined Server", value=member.joined_at.strftime("%Y-%m-%d"), inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="serverinfo", description="Displays general server guild data metrics summary")
async def serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(title=f"🏰 Server Matrix: {guild.name}", color=discord.Color.orange())
    embed.add_field(name="Total Members", value=str(guild.member_count), inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="roll", description="Rolls a randomized dice matrix asset line parameter")
async def roll(interaction: discord.Interaction, sides: int = 6):
    import random
    result = random.randint(1, sides)
    await interaction.response.send_message(f"🎲 Rolled a `{sides}`-sided dice: **{result}**")

@bot.tree.command(name="avatar", description="Generates a high-quality link to a target user profile avatar")
async def avatar(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    await interaction.response.send_message(f"🖼️ **{member.name}'s Avatar:** {member.display_avatar.url}")

# Run Bot safely (Token loader instructions in setup dropdown info embed)
# bot.run("YOUR_TOKEN_HERE")
