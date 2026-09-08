import os
import re
import time
import logging
import asyncio
import aiohttp
from difflib import SequenceMatcher
from dotenv import load_dotenv
import discord
from discord import app_commands
from discord.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient
from PIL import Image
import io
import pytesseract

# Comprehensive Discloud Sandbox Path Lookups
DISCLOUD_BIN_PATHS = [
    '/app/.apt/usr/bin/tesseract',
    '/home/user_discloud/.apt/usr/bin/tesseract',
    '/usr/bin/tesseract',
    'tesseract'
]

for binary_path in DISCLOUD_BIN_PATHS:
    if os.path.exists(binary_path) or os.access(binary_path, os.X_OK):
        pytesseract.pytesseract.tesseract_cmd = binary_path
        break

# Load local environment configuration keys
load_dotenv()

# Configure Global Logging Matrices
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
class GauntletBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.db = None
        self.mongo_client = None
    async def setup_hook(self):
        # Establish asynchronous MongoDB connection via Motor
        mongo_uri = os.getenv("MONGO_URI")
        if mongo_uri:
            try:
                self.mongo_client = AsyncIOMotorClient(mongo_uri)
                # Force a low-latency cluster validation ping
                await self.mongo_client.admin.command('ping')
                self.db = self.mongo_client.get_database("asphalt_gauntlet")
                logging.info("🟢 Successfully connected to MongoDB Atlas Cloud Cluster.")
            except Exception as e:
                logging.error(f"🔴 MongoDB Connection Failed: {e}")
                logging.info("Falling back to simulated local environment database...")
                self.setup_mock_db()
        else:
            logging.warning("⚠️ MONGO_URI missing from environment variables.")
            self.setup_mock_db()

        # Synchronize application tree slash commands globally
        await self.tree.sync()
        logging.info("🟢 Application slash commands synchronized globally.")
    def setup_mock_db(self):
        """Fallback local database simulation if MongoDB Atlas is offline."""
        class MockCollection:
            async def find_one(self, *args, **kwargs): return {}
            async def update_one(self, *args, **kwargs): return None
            async def delete_one(self, *args, **kwargs): return None
        class MockDB:
            def __getattr__(self, name): return MockCollection()
            async def command(self, *args, **kwargs): raise ConnectionError("Mock DB Offline")
        self.db = MockDB()

    async def close(self):
        if self.mongo_client:
            self.mongo_client.close()
        await super().close()

bot = GauntletBot()
def fuzzy_correct_marker(text: str, target: str, threshold: float = 0.6) -> str:
    """Corrects common OCR typos (like 6ARAGE or 1D) back into clear target keys."""
    words = text.split()
    for word in words:
        cleaned_word = re.sub(r'[^A-Z0-9]', '', word.upper())
        if not cleaned_word:
            continue
        matcher = SequenceMatcher(None, cleaned_word, target)
        if matcher.ratio() >= threshold:
            return text.replace(word, target)
    return text

def preprocess_text_with_fuzzy(text: str) -> str:
    """Pre-processes OCR text block with common Asphalt Legends interface corrections."""
    text = text.upper()
    text = fuzzy_correct_marker(text, "GARAGE")
    text = fuzzy_correct_marker(text, "PLAYER")
    text = fuzzy_correct_marker(text, "LEVEL")
    text = fuzzy_correct_marker(text, "CLUB")
    
    # Target common text errors explicitly
    text = re.sub(r'\b(1D|LD|lD)\b', 'ID', text)
    text = re.sub(r'\b(6ARAGE|GARA6E)\b', 'GARAGE', text)
    return text
class VerificationView(discord.ui.View):
    def __init__(self, user_id: str, guild_id: str, game_id: str, rank: int, control: str):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.guild_id = guild_id
        self.game_id = game_id
        self.rank = rank
        self.control = control

    @discord.ui.button(label="Approve Driver", style=discord.ButtonStyle.green, custom_id="approve_driver_btn")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        await bot.db.drivers.update_one(
            {"_id": f"{self.guild_id}_{self.user_id}"},
            {"$set": {
                "guild_id": self.guild_id, "user_id": self.user_id,
                "game_id": self.game_id, "garage_pi": self.rank,
                "control_type": self.control, "verified_at": time.time()
            }},
            upsert=True
        )
        await bot.db.pending.delete_one({"_id": f"{self.guild_id}_{self.user_id}"})
        
        embed = interaction.message.embeds
        embed.color = discord.Color.green()
        embed.title = "✅ Driver Profile Verification Approved"
        embed.set_footer(text=f"Approved by staff manager: {interaction.user.display_name}")
        
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(embed=embed, view=self)
        
        try:
            member = await interaction.guild.fetch_member(int(self.user_id))
            if member:
                await member.send(f"🎉 **Asphalt Gauntlet Roster Clearance:** Your profile (`{self.game_id}`) has been fully approved for official league tournament races!")
        except Exception:
            pass
    @discord.ui.button(label="Reject & Deny", style=discord.ButtonStyle.red, custom_id="reject_driver_btn")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await bot.db.pending.delete_one({"_id": f"{self.guild_id}_{self.user_id}"})
        
        embed = interaction.message.embeds
        embed.color = discord.Color.red()
        embed.title = "❌ Driver Profile Verification Denied"
        embed.set_footer(text=f"Rejected by staff manager: {interaction.user.display_name}")
        
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(embed=embed, view=self)
@bot.tree.command(name="register", description="Enters the automated cloud verification staging queues.")
@app_commands.describe(game_id="Asphalt player alphanumeric tag ID", proof_screenshot="Attach profile card file", control_type="Driving system configuration layout used")
@app_commands.choices(control_type=[
    app_commands.Choice(name="Manual Controls", value="manual"), 
    app_commands.Choice(name="TouchDrive", value="touchdrive")
])
async def register_cmd(interaction: discord.Interaction, game_id: str, proof_screenshot: discord.Attachment, control_type: app_commands.Choice[str]):
    cfg = await bot.db.settings.find_one({"_id": str(interaction.guild_id)})
    if cfg and cfg.get("registration_channel_id") and str(interaction.channel_id) != str(cfg["registration_channel_id"]):
        await interaction.response.send_message(f"❌ Execute profile registration within <#{cfg['registration_channel_id']}>.", ephemeral=True)
        return

    if not proof_screenshot.content_type or not proof_screenshot.content_type.startswith("image/"):
        await interaction.response.send_message("❌ Upload Blocked: Media attachments must be valid images.", ephemeral=True)
        return

    await interaction.response.defer()
    parsed_rank = 15500
    ocr_status = "AUTOMATED_OCR_PASS"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(proof_screenshot.url) as img_resp:
                if img_resp.status == 200:
                    img_bytes = await img_resp.read()
                    
                    # Offload local processing to executor thread to keep event loop responsive
                    loop = asyncio.get_event_loop()
                    def run_local_ocr():
                        img = Image.open(io.BytesIO(img_bytes)).convert('L')
                        img = img.point(lambda x: 0 if x < 200 else 255, '1')
                        return pytesseract.image_to_string(img)
                    
                    raw_text = await loop.run_in_executor(None, run_local_ocr)
                    parsed_text = preprocess_text_with_fuzzy(raw_text)
                    
                    match_id = re.search(r"ID[:\s]*([A-Z0-9_\-]+)", parsed_text)
                    match_pi = re.search(r"GARAGE[:\s]*([0-9,]+)", parsed_text)
                    
                    if match_id: game_id = match_id.group(1)
                    if match_pi: parsed_rank = int(match_pi.group(1).replace(",", ""))
                    
                    if not any(x in parsed_text for x in ["PLAYER", "GARAGE", "LEVEL", "CLUB", "ID"]):
                        await interaction.followup.send("❌ Image Analysis Blocked: Uploaded file does not verify as an authentic Asphalt interface screenshot.")
                        return
                else:
                    ocr_status = "MANUAL_REVIEW_REQUIRED_DOWNLOAD_FAILED"
    except Exception as err:
        logging.error(f"Local OCR pipeline exception: {err}")
        ocr_status = "MANUAL_REVIEW_REQUIRED_PROCESSING_ERROR"

    db_id = f"{interaction.guild_id}_{interaction.user.id}"
    await bot.db.pending.update_one(
        {"_id": db_id}, 
        {"$set": {
            "guild_id": str(interaction.guild_id), "user_id": str(interaction.user.id), 
            "game_id": game_id, "proposed_rank": parsed_rank, "proof": proof_screenshot.url, 
            "control": control_type.value, "ocr_verification": ocr_status
        }}, 
        upsert=True
    )
    
    msg_prefix = f"📥 **Submission Completed (Auto-Filled Profile UI).** Detected ID: `{game_id}`, PI: `{parsed_rank:,}`" if ocr_status == "AUTOMATED_OCR_PASS" else "⚠️ **Local Validation Flagged.** Submission queued for manual review."
    await interaction.followup.send(f"{msg_prefix} Roster lines routed to staff review queues.")
    
    if cfg and cfg.get("registration_channel_id"):
        chan = bot.get_channel(int(cfg["registration_channel_id"]))
        if chan:
            emb = discord.Embed(title="🛡️ New Gauntlet Placement Review Request", color=0xffcc00)
            emb.add_field(name="Driver", value=interaction.user.mention, inline=True)
            emb.add_field(name="Declared Game ID", value=f"`{game_id}`", inline=True)
            emb.add_field(name="System Audit Flag", value=f"`{ocr_status}`", inline=False)
            emb.set_image(url=proof_screenshot.url)
            await chan.send(embed=emb, view=VerificationView(str(interaction.user.id), str(interaction.guild_id), game_id, parsed_rank, control_type.value))
@bot.tree.command(name="diagnose", description="[Admin Only] Core structural health check for database, OCR, and container limits.")
@app_commands.default_permissions(administrator=True)
async def diagnose_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    discord_ping = round(bot.latency * 1000)
    db_status = "🟢 Operational"
    db_ping = "N/A"
    
    try:
        start_time = time.perf_counter()
        await bot.db.command("ping") 
        db_ping = f"{round((time.perf_counter() - start_time) * 1000)}ms"
    except Exception as db_err:
        db_status = f"🔴 Disconnected ({type(db_err).__name__})"

    # Diagnose local library binary compliance
    ocr_status = "🟢 Operational (Local Native Tesseract)"
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        # Fallback automated lookup logic for Discloud containers
        try:
            for fallback_path in ['/app/.apt/usr/bin/tesseract', '/usr/bin/tesseract', 'tesseract']:
                pytesseract.pytesseract.tesseract_cmd = fallback_path
                try:
                    pytesseract.get_tesseract_version()
                    ocr_status = f"🟢 Operational ({fallback_path})"
                    break
                except Exception:
                    continue
            if "🟢" not in ocr_status:
                ocr_status = "🔴 Binary Path Missing / Configuration Error"
        except Exception as e:
            ocr_status = f"🔴 Configuration Error ({type(e).__name__})"

    # Calculate native system RAM constraints securely using built-in system states
    ram_used = 0.0
    try:
        with open('/proc/self/status', 'r') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    ram_used = round(int(line.split()) / 1024, 1)
                    break
    except Exception:
        ram_used = 0.0

    ram_total = 512
    ram_percent = round((ram_used / ram_total) * 100, 1) if ram_used > 0 else 0.0

    embed = discord.Embed(
        title="🛠️ ALU-GauntletEngine Core Diagnostics", 
        color=0x00ffcc if "🟢" in db_status and "🟢" in ocr_status else 0xffcc00,
        timestamp=interaction.created_at
    )
    embed.add_field(name="📡 Discord Gateway Ping", value=f"`{discord_ping}ms`", inline=True)
    embed.add_field(name="🗄️ MongoDB Cloud Link", value=f"Status: **{db_status}**\nLatency: `{db_ping}`", inline=False)
    embed.add_field(name="👁️ OCR Parser Engine", value=f"Status: **{ocr_status}**", inline=False)
    embed.add_field(name="☁️ Discloud Cluster Memory", value=f"Allocation: `{ram_used}MB` / `{ram_total}MB` (**{ram_percent}%**)", inline=False)
    embed.set_footer(text=f"Node Container Environment ID: {os.getenv('DISCLOUD_APP_ID', 'Localhost')}")

    await interaction.followup.send(embed=embed)
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    logging.error(f"Application command exception intercepted: {error}")
    if isinstance(error, app_commands.MissingPermissions):
        embed = discord.Embed(title="❌ Access Denied", description="This diagnostic interface command is gated strictly to Server Administrators.", color=0xff3333)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    embed = discord.Embed(title="⚠️ Application Engine Pipeline Failure", description="An unexpected error blocked processing.", color=0xff9900)
    await interaction.followup.send(embed=embed, ephemeral=True)

# Main Execution Routine Hook
if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if token:
        bot.run(token)
    else:
        logging.critical("DISCORD_BOT_TOKEN is missing from your Environment Variables.")
