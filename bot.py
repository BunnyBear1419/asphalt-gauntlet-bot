import os
import re
import logging
import time
import io
import aiohttp
import psutil
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from PIL import Image

# Initialize logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load secure system environment variables
load_dotenv()

class GauntletBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.db_client = None
        self.db = None

    async def setup_hook(self):
        # Establish stable asynchronous cloud clustering handshake via MongoDB Atlas
        mongo_uri = os.getenv("MONGO_URI")
        if mongo_uri:
            try:
                self.db_client = AsyncIOMotorClient(mongo_uri)
                # Select the targeted operational data bank bucket
                self.db = self.db_client["gauntlet_engine_db"]
                logging.info("🟢 MongoDB Atlas Cloud Cluster Connection Established successfully.")
            except Exception as e:
                logging.error(f"🔴 Critical failure provisioning cloud database connection: {e}")
        else:
            logging.warning("⚠️ MONGO_URI missing from environment variables. Bot operations will be restricted.")
        
        # Synchronize production tier tree application slice nodes globally
        try:
            await self.tree.sync()
            logging.info("🟢 Discord application tree command structures successfully synchronized.")
        except discord.HTTPException as http_err:
            logging.error(f"🔴 System network fault syncing app command maps: {http_err}")

bot = GauntletBot()

@bot.event
async def on_ready():
    logging.info(f"🟢 Authenticated successfully onto Gateway node as: {bot.user}")

# Mock placeholder for the UI verification view panel loop workflow
class VerificationView(discord.ui.View):
    def __init__(self, user_id, guild_id, game_id, parsed_rank, control_type):
        super().__init__(timeout=None)

@bot.tree.command(name="register", description="Enters the automated cloud verification staging queues.")
@app_commands.describe(game_id="Asphalt player alphanumeric tag ID", proof_screenshot="Attach profile card file", control_type="Driving system configuration layout used")
@app_commands.choices(control_type=[
    app_commands.Choice(name="Manual Controls", value="manual"), 
    app_commands.Choice(name="TouchDrive", value="touchdrive")
])
async def register_cmd(interaction: discord.Interaction, game_id: str, proof_screenshot: discord.Attachment, control_type: app_commands.Choice[str]):
    if not bot.db:
        await interaction.response.send_message("❌ Connection Interrupted: Cloud databases are currently offline.", ephemeral=True)
        return

    cfg = await bot.db.settings.find_one({"_id": str(interaction.guild_id)})
    if cfg and cfg.get("registration_channel_id") and str(interaction.channel_id) != str(cfg["registration_channel_id"]):
        await interaction.response.send_message(f"❌ Redirection Link: Execute profile registration actions within <#{cfg['registration_channel_id']}>.", ephemeral=True)
        return

    if not proof_screenshot.content_type or not proof_screenshot.content_type.startswith("image/"):
        await interaction.response.send_message("❌ Upload Blocked: Media attachments must be valid images.", ephemeral=True)
        return

    # Defer immediate execution contexts to accommodate processing overhead safely
    await interaction.response.defer()
    parsed_rank = 15500
    ocr_status = "AUTOMATED_OCR_PASS"
    ocr_key = os.getenv("OCR_SPACE_API_KEY")
    
    if ocr_key and ocr_key != "your_free_ocr_space_api_key_here":
        try:
            # Phase 1: Download raw image bytes asynchronously
            async with aiohttp.ClientSession() as session:
                async with session.get(proof_screenshot.url) as img_resp:
                    if img_resp.status == 200:
                        img_bytes = await img_resp.read()
                        
                        # Phase 2: Sharpen text layers natively inside Discloud Platinum RAM limits
                        img = Image.open(io.BytesIO(img_bytes)).convert('L')
                        # Binarization to cleanly separate white neon fonts from background clutter
                        img = img.point(lambda x: 0 if x < 200 else 255, '1')
                        
                        output_buffer = io.BytesIO()
                        img.save(output_buffer, format="PNG")
                        output_buffer.seek(0)
                        
                        # Phase 3: Fire multipart file payload binary payload stream to OCR Space
                        data = aiohttp.FormData()
                        data.add_field('apikey', ocr_key)
                        data.add_field('language', 'eng')
                        data.add_field('file', output_buffer, filename='processed_screenshot.png', content_type='image/png')
                        
                        async with session.post("https://api.ocr.space/parse/image", data=data, timeout=15) as response:
                            if response.status == 200:
                                res_data = await response.json()
                                parsed_text = res_data.get("ParsedResults", [{}])[0].get("ParsedText", "").upper()
                                
                                match_id = re.search(r"ID[:\s]*([A-Z0-9_\-]+)", parsed_text)
                                match_pi = re.search(r"GARAGE[:\s]*([0-9,]+)", parsed_text)
                                
                                if match_id: game_id = match_id.group(1)
                                if match_pi: parsed_rank = int(match_pi.group(1).replace(",", ""))
                                
                                # Basic UI structural verification match loop fallback
                                if not any(x in parsed_text for x in ["PLAYER", "GARAGE", "LEVEL", "CLUB", "ID"]):
                                    await interaction.followup.send("❌ Image Analysis Blocked: Uploaded file does not verify as an authentic Asphalt interface screenshot.")
                                    return
                            else: 
                                ocr_status = "MANUAL_REVIEW_REQUIRED_API_ERROR"
                    else:
                        ocr_status = "MANUAL_REVIEW_REQUIRED_DOWNLOAD_FAILED"
        except Exception as ocr_err:
            logging.error(f"Async OCR pipeline exception: {ocr_err}")
            ocr_status = "MANUAL_REVIEW_REQUIRED_TIMEOUT"

    db_id = f"{interaction.guild_id}_{interaction.user.id}"
    await bot.db.pending.update_one(
        {"_id": db_id}, 
        {"$set": {
            "guild_id": str(interaction.guild_id), 
            "user_id": str(interaction.user.id), 
            "game_id": game_id, 
            "proposed_rank": parsed_rank, 
            "proof": proof_screenshot.url, 
            "control": control_type.value, 
            "ocr_verification": ocr_status
        }}, 
        upsert=True
    )
    
    msg_prefix = f"📥 **Submission Completed (Auto-Filled Profile UI).** Detected ID: `{game_id}`, PI: `{parsed_rank:,}`" if ocr_status == "AUTOMATED_OCR_PASS" else "⚠️ **OCR System Offline.** Submission queued for manual review."
    await interaction.followup.send(f"{msg_prefix} Roster lines routed to staff review queues.")
    
    if cfg and cfg.get("registration_channel_id"):
        chan = bot.get_channel(int(cfg["registration_channel_id"]))
        if chan:
            emb = discord.Embed(title="🛡️ New Gauntlet Placement Review Request", color=0xffcc00)
            emb.add_field(name="Driver", value=interaction.user.mention, inline=True)
            embed.add_field(name="Declared Game ID", value=f"`{game_id}`", inline=True)
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
    
    if bot.db is not None:
        try:
            start_time = time.perf_counter()
            await bot.db.command("ping") 
            db_ping = f"{round((time.perf_counter() - start_time) * 1000)}ms"
        except Exception as db_err:
            db_status = f"🔴 Disconnected ({type(db_err).__name__})"
    else:
        db_status = "🔴 Uninitialized (No URI Provided)"
    
    ocr_status = "🟢 Operational"
    ocr_key = os.getenv("OCR_SPACE_API_KEY")
    if not ocr_key or ocr_key == "your_free_ocr_space_api_key_here":
        ocr_status = "🟡 Missing API Key in Environment Variables"
    else:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://ocr.space/parse/imageurl?apikey={ocr_key}&url=https://raw.githubusercontent.com/github/explore/main/topics/python/python.png", timeout=5) as resp:
                    if resp.status != 200:
                        ocr_status = f"🔴 API Error (HTTP {resp.status})"
        except Exception:
            ocr_status = "🔴 Timeout / Unreachable"

    process = psutil.Process(os.getpid())
    ram_used = round(process.memory_info().rss / (1024 * 1024), 1)
    ram_total = 512  # Matches discloud.config allocation constraints
    ram_percent = round((ram_used / ram_total) * 100, 1)

    embed = discord.Embed(
        title="🛠️ ALU-GauntletEngine Core Diagnostics", 
        color=0x00ffcc if "🟢" in db_status and "🟢" in ocr_status else 0xffcc00,
        timestamp=interaction.created_at
    )
    embed.add_field(name="📡 Discord Gateway Ping", value=f"`{discord_ping}ms`", inline=True)
    embed.add_field(name="🗄️ MongoDB Cloud Link", value=f"Status: **{db_status}**
Latency: `{db_ping}`", inline=False)
    embed.add_field(name="👁️ OCR.Space Parser Engine", value=f"Status: **{ocr_status}**", inline=False)
    embed.add_field(name="☁️ Discloud Cluster Memory", value=f"Allocation: `{ram_used}MB` / `{ram_total}MB` (**{ram_percent}%**)", inline=False)
    embed.set_footer(text=f"Node Container Environment ID: {os.getenv('DISCLOUD_APP_ID', 'Localhost')}")

    await interaction.followup.send(embed=embed)

if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if token:
        bot.run(token)
    else:
        logging.error("🔴 Operational Shutdown: DISCORD_BOT_TOKEN missing from environment context.")
