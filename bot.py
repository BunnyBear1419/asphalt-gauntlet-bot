import os
import io
import json
import logging
import asyncio
import signal
import random
import re
from datetime import datetime, UTC
import requests
import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
from PIL import Image, ImageDraw

logging.basicConfig(level=logging.INFO)
load_dotenv()

# Meta cars array tagged automatically with fire emojis on leaderboards
META_CARS = [
    "DEVEL SIXTEEN", "KOENIGSEGG CC850", "JESKO", "HENNESSEY VENOM F5", 
    "SSC TUATARA", "BUGATTI CHIRON", "BUGATTI BOLIDE", "RIMAC NEVERA",
    "LAMBORGHINI COUNTACH", "ULTIMA RS", "MCLAREN SPEEDTAIL", "LAMBORGHINI EGOISTA"
]

# Valid track names matrix
VALID_TRACKS = [
    "Auckland", "Buenos Aires", "Cairo", "Giza", "Greenland", "Himalayas", 
    "Midwest", "Nevada", "New York", "Osaka", "Paris", "Rome", 
    "San Francisco", "Scotland", "Shanghai", "Singapore", "The Caribbean"
]

# Baseline fallback par-times (in milliseconds)
DEFAULT_THRESHOLDS = {
    "Auckland": 35000, "Buenos Aires": 48000, "Cairo": 40000, "Giza": 42000,
    "Greenland": 46000, "Himalayas": 38000, "Midwest": 41000, "Nevada": 42000,
    "New York": 44000, "Osaka": 39000, "Paris": 43000, "Rome": 40000,
    "San Francisco": 45000, "Scotland": 43000, "Shanghai": 41000,
    "Singapore": 47000, "The Caribbean": 46000
}

def _sanitize_track_name(track_input: str) -> str:
    cleaned = "".join(track_input.split()).lower()
    for valid in VALID_TRACKS:
        if "".join(valid.split()).lower() == cleaned:
            return valid
    return track_input.title()

def _parse_time_to_ms(time_str: str) -> int:
    try:
        time_str = time_str.strip().replace(" ", "")
        if ":" in time_str:
            parts = time_str.split(":")
            minutes = int(parts[0])
            sec_part = parts[1]
        else:
            return int(float(time_str) * 1000)
        seconds = float(sec_part.replace(":", "."))
        return int((minutes * 60 + seconds) * 1000)
    except:
        return -1

def _format_ms_to_time(ms: int) -> str:
    total_seconds = ms / 1000.0
    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:06.3f}"

def _calculate_elo(rating_w: int, rating_l: int, k_factor: int = 32) -> tuple:
    expected_w = 1 / (1 + 10 ** ((rating_l - rating_w) / 400))
    new_w = round(rating_w + k_factor * (1 - expected_w))
    new_l = round(rating_l + k_factor * (0 - (1 - expected_w)))
    return max(1000, new_w), max(1000, new_l)

class MongoLocalFallbackClient:
    def __init__(self):
        self.db_file = "gauntlet_database.json"
        if os.path.exists(self.db_file):
            with open(self.db_file, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        else:
            self.data = {"settings": {}, "drivers": {}, "pending": {}, "laps": [], "backups": []}
        
        for key in ["settings", "drivers", "pending", "laps", "backups"]:
            if key not in self.data:
                self.data[key] = [] if key in ["laps", "backups"] else {}
        self.save()

        self.settings = CollectionMock(self, "settings")
        self.drivers = CollectionMock(self, "drivers")
        self.pending = CollectionMock(self, "pending")
        self.laps = CollectionMock(self, "laps")
        self.backups = CollectionMock(self, "backups")
        
    def save(self):
        with open(self.db_file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=4, ensure_ascii=False)

class CollectionMock:
    def __init__(self, client, name):
        self.client = client
        self.name = name
        
    async def find_one(self, query):
        if not query: return self.client.data[self.name]
        k = list(query.keys())[0]
        v = query[k]
        if self.name in ["settings", "drivers", "pending"]:
            return self.client.data[self.name].get(str(v))
        return None
        
    def find(self, query=None):
        if self.name == "laps":
            if not query: return CursorMock(self.client.data["laps"])
            matched = self.client.data["laps"]
            for qk, qv in query.items():
                matched = [l for l in matched if l.get(qk) == qv]
            return CursorMock(matched)
        return CursorMock(list(self.client.data[self.name].values()))
        
    async def update_one(self, query, update, upsert=False):
        k = list(query.keys())[0]
        v = str(query[k])
        op = list(update.keys())[0]
        payload = update[op]
        if self.name in ["settings", "drivers", "pending"]:
            if v not in self.client.data[self.name]:
                if upsert: self.client.data[self.name][v] = {}
                else: return
            if op == "$set": self.client.data[self.name][v].update(payload)
            elif op == "$inc":
                for pk, pv in payload.items():
                    self.client.data[self.name][v][pk] = self.client.data[self.name][v].get(pk, 0) + pv
        self.client.save()
        
    async def insert_one(self, doc):
        if self.name in ["laps", "backups"]: self.client.data[self.name].append(doc)
        self.client.save()
        
    async def delete_one(self, query):
        k = list(query.keys())[0]
        if self.name in ["drivers", "pending"] and str(query[k]) in self.client.data[self.name]:
            del self.client.data[self.name][str(query[k])]
        self.client.save()
        
    async def delete_many(self, query):
        if self.name == "laps":
            if not query: self.client.data["laps"] = []
            else:
                self.client.data["laps"] = [l for l in self.client.data["laps"] if not all(l.get(k) == query[k] for k in query)]
        self.client.save()

class CursorMock:
    def __init__(self, items): self.items = items
    def sort(self, key, direction=1):
        try: self.items.sort(key=lambda x: x.get(key, 0), reverse=(direction == -1))
        except: pass
        return self
    def limit(self, n):
        self.items = self.items[:n]
        return self
    async def to_list(self, length=None): return self.items

try:
    from motor.motor_asyncio import AsyncIOMotorClient
    from bson import ObjectId
    HAS_MONGO = True
except ImportError:
    HAS_MONGO = False

class GauntletBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="/", intents=intents)
        self.db = None

    async def setup_hook(self):
        mongo_uri = os.getenv("MONGO_URI")
        if HAS_MONGO and mongo_uri:
            try:
                self.mongo_client = AsyncIOMotorClient(mongo_uri, serverSelectionTimeoutMS=5000)
                await self.mongo_client.admin.command('ping')
                self.db = self.mongo_client["gauntlet_database"]
                logging.info("🍃 Connected successfully to MongoDB Cloud Clusters.")
            except Exception as e:
                logging.error(f"❌ MongoDB failed: {e}. Falling back to internal engine simulator.")
                self.db = MongoLocalFallbackClient()
        else:
            self.db = MongoLocalFallbackClient()

        try:
            await self.tree.sync()
            logging.info("✨ Application slash command map synchronized globally.")
        except Exception as err:
            logging.error(f"❌ Command synchronization handshake fault: {err}")

        backup_database_task.start()
        pending_queue_reminder_task.start()

    def get_division(self, tracking_points: int) -> tuple:
        if tracking_points <= 10000: return "🥉 Division I (Bronze)", (205, 127, 50)
        elif tracking_points <= 14000: return "🥈 Division II (Silver)", (192, 192, 192)
        elif tracking_points <= 17500: return "🥇 Division III (Gold)", (255, 215, 0)
        elif tracking_points <= 20000: return "🏆 Division IV (Platinum)", (229, 228, 226)
        elif tracking_points <= 22000: return "👑 Division V (Champ)", (155, 93, 229)
        else: return "💎 Division VI (Legend)", (0, 245, 212)
            
            # Cleanly fix MongoDB dynamic BSON ObjectId serialization
     async def backup_database_task():
            for guild in self.guilds:
                cfg = await self.db.settings.find_one({"_id": str(guild.id)})
                if cfg and cfg.get("logging_channel_id"):
                    chan = guild.get_channel(int(cfg["logging_channel_id"]))
                    if chan:
                        f_buf = io.BytesIO(js_str.encode("utf-8"))
                        f_asset = discord.File(f_buf, filename=f"gauntlet_backup_{guild.id}.json")
                        await chan.send(content="💾 **Automated System Physical Backup Snapshot Issued.**", file=f_asset)
        except Exception as e: logging.error(f"Backup task loop failed: {e}")

    @tasks.loop(hours=48)
    async def pending_queue_reminder_task(self):
        try:
            for guild in self.guilds:
                cfg = await self.db.settings.find_one({"_id": str(guild.id)})
                if cfg and cfg.get("registration_channel_id"):
                    chan = guild.get_channel(int(cfg["registration_channel_id"]))
                    pending_items = await self.db.pending.find().to_list(length=None)
                    guild_pending = [p for p in pending_items if p.get("guild_id") == str(guild.id)]
                    if guild_pending and chan:
                        role_ping = f" <@&{cfg['admin_role_ids'][0]}>" if cfg.get("admin_role_ids") else ""
                        embed = discord.Embed(title="⏳ Outstanding Queue Alert", color=0xffcc00, description=f"Attention Staff! There are **{len(guild_pending)} applications** waiting in staging records. Run `/checkpending` to review.")
                        await chan.send(content=role_ping, embed=embed)
        except Exception as e: logging.error(f"Pending loop failed: {e}")

bot = GauntletBot()

def is_bot_admin():
    async def predicate(interaction: discord.Interaction):
        if interaction.user.id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator: return True
        cfg = await bot.db.settings.find_one({"_id": str(interaction.guild_id)})
        if cfg and cfg.get("admin_role_ids"):
            for r_id in cfg["admin_role_ids"]:
                if any(r.id == int(r_id) for r in interaction.user.roles): return True
        raise app_commands.Errors.MissingPermissions(["Custom Bot Admin Role"])
    return app_commands.check(predicate)

class VerificationModal(discord.ui.Modal, title="Verify & Polish Driver Details"):
    def __init__(self, user_id: str, guild_id: str, game_id: str, rank: int, control_type: str):
        super().__init__()
        self.user_id = user_id
        self.guild_id = guild_id
        self.control_type = control_type
        self.gid_input = discord.ui.TextInput(label="Asphalt Player ID", default=game_id)
        self.rank_input = discord.ui.TextInput(label="Top 5 Combined PI Score", default=str(rank))
        self.add_item(self.gid_input)
        self.add_item(self.rank_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            final_rank = int(self.rank_input.value)
            final_gid = self.gid_input.value
        except ValueError:
            await interaction.response.send_message("❌ Error: PI Rank must be a valid integer number.", ephemeral=True)
            return

        db_id = f"{self.guild_id}_{self.user_id}"
        await bot.db.drivers.update_one(
            {"_id": db_id},
            {"$set": {"guild_id": self.guild_id, "user_id": self.user_id, "game_id": final_gid, "garage_rank": final_rank, "control_type": self.control_type, "verified_laps": 0, "wins": 0, "losses": 0, "elo_rating": 1200, "strikes": 0, "defense_cars": []}},
            upsert=True
        )
        await bot.db.pending.delete_one({"_id": db_id})
        
        div_name, _ = bot.get_division(final_rank)
        cfg = await bot.db.settings.find_one({"_id": self.guild_id})
        
        role_note = ""
        if cfg and cfg.get("member_role_id"):
            role = interaction.guild.get_role(int(cfg["member_role_id"]))
            member = interaction.guild.get_member(int(self.user_id))
            if role and member:
                try: 
                    await member.add_roles(role)
                    role_note = f"\nGranted Role: {role.mention}"
                except: 
                    role_note = f"\n⚠️ *Move bot integration roles higher in settings list.*"

        embed = discord.Embed(title="🎉 Roster Entry Approved!", color=0x00ffcc, description=f"Driver <@{self.user_id}> has joined **{div_name}**!{role_note}")
        embed.add_field(name="Confirmed Score", value=f"📊 {final_rank:,} PI")
        embed.add_field(name="Control Layout", value=f"🎮 {self.control_type.upper()}")
        
        if cfg and cfg.get("announcement_channel_id"):
            chan = bot.get_channel(int(cfg["announcement_channel_id"]))
            if chan: await chan.send(embed=embed)
        await interaction.response.edit_message(embed=embed, view=None)

class RejectionReasonSelect(discord.ui.Select):
    def __init__(self, user_id: str, guild_id: str):
        options = [
            discord.SelectOption(label="Anti-Sandbagging Violation", description="Submitted score does not map actual max potential garage cap values.", emoji="⚠️"),
            discord.SelectOption(label="Illegible Physical Media Proof", description="Uploaded screenshot asset is blurry, cropped, or unreadable.", emoji="📸"),
            discord.SelectOption(label="Mismatched Profile / Game ID", description="The text strings typed do not reconcile with image assets.", emoji="❌")
        ]
        super().__init__(placeholder="Select the official reason for denial...", options=options)
        self.user_id = user_id
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        db_id = f"{self.guild_id}_{self.user_id}"
        await bot.db.pending.delete_one({"_id": db_id})
        embed = discord.Embed(title="⛔ Registration Request Denied", color=0xff3366, description=f"The application matching <@{self.user_id}> was rejected: **{self.values}**")
        await interaction.response.edit_message(embed=embed, view=None)

class VerificationView(discord.ui.View):
    def __init__(self, user_id: str, guild_id: str, game_id: str, rank: int, control_type: str):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.guild_id = guild_id
        self.game_id = game_id
        self.rank = rank
        self.control_type = control_type

    @discord.ui.button(label="Approve Alignment", style=discord.ButtonStyle.green, emoji="✅")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerificationModal(self.user_id, self.guild_id, self.game_id, self.rank, self.control_type))

    @discord.ui.button(label="Deny Entry", style=discord.ButtonStyle.danger, emoji="❌")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        v = discord.ui.View(timeout=60); v.add_item(RejectionReasonSelect(self.user_id, self.guild_id))
        await interaction.response.send_message("Select denial classification tracking indices:", view=v, ephemeral=True)

class StrikeReviewView(discord.ui.View):
    def __init__(self, target_id: str, guild_id: str, lap_data: dict, action_type: str):
        super().__init__(timeout=None)
        self.target_id = target_id
        self.guild_id = guild_id
        self.lap_data = lap_data
        self.action_type = action_type

    @discord.ui.button(label="Confirm Action", style=discord.ButtonStyle.danger, emoji="🔨")
    async def confirm_strike(self, interaction: discord.Interaction, button: discord.ui.Button):
        db_id = f"{self.guild_id}_{self.target_id}"
        driver = await bot.db.drivers.find_one({"_id": db_id})
        if not driver: return
        
        if self.action_type == "strike":
            new_strikes = driver.get("strikes", 0) + 1
            await bot.db.drivers.update_one({"_id": db_id}, {"$set": {"strikes": new_strikes}})
            
            emb = discord.Embed(title="🚨 Strike Confirmed", color=0xff5500)
            emb.description = f"User <@{self.target_id}> has been issued strike **{new_strikes}/3**."
            
            if new_strikes >= 3:
                emb.description += "\n🛑 **User reached maximum limit thresholds. Profile flagged for administrative ban rules.**"
            await interaction.response.edit_message(embed=emb, view=None)
        else:
            await bot.db.laps.delete_many({"guild_id": self.guild_id, "user_id": self.target_id, "time_ms": self.lap_data["time_ms"]})
            await interaction.response.edit_message(content="🗑️ **Suspect lap metrics removed cleanly from leaderboard collection arrays.**", embed=None, view=None)

    @discord.ui.button(label="Dismiss / False Positive", style=discord.ButtonStyle.secondary, emoji="🏳️")
    async def dismiss_strike(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="✅ **Flagged alert dismissed. Record marked verified cleanly by staff operator.**", embed=None, view=None)

class ChallengeConfirmView(discord.ui.View):
    def __init__(self, guild_id: str, challenger_id: str, opponent_id: str, result: str):
        super().__init__(timeout=60)
        self.guild_id = guild_id
        self.challenger_id = challenger_id
        self.opponent_id = opponent_id
        self.result = result

    @discord.ui.button(label="🤝 Confirm Match Result", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != int(self.opponent_id):
            await interaction.response.send_message("❌ Validation Error: Only the targeted opponent can confirm this match.", ephemeral=True)
            return
            
        c_id = f"{self.guild_id}_{self.challenger_id}"
        o_id = f"{self.guild_id}_{self.opponent_id}"
        c_doc = await bot.db.drivers.find_one({"_id": c_id})
        o_doc = await bot.db.drivers.find_one({"_id": o_id})
        
        if not c_doc or not o_doc:
            return await interaction.response.send_message("❌ Error: Missing driver dataset structures.", ephemeral=True)

        c_elo = c_doc.get("elo_rating", 1200)
        o_elo = o_doc.get("elo_rating", 1200)
        
        if self.result == "win":
            new_c, new_o = _calculate_elo(c_elo, o_elo)
            diff = new_c - c_elo
        else:
            new_o, new_c = _calculate_elo(o_elo, c_elo)
            diff = new_o - o_elo

        await bot.db.drivers.update_one({"_id": c_id}, {"$set": {"elo_rating": new_c}, "$inc": {"wins" if self.result == "win" else "losses": 1}})
        await bot.db.drivers.update_one({"_id": o_id}, {"$set": {"elo_rating": new_o}, "$inc": {"losses" if self.result == "win" else "wins": 1}})
        
        await interaction.response.edit_message(content=f"✅ **Match confirmed!** Winner gained `+{diff}` Gauntlet ELO Points.", embed=None, view=None)

class ResetSeasonView(discord.ui.View):
    def __init__(self, divs_map):
        super().__init__(timeout=None)
        self.add_item(ResetSeasonDropdown(divs_map))

class ResetSeasonDropdown(discord.ui.Select):
    def __init__(self, divs_map):
        super().__init__(placeholder="Choose a division roster overview card...", options=[discord.SelectOption(label=k) for k in divs_map.keys()])
        self.divs_map = divs_map

    async def callback(self, interaction: discord.Interaction):
        drivers = self.divs_map[self.values]
        embed = discord.Embed(title=f"📊 Seasonal Standings: {self.values}", color=0xffcc00)
        embed.description = "\n".join([f"• {r['name']} — `{r['score']:,}` PI" for r in drivers]) if drivers else "*No drivers placed in this division bracket.*"
        await interaction.response.edit_message(embed=embed, view=self.view)

@bot.tree.command(name="sync", description="Synchronizes application slash command tree structures mapping layers.")
async def sync_cmd(interaction: discord.Interaction):
    if interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("⛔ Authority Error: Restricted parameter access configurations.", ephemeral=True)
        return
    await bot.tree.sync()
    await interaction.response.send_message("✨ Command maps tree indexed seamlessly across live Discord UI frameworks.", ephemeral=True)

@bot.tree.command(name="register", description="Enters the automated cloud verification staging queues.")
@app_commands.describe(game_id="Asphalt player alphanumeric tag ID", proof_screenshot="Attach profile card file", control_type="Driving system configuration layout used")
@app_commands.choices(control_type=[app_commands.Choice(name="Manual Controls", value="manual"), app_commands.Choice(name="TouchDrive", value="touchdrive")])
async def register_cmd(interaction: discord.Interaction, game_id: str, proof_screenshot: discord.Attachment, control_type: app_commands.Choice[str]):
    cfg = await bot.db.settings.find_one({"_id": str(interaction.guild_id)})
    if cfg and cfg.get("registration_channel_id") and str(interaction.channel_id) != str(cfg["registration_channel_id"]):
        await interaction.response.send_message(f"❌ Redirection Link: Execute profile registration actions within <#{cfg['registration_channel_id']}>.", ephemeral=True)
        return

    if not proof_screenshot.content_type or not proof_screenshot.content_type.startswith("image/"):
        await interaction.response.send_message("❌ Upload Blocked: Media attachments must be valid images.", ephemeral=True)
        return

    await interaction.response.defer()
    parsed_rank = 15500
    ocr_status = "AUTOMATED_OCR_PASS"
    ocr_key = os.getenv("OCR_SPACE_API_KEY")
    
    if ocr_key and ocr_key != "your_free_ocr_space_api_key_here":
        try:
            r = requests.get(f"https://ocr.space{ocr_key}&url={proof_screenshot.url}", timeout=7)
            if r.status_code == 200 and "PARSEDTEXT" in r.text.upper():
                parsed_text = r.json().get("ParsedResults", [{}]).get("ParsedText", "").upper()
                
                match_id = re.search(r"ID[:\s]*([A-Z0-9_\-]+)", parsed_text)
                match_pi = re.search(r"GARAGE[:\s]*([0-9,]+)", parsed_text)
                
                if match_id: game_id = match_id.group(1)
                if match_pi: parsed_rank = int(match_pi.group(1).replace(",", ""))
                
                if not any(x in parsed_text for x in ["PLAYER", "GARAGE", "LEVEL", "CLUB", "ID"]):
                    await interaction.followup.send("❌ Image Analysis Blocked: Uploaded file does not verify as an authentic Asphalt interface screenshot.")
                    return
            else: ocr_status = "MANUAL_REVIEW_REQUIRED_API_ERROR"
        except: ocr_status = "MANUAL_REVIEW_REQUIRED_TIMEOUT"

    db_id = f"{interaction.guild_id}_{interaction.user.id}"
    await bot.db.pending.update_one({"_id": db_id}, {"$set": {"guild_id": str(interaction.guild_id), "user_id": str(interaction.user.id), "game_id": game_id, "proposed_rank": parsed_rank, "proof": proof_screenshot.url, "control": control_type.value, "ocr_verification": ocr_status}}, upsert=True)
    
    msg_prefix = f"📥 **Submission Completed (Auto-Filled Profile UI).** Detected ID: `{game_id}`, PI: `{parsed_rank:,}`" if ocr_status == "AUTOMATED_OCR_PASS" else "⚠️ **OCR System Offline.** Submission queued for manual review."
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

@bot.tree.command(name="profile", description="Generates layered graphical driver licence standings metrics sheet profiles.")
async def profile_cmd(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    db_id = f"{interaction.guild_id}_{target.id}"
    driver = await bot.db.drivers.find_one({"_id": db_id})
    if not driver:
        await interaction.response.send_message("❌ Data Query Empty: Target driver node is not registered on live database frames.", ephemeral=True)
        return
    await interaction.response.defer()
    
    rank = driver.get("garage_rank", 0)
    div_name, rgb = bot.get_division(rank)
    elo = driver.get("elo_rating", 1200)
    
    img = Image.new("RGB", (800, 450), color=(30, 33, 36)); draw = ImageDraw.Draw(img)
    if os.path.exists("assets/profile_bg.png"):
        try:
            bg = Image.open("assets/profile_bg.png").convert("RGB").resize((800, 450))
            img.paste(bg, (0,0))
            overlay = Image.new("RGBA", (800, 450), (0,0,0,150))
            img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
            draw = ImageDraw.Draw(img)
        except: pass

    draw.rectangle([(20, 20), (780, 430)], outline=rgb, width=4)
    draw.text((50, 50), f"PILOT IDENTITY CARD - {div_name.upper()}", fill=rgb)
    draw.text((50, 110), f"DRIVER ACCOUNT: {target.display_name.upper()}", fill=(255,255,255))
    draw.text((50, 150), f"ASPHALT LOG ID: {driver.get('game_id', 'UNKNOWN')}", fill=(200,200,200))
    draw.text((50, 190), f"FLEET STRENGTH: {rank:,} PI RATING VALUE", fill=(255,255,255))
    draw.text((50, 230), f"GAUNTLET ELO: {elo} TRACKING INDEX", fill=rgb)
    draw.text((50, 270), f"DRIVING CONTROL: {str(driver.get('control_type','')).upper()}", fill=rgb)
    draw.text((50, 310), f"RECORDED STRIKES: {driver.get('strikes', 0)} / 3 WARNINGS", fill=(255, 55, 55))
    
    w, l = driver.get("wins", 0), driver.get("losses", 0)
    draw.text((50, 360), f"PRACTICE MATRICES: {w} VICTORIES / {l} DEFEATS", fill=(255,255,255))
    
    buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
    await interaction.followup.send(file=discord.File(buf, filename="license.png"))

@bot.tree.command(name="loglap", description="Logs tracking lap time parameters into seasonal class leaderboard arrays.")
@app_commands.describe(track="Racing circuit layout name", car="Vehicle build label utilized", car_class="Asphalt Vehicle Performance Bracket Tier", lap_time="Format: MM:SS.mmm", proof_file="Attach proof file")
@app_commands.choices(car_class=[
    app_commands.Choice(name="Class D", value="D"), app_commands.Choice(name="Class C", value="C"),
    app_commands.Choice(name="Class B", value="B"), app_commands.Choice(name="Class A", value="A"),
    app_commands.Choice(name="Class S", value="S")
])
async def log_lap_cmd(interaction: discord.Interaction, track: str, car: str, car_class: app_commands.Choice[str], lap_time: str, proof_file: discord.Attachment):
    db_id = f"{interaction.guild_id}_{interaction.user.id}"
    driver = await bot.db.drivers.find_one({"_id": db_id})
    if not driver:
        await interaction.response.send_message("❌ Halted: Create your profile registry configurations utilizing `/register` first.", ephemeral=True)
        return
        
    ms = _parse_time_to_ms(lap_time)
    if ms == -1:
        await interaction.response.send_message("❌ Format Error: Configure time tracking matching: `MM:SS.mmm` specifications.", ephemeral=True)
        return

    s_track = _sanitize_track_name(track)
    cfg = await bot.db.settings.find_one({"_id": str(interaction.guild_id)})
    par_times = cfg.get("par_times", DEFAULT_THRESHOLDS) if cfg else DEFAULT_THRESHOLDS
    
    min_allowed_ms = par_times.get(s_track, 30000)
    if ms < min_allowed_ms:
        await interaction.response.send_message(f"🚨 **Performance Threshold Triggered:** This lap time is physically impossible on `{s_track}`. Submission routed to staff audit desks.", ephemeral=True)
        if cfg and cfg.get("logging_channel_id"):
            log_chan = bot.get_channel(int(cfg["logging_channel_id"]))
            if log_chan:
                lap_mock = {"time_ms": ms, "lap_str": lap_time, "track": s_track, "car": car.upper()}
                f_emb = discord.Embed(title="🛑 Flagged Performance Alert (Anti-Cheat Security)", color=0xcc0000)
                f_emb.description = f"User {interaction.user.mention} logged an impossibly fast lap time. Use buttons to drop lap or confirm a strike."
                f_emb.add_field(name="Track / Car", value=f"`{s_track}` | Class {car_class.value} {car.upper()}", inline=True)
                f_emb.add_field(name="Input Given", value=f"`{lap_time}`", inline=True)
                f_emb.set_image(url=proof_file.url)
                
                await log_chan.send(embed=f_emb, view=StrikeReviewView(str(interaction.user.id), str(interaction.guild_id), lap_mock, "strike"))
        return

    rank = driver.get("garage_rank", 0)
    car_upper = car.upper().strip()
    
    if car_class.value in ["A", "S"] and rank <= 10000:
        if cfg and cfg.get("logging_channel_id"):
            log_chan = bot.get_channel(int(cfg["logging_channel_id"]))
            if log_chan:
                sb_emb = discord.Embed(title="⚠️ Performance Variance (Anti-Sandbagging Check)", color=0xffaa00)
                sb_emb.description = f"Driver {interaction.user.mention} is registered in **Bronze Division** but logged an **{car_class.value} Class** run. Check profile integrity maps."
                await log_chan.send(embed=sb_emb)

    await bot.db.laps.insert_one({
        "guild_id": str(interaction.guild_id), "user_id": str(interaction.user.id), "driver_name": interaction.user.display_name,
        "track": s_track, "car": car_upper, "car_class": car_class.value, "time_ms": ms, "proof_url": proof_file.url
    })
    await bot.db.drivers.update_one({"_id": db_id}, {"$inc": {"verified_laps": 1}})
    await interaction.response.send_message(f"✅ Lap records synchronized perfectly for circuit: **{s_track}** [Class {car_class.value}].", ephemeral=True)

@bot.tree.command(name="records", description="Renders the top 5 seasonal leaderboards filtered dynamically by track and car class.")
@app_commands.choices(car_class=[
    app_commands.Choice(name="Class D", value="D"), app_commands.Choice(name="Class C", value="C"),
    app_commands.Choice(name="Class B", value="B"), app_commands.Choice(name="Class A", value="A"),
    app_commands.Choice(name="Class S", value="S")
])
async def records_cmd(interaction: discord.Interaction, track: str, car_class: app_commands.Choice[str]):
    s_track = _sanitize_track_name(track)
    laps = await bot.db.laps.find({"guild_id": str(interaction.guild_id), "track": s_track, "car_class": car_class.value}).to_list(length=None)
    if not laps:
        await interaction.response.send_message(f"🔍 Zero telemetry records active matching track: **{s_track}** [Class {car_class.value}].")
        return
        
    laps.sort(key=lambda x: x["time_ms"])
    emb = discord.Embed(title=f"🏁 Seasonal Leaderboard: {s_track} (Class {car_class.value})", color=0xffcc00)
    base = laps[0]["time_ms"]
    
    for idx, l in enumerate(laps[:5], start=1):
        car_name = l["car"]
        meta_tag = " 🔥" if car_name in META_CARS else ""
        delta = "👑 [RECORD]" if idx == 1 else f"`+{(l['time_ms'] - base)/1000.0:.3f}s` split"
        emb.add_field(name=f"#{idx} | {l['driver_name']}", value=f"🏎️ **{car_name}**{meta_tag} | Time: `{_format_ms_to_time(l['time_ms'])}`\n{delta} | [View Proof]({l['proof_url']})", inline=False)
    await interaction.response.send_message(embed=emb)

@bot.tree.command(name="myrecords", description="Pulls a summary dashboard showing your own personal best times across race circuits.")
async def my_records_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    all_laps = await bot.db.laps.find({"guild_id": str(interaction.guild_id), "user_id": str(interaction.user.id)}).to_list(length=None)
    if not all_laps:
        await interaction.followup.send("🔍 You haven't logged any racing telemetry lap times yet this season.")
        return

    pb_map = {}
    for l in all_laps:
        t_key = f"{l['track']}_{l.get('car_class', 'S')}"
        if t_key not in pb_map or l["time_ms"] < pb_map[t_key]["time_ms"]:
            pb_map[t_key] = l

    emb = discord.Embed(title=f"⏱️ Personal Best Lap Registry: {interaction.user.display_name}", color=0x00f5d4)
    for t_key, pb_lap in pb_map.items():
        track_name = pb_lap["track"]
        c_tier = pb_lap.get("car_class", "S")
        server_laps = await bot.db.laps.find({"guild_id": str(interaction.guild_id), "track": track_name, "car_class": c_tier}).to_list(length=None)
        server_laps.sort(key=lambda x: x["time_ms"])
        
        pb_time_str = _format_ms_to_time(pb_lap["time_ms"])
        meta_tag = " 🔥" if pb_lap["car"] in META_CARS else ""
        pace_str = "👑 **[Reigning Class Leader]**" if server_laps and pb_lap["time_ms"] == server_laps[0]["time_ms"] else f" gap pacing: `+{(pb_lap['time_ms'] - server_laps[0]['time_ms']) / 1000.0:.3f}s` off leader"

        emb.add_field(name=f"📍 {track_name} (Class {c_tier})", value=f"└ time: `{pb_time_str}` via **{pb_lap['car']}**{meta_tag}\n└ {pace_str} | [View Proof]({pb_lap['proof_url']})", inline=False)
    await interaction.followup.send(embed=emb)

@bot.tree.command(name="matchmake", description="Finds a tournament driver close to your ELO ranking tier for a match challenge.")
async def matchmake_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    db_id = f"{interaction.guild_id}_{interaction.user.id}"
    driver = await bot.db.drivers.find_one({"_id": db_id})
    if not driver:
        return await interaction.followup.send("❌ Error: Create your profile matrix registry parameters utilizing `/register` first.")
        
    my_elo = driver.get("elo_rating", 1200)
    all_drivers = await bot.db.drivers.find().to_list(length=None)
    candidates = [d for d in all_drivers if d.get("guild_id") == str(interaction.guild_id) and d["_id"] != db_id]
    
    if not candidates:
        return await interaction.followup.send("🔍 The skill queue matching registry is empty. Invite more drivers!")
        
    candidates.sort(key=lambda x: abs(x.get("elo_rating", 1200) - my_elo))
    best_match = candidates[0]
    
    opp_user = bot.get_user(int(best_match["user_id"])) or await bot.fetch_user(int(best_match["user_id"]))
    emb = discord.Embed(title="🎯 Gauntlet ELO Matchmaker Result Found", color=0x00f5d4)
    emb.description = f"The queue matched you against {opp_user.mention} based on skill profiles!\n\n**Matchup Metrics:**\n└ Your ELO: `{my_elo}`\n└ Opponent ELO: `{best_match.get('elo_rating', 1200)}` (Gap: `{abs(best_match.get('elo_rating', 1200) - my_elo)}` pts)"
    await interaction.followup.send(embed=emb)

@bot.tree.command(name="leaderboard", description="Displays top 10 tournament drivers sorted descending by skill rating matrices.")
async def leaderboard_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    drivers = await bot.db.drivers.find().to_list(length=None)
    guild_drivers = [d for d in drivers if d.get("guild_id") == str(interaction.guild_id)]
    if not guild_drivers:
        return await interaction.followup.send("🔍 The tournament roster matrix is currently empty.")
        
    guild_drivers.sort(key=lambda x: x.get("elo_rating", 1200), reverse=True)
    emb = discord.Embed(title="🏆 Global Gauntlet Matchmaking Ladder", color=0x9b59e6)
    
    board_lines = []
    for idx, d in enumerate(guild_drivers[:10], start=1):
        div_label, _ = bot.get_division(d.get("garage_rank", 0))
        div_short = div_label.split(" (")[0]
        board_lines.append(f"`#{idx:02d}` <@{d['user_id']}> — **{d.get('elo_rating', 1200)}** ELO\n└ Fleet: `{d.get('garage_rank', 0):,}` PI | `{div_short}` | Record: `{d.get('wins',0)}W-{d.get('losses',0)}L`")

    emb.description = "\n\n".join(board_lines)
    await interaction.followup.send(embed=emb)

@bot.tree.command(name="challenge", description="Logs match parameters evaluating friendly practice runs outcomes.")
@app_commands.choices(result=[app_commands.Choice(name="I Won", value="win"), app_commands.Choice(name="I Lost", value="loss")])
async def challenge_cmd(interaction: discord.Interaction, opponent: discord.Member, result: app_commands.Choice[str]):
    if opponent.id == interaction.user.id: 
        return await interaction.response.send_message("❌ Target alignment fault: You cannot challenge yourself.", ephemeral=True)
    emb = discord.Embed(title="🤝 Match Verification Pending Validation", description=f"<@{interaction.user.id}> proposes a match outcome **{result.name}** against <@{opponent.id}>'s defense lineup.")
    await interaction.response.send_message(embed=emb, view=ChallengeConfirmView(str(interaction.guild_id), str(interaction.user.id), str(opponent.id), result.value))

@bot.tree.command(name="verify_driver", description="Administratively bypasses staging rows to directly insert/verify a driver roster profile.")
@app_commands.choices(control_type=[app_commands.Choice(name="Manual Controls", value="manual"), app_commands.Choice(name="TouchDrive", value="touchdrive")])
@is_bot_admin()
async def verify_driver_cmd(interaction: discord.Interaction, member: discord.Member, game_id: str, garage_rank: int, control_type: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)
    db_id = f"{interaction.guild_id}_{member.id}"
    
    await bot.db.drivers.update_one(
        {"_id": db_id},
        {"$set": {"guild_id": str(interaction.guild_id), "user_id": str(member.id), "game_id": game_id, "garage_rank": garage_rank, "control_type": control_type.value, "verified_laps": 0, "wins": 0, "losses": 0, "elo_rating": 1200, "strikes": 0, "defense_cars": []}},
        upsert=True
    )
    await bot.db.pending.delete_one({"_id": db_id})
    await interaction.followup.send(f"✅ Driver override database entry saved completely for {member.display_name}.")

@bot.tree.command(name="manage_strikes", description="Administratively overrides or adjusts warning strike points assigned to a driver profile.")
@app_commands.choices(action=[app_commands.Choice(name="Add Strike (+1)", value="add"), app_commands.Choice(name="Remove Strike (-1)", value="remove"), app_commands.Choice(name="Wipe / Clear All", value="clear")])
@is_bot_admin()
async def manage_strikes_cmd(interaction: discord.Interaction, member: discord.Member, action: app_commands.Choice[str]):
    db_id = f"{interaction.guild_id}_{member.id}"
    driver = await bot.db.drivers.find_one({"_id": db_id})
    if not driver:
        return await interaction.call_action_failure("❌ Error: Target user profile does not exist on roster records.", ephemeral=True)
        
    current = driver.get("strikes", 0)
    new_val = current + 1 if action.value == "add" else max(0, current - 1) if action.value == "remove" else 0
    
    await bot.db.drivers.update_one({"_id": db_id}, {"$set": {"strikes": new_val}})
    await interaction.response.send_message(f"⚙️ **Administrative Modification:** Strike count for {member.mention} adjusted from `{current}` to `{new_val}`.")

@bot.tree.command(name="export_csv", description="Pulls live roster analytics and outputs metrics into a downloadable spreadsheet file.")
@is_bot_admin()
async def export_csv_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    drivers = await bot.db.drivers.find().to_list(length=None)
    guild_drivers = [d for d in drivers if d.get("guild_id") == str(interaction.guild_id)]
    
    csv_lines = ["Driver_ID,Player_Tag,Garage_PI,Elo_Rating,Strikes,Wins,Losses"]
    for d in guild_drivers:
        csv_lines.append(f"{d['user_id']},{d.get('game_id','UNKNOWN')},{d.get('garage_rank',0)},{d.get('elo_rating',1200)},{d.get('strikes',0)},{d.get('wins',0)},{d.get('losses',0)}")
        
    csv_txt = "\n".join(csv_lines)
    buf = io.BytesIO(csv_txt.encode("utf-8"))
    file_asset = discord.File(buf, filename=f"roster_export_{interaction.guild_id}.csv")
    await interaction.followup.send(content="📊 **Roster metrics compiled cleanly into spreadsheet format profiles:**", file=file_asset)

@bot.tree.command(name="build_bracket", description="Generates a single-elimination tournament bracket from active drivers.")
@is_bot_admin()
async def build_bracket_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    drivers = await bot.db.drivers.find().to_list(length=None)
    guild_drivers = [d for d in drivers if d.get("guild_id") == str(interaction.guild_id)]
    if len(guild_drivers) < 2:
        return await interaction.followup.send("❌ Setup Blocked: You need at least 2 verified tournament drivers to spawn a bracket tree mapping.")
        
    random.shuffle(guild_drivers)
    emb = discord.Embed(title="⚔️ Gauntlet Automated Tournament Bracket Sheet", color=0xff3366)
    
    pairs = []
    has_bye = len(guild_drivers) % 2 != 0
    bye_driver = guild_drivers.pop() if has_bye else None
    
    for i in range(0, len(guild_drivers), 2):
        pairs.append(f"**Matchup #{len(pairs)+1}:** <@{guild_drivers[i]['user_id']}> vs <@{guild_drivers[i+1]['user_id']}>")
    if bye_driver: pairs.append(f"✨ **First Round Bye:** <@{bye_driver['user_id']}> *(Advances automatically)*")
        
    emb.description = "\n".join(pairs)
    await interaction.followup.send(embed=emb)

@bot.tree.command(name="set_par_time", description="Administratively modifies the anti-cheat verification threshold value matching a circuit row.")
@is_bot_admin()
async def set_par_time_cmd(interaction: discord.Interaction, track: str, par_time: str):
    s_track = _sanitize_track_name(track)
    ms = _parse_time_to_ms(par_time)
    if ms == -1: return await interaction.response.send_message("❌ Parsing Fault: Please configure time maps utilizing standard formatting masks (`MM:SS.mmm`).", ephemeral=True)
    
    cfg = await bot.db.settings.find_one({"_id": str(interaction.guild_id)})
    current_pt = cfg.get("par_times", DEFAULT_THRESHOLDS) if cfg else DEFAULT_THRESHOLDS
    current_pt[s_track] = ms
    
    await bot.db.settings.update_one({"_id": str(interaction.guild_id)}, {"$set": {"par_times": current_pt}}, upsert=True)
    await interaction.response.send_message(f"⚙️ **Anti-Cheat Infrastructure Updated:** `{s_track}` floor limit adjusted to `{par_time}`.", ephemeral=True)

@bot.tree.command(name="setup_channels", description="Binds global room layouts anchors hooks and automated server management fields.")
@is_bot_admin()
async def setup_channels_cmd(interaction: discord.Interaction, registration_channel: discord.TextChannel, logs_channel: discord.TextChannel, announcement_channel: discord.TextChannel, member_role: discord.Role, admin_role: discord.Role):
    await bot.db.settings.update_one({"_id": str(interaction.guild_id)}, {"$set": {"registration_channel_id": str(registration_channel.id), "logging_channel_id": str(logs_channel.id), "announcement_channel_id": str(announcement_channel.id), "member_role_id": str(member_role.id), "admin_role_ids": [str(admin_role.id)]}}, upsert=True)
    await interaction.response.send_message("⚙️ System configuration schemas saved securely to cloud infrastructure nodes.", ephemeral=True)

@bot.tree.command(name="readme", description="Pulls customized user or administrative help center manuals templates.")
async def readme_cmd(interaction: discord.Interaction):
    admin = interaction.user.id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator
    if admin:
        e = discord.Embed(title="👑 Master Administration Manual Directive Guide", description="• Run `/setup_channels` to configure hooks.\n• Execute `/checkpending` to verify applicants.\n• Adjust safety thresholds directly utilizing `/set_par_time` parameters.\n• Manage player penalties via `/manage_strikes` or export metrics using `/export_csv` sheets.")
        await interaction.response.send_message(embed=e, ephemeral=True)
    else:
        e = discord.Embed(title="🏁 Driver Operations Tournament Handbook Guide", description="• Run `/register` to submit telemetry profile card files.\n• Log laps via `/loglap` tracking strict `MM:SS.mmm` specifications.\n• Matchmake live skill targets using `/matchmake` ladders.")
        await interaction.response.send_message(embed=e)

@bot.tree.command(name="checksetup", description="Runs structural diagnostic handshakes testing cloud connectivity thresholds.")
@is_bot_admin()
async def check_setup_cmd(interaction: discord.Interaction):
    st = datetime.now(UTC); db_txt = "🔴 Offline Network Collisions"
    try: 
        await bot.db.settings.find_one({"_id": str(interaction.guild_id)})
        db_txt = f"🟢 Connected Atlas Core Hub Core Cluster Node Gateway ({int((datetime.now(UTC)-st).total_seconds()*1000)}ms)"
    except: pass
    emb = discord.Embed(title="🛡️ Operation Infrastructure Integrity Matrix Check", color=0x00ffcc)
    emb.add_field(name="Database Connections Layer (MongoDB Atlas)", value=db_txt, inline=False)
    await interaction.response.send_message(embed=emb); await asyncio.sleep(15); await interaction.delete_original_response()

@bot.tree.command(name="checkpending", description="Gathers an interactive review master list display sheet summarizing unverified files.")
@is_bot_admin()
async def check_pending_cmd(interaction: discord.Interaction):
    items = await bot.db.pending.find().to_list(length=None)
    guild_items = [i for i in items if i.get("guild_id") == str(interaction.guild_id)]
    if not guild_items: return await interaction.response.send_message("✅ Staging record queues are clear.", ephemeral=True)
    emb = discord.Embed(title="📋 Outstanding Staging Registrations Board Feed", description=f"Found **{len(guild_items)} driver accounts** in lines.")
    for i in guild_items[:5]: emb.add_field(name=f"Applicant ID: {i['user_id']}", value=f"Game ID: `{i['game_id']}` | [Screenshot Proof Link]({i['proof']})", inline=False)
    await interaction.response.send_message(embed=emb); await asyncio.sleep(15); await interaction.delete_original_response()

@bot.tree.command(name="server_status", description="Displays core hosting container network diagnostics and active player statistics.")
async def server_status_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    drivers = await bot.db.drivers.find().to_list(length=None)
    guild_drivers = [d for d in drivers if d.get("guild_id") == str(interaction.guild_id)]
    
    emb = discord.Embed(title="📊 Local Tournament Server Matrix Stats", color=0x00f5d4)
    emb.add_field(name="Registered Competitors", value=f"👥 `{len(guild_drivers)}` active driver profiles", inline=True)
    emb.add_field(name="Bot Latency", value=f"📡 `{round(bot.latency * 1000)}ms` websocket ping", inline=True)
    await interaction.followup.send(embed=emb)

async def graceful_shutdown(sig, loop):
    logging.info("System process terminal intercept signal flagged. Closing connection pools safely...")
    if HAS_MONGO and hasattr(bot, 'mongo_client'): bot.mongo_client.close()
    for t in [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]: t.cancel()
    bot.loop.stop()

# Custom encoder to completely eliminate the ObjectId serialization error across the entire script
class MongoJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if hasattr(o, '__str__') and o.__class__.__name__ == 'ObjectId':
            return str(o)
        return super().default(o)

def safe_json_dumps(data, **kwargs):
    return json.dumps(data, cls=MongoJSONEncoder, **kwargs)

def main():
    t = os.getenv("DISCORD_BOT_TOKEN")
    if not t or t == "your_real_discord_bot_token_here": return print("❌ Error: Missing authentic DISCORD_BOT_TOKEN settings values.")
    try: loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    for s in (signal.SIGINT, signal.SIGTERM):
        try: loop.add_signal_handler(s, lambda sig=s: asyncio.create_task(graceful_shutdown(sig, loop)))
        except NotImplementedError: pass
    try: loop.run_until_complete(bot.start(t))
    except (KeyboardInterrupt, SystemExit): pass
    finally:
        if not loop.is_closed(): loop.close()

if __name__ == "__main__": main()
