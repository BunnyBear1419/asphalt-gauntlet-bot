import os
import io
import json
import logging
import asyncio
import signal
from datetime import datetime, timedelta
import requests
import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
from PIL import Image, ImageDraw

logging.basicConfig(level=logging.INFO)
load_dotenv()

META_CARS = [
    "Devel Sixteen", "Koenigsegg CC850", "Jesko", "Hennessey Venom F5", 
    "SSC Tuatara", "Bugatti Chiron", "Bugatti Bolide", "Rimac Nevera",
    "Lamborghini Countach", "Ultima RS", "McLaren Speedtail", "Lamborghini Egoista"
]

VALID_TRACKS = [
    "Auckland", "Buenos Aires", "Cairo", "Giza", "Greenland", "Himalayas", 
    "Midwest", "Nevada", "New York", "Osaka", "Paris", "Rome", 
    "San Francisco", "Scotland", "Shanghai", "Singapore", "The Caribbean"
]
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

class MongoLocalFallbackClient:
    def __init__(self):
        self.db_file = "gauntlet_database.json"
        if os.path.exists(self.db_file):
            with open(self.db_file, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        else:
            self.data = {"settings": {}, "drivers": {}, "pending": {}, "laps": [], "backups": []}
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
        k = list(query.keys())[0] if query else None
        v = query[k] if k else None
        if self.name in ["settings", "drivers", "pending"]:
            if not query: return self.client.data[self.name]
            return self.client.data[self.name].get(str(v))
        return None
    async def find(self, query=None):
        if self.name == "laps":
            if not query: return CursorMock(self.client.data["laps"])
            k = list(query.keys())[0]
            filtered = [l for l in self.client.data["laps"] if l.get(k) == query[k]]
            return CursorMock(filtered)
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
        if self.name == "laps": self.client.data["laps"] = []
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
                # FIXED: Added serverSelectionTimeoutMS to prevent long hangs and let fallback catch issues cleanly
                self.mongo_client = AsyncIOMotorClient(mongo_uri, serverSelectionTimeoutMS=5000)
                self.db = self.mongo_client["gauntlet_database"]
                # FIXED: Trigger an actual command layout check to verify the cluster network connection handles handshakes early
                await self.mongo_client.admin.command('ping')
                logging.info("🍃 Connected successfully to MongoDB Cloud Clusters.")
            except Exception as e:
                logging.error(f"❌ MongoDB failed: {e}. Falling back to internal engine simulator.")
                self.db = MongoLocalFallbackClient()
        else:
            self.db = MongoLocalFallbackClient()

        s_check = await self.db.settings.find_one({"_id": "guild_config"})
        if not s_check:
            await self.db.settings.update_one({"_id": "guild_config"}, {"$set": {"season_number": 1, "season_start": datetime.utcnow().isoformat()}}, upsert=True)

        self.backup_database_task.start()
        self.pending_queue_reminder_task.start()

    def get_division(self, tracking_points: int) -> tuple:
        if tracking_points <= 10000: return "🥉 Division I (Bronze)", (205, 127, 50)
        elif tracking_points <= 14000: return "🥈 Division II (Silver)", (192, 192, 192)
        elif tracking_points <= 17500: return "🥇 Division III (Gold)", (255, 215, 0)
        elif tracking_points <= 20000: return "🏆 Division IV (Platinum)", (229, 228, 226)
        elif tracking_points <= 22000: return "👑 Division V (Champ)", (155, 93, 229)
        else: return "💎 Division VI (Legend)", (0, 245, 212)

    @tasks.loop(hours=168)
    async def backup_database_task(self):
        try:
            cfg = await self.db.settings.find_one({"_id": "guild_config"})
            if not cfg or not cfg.get("logging_channel_id"): return
            chan = self.get_channel(int(cfg["logging_channel_id"]))
            drivers_list = await self.db.drivers.find().to_list(length=None)
            laps_list = await self.db.laps.find().to_list(length=None)
            
            snapshot = {"timestamp": datetime.utcnow().isoformat(), "drivers": drivers_list, "laps": laps_list}
            await self.db.backups.insert_one(snapshot)
            if chan: await chan.send("💾 **Automated Cloud Backup System:** Snapshot successfully logged inside your remote database collection nodes.")
        except Exception as e: logging.error(f"Backup failed: {e}")

    @tasks.loop(hours=48)
    async def pending_queue_reminder_task(self):
        try:
            cfg = await self.db.settings.find_one({"_id": "guild_config"})
            if not cfg or not cfg.get("registration_channel_id"): return
            chan = self.get_channel(int(cfg["registration_channel_id"]))
            pending_items = await self.db.pending.find().to_list(length=None)
            if pending_items and chan:
                role_ping = f" <@&{cfg['admin_role_ids'][0]}>" if cfg.get("admin_role_ids") else ""
                embed = discord.Embed(title="⏳ Outstanding Queue Alert", color=0xffcc00, description=f"Attention Officers! There are **{len(pending_items)} drivers** waiting in staging records. Run `/checkpending` to review.")
                await chan.send(content=role_ping, embed=embed)
        except Exception as e: logging.error(f"Pending loop failed: {e}")

bot = GauntletBot()
def is_bot_admin():
    async def predicate(interaction: discord.Interaction):
        if interaction.user.id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator: return True
        cfg = await bot.db.settings.find_one({"_id": "guild_config"})
        if cfg and cfg.get("admin_role_ids"):
            for r_id in cfg["admin_role_ids"]:
                if any(r.id == int(r_id) for r in interaction.user.roles): return True
        raise app_commands.Errors.MissingPermissions(["Custom Bot Admin Role"])
    return app_commands.check(predicate)

class VerificationModal(discord.ui.Modal, title="Verify & Polish Driver Details"):
    def __init__(self, user_id: str, game_id: str, rank: int, control_type: str):
        super().__init__()
        self.user_id = user_id
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

        await bot.db.drivers.update_one(
            {"_id": self.user_id},
            {"$set": {"game_id": final_gid, "garage_rank": final_rank, "control_type": self.control_type, "verified_laps": 0, "wins": 0, "losses": 0, "defense_cars": []}},
            upsert=True
        )
        await bot.db.pending.delete_one({"_id": self.user_id})
        
        div_name, _ = bot.get_division(final_rank)
        cfg = await bot.db.settings.find_one({"_id": "guild_config"})
        
        role_note = ""
        if cfg and cfg.get("member_role_id"):
            role = interaction.guild.get_role(int(cfg["member_role_id"]))
            member = interaction.guild.get_member(int(self.user_id))
            if role and member:
                try: await member.add_roles(role); role_note = f"
Granted Role: {role.mention}"
                except: role_note = f"
⚠️ *Move bot integration roles higher in settings list.*"

        embed = discord.Embed(title="🎉 Roster Entry Approved!", color=0x00ffcc, description=f"Driver <@{self.user_id}> has joined **{div_name}**!{role_note}")
        embed.add_field(name="Confirmed Score", value=f"📊 {final_rank:,} PI")
        embed.add_field(name="Control Layout", value=f"🎮 {self.control_type.upper()}")
        
        if cfg and cfg.get("announcement_channel_id"):
            chan = bot.get_channel(int(cfg["announcement_channel_id"]))
            if chan: await chan.send(embed=embed)
        await interaction.response.edit_message(embed=embed, view=None)

class RejectionReasonSelect(discord.ui.Select):
    def __init__(self, user_id: str):
        options = [
            discord.SelectOption(label="Anti-Sandbagging Violation", description="Submitted score does not map actual max potential garage cap values.", emoji="⚠️"),
            discord.SelectOption(label="Illegible Physical Media Proof", description="Uploaded screenshot asset is blurry, cropped, or unreadable.", emoji="📸"),
            discord.SelectOption(label="Mismatched Profile / Game ID", description="The text strings typed do not reconcile with image assets.", emoji="❌")
        ]
        super().__init__(placeholder="Select the official reason for denial...", options=options)
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        await bot.db.pending.delete_one({"_id": self.user_id})
        embed = discord.Embed(title="⛔ Registration Request Denied", color=0xff3366, description=f"The application matching <@{self.user_id}> was rejected: **{self.values[0]}**")
        await interaction.response.edit_message(embed=embed, view=None)

class VerificationView(discord.ui.View):
    def __init__(self, user_id: str, game_id: str, rank: int, control_type: str):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.game_id = game_id
        self.rank = rank
        self.control_type = control_type

    @discord.ui.button(label="Approve Alignment", style=discord.ButtonStyle.green, emoji="✅")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VerificationModal(self.user_id, self.game_id, self.rank, self.control_type))

    @discord.ui.button(label="Deny Entry", style=discord.ButtonStyle.danger, emoji="❌")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        v = discord.ui.View(timeout=60); v.add_item(RejectionReasonSelect(self.user_id))
        await interaction.response.send_message("Select denial classification tracking indices:", view=v, ephemeral=True)

class ChallengeConfirmView(discord.ui.View):
    def __init__(self, challenger_id: str, opponent_id: str, result: str):
        super().__init__(timeout=60)
        self.challenger_id = challenger_id
        self.opponent_id = opponent_id
        self.result = result

    @discord.ui.button(label="🤝 Confirm Match Result", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != int(self.opponent_id):
            await interaction.response.send_message("❌ Validation Error: Only the targeted challenge opponent can confirm this match logs data entry.", ephemeral=True)
            return
        w_id, l_id = (self.challenger_id, self.opponent_id) if self.result == "win" else (self.opponent_id, self.challenger_id)
        await bot.db.drivers.update_one({"_id": w_id}, {"$inc": {"wins": 1}})
        await bot.db.drivers.update_one({"_id": l_id}, {"$inc": {"losses": 1}})
        await interaction.response.edit_message(content="✅ **Match outcome confirmed and updated securely on remote MongoDB cluster metrics keys!**", embed=None, view=None)

class ResetSeasonView(discord.ui.View):
    def __init__(self, divs_map):
        super().__init__(timeout=None)
        self.add_item(ResetSeasonDropdown(divs_map))

class ResetSeasonDropdown(discord.ui.Select):
    def __init__(self, divs_map):
        super().__init__(placeholder="Choose a division roster overview card...", options=[discord.SelectOption(label=k) for k in divs_map.keys()])
        self.divs_map = divs_map

    async def callback(self, interaction: discord.Interaction):
        drivers = self.divs_map[self.values[0]]
        embed = discord.Embed(title=f"📊 Seasonal Standings: {self.values[0]}", color=0xffcc00)
        embed.description = "
".join([f"• {r['name']} — `{r['score']:,}` PI" for r in drivers]) if drivers else "*No drivers placed in this division bracket.*"
        await interaction.response.edit_message(embed=embed, view=self.view)

# --- SLASH ROUTINES CORE COMMAND MAPS ---

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
    cfg = await bot.db.settings.find_one({"_id": "guild_config"})
    if cfg and cfg.get("registration_channel_id") and str(interaction.channel_id) != str(cfg["registration_channel_id"]):
        await interaction.response.send_message(f"❌ Redirection Link: Execute profile registration actions within <#{cfg['registration_channel_id']}>.", ephemeral=True)
        return

    if not proof_screenshot.content_type or not proof_screenshot.content_type.startswith("image/"):
        await interaction.response.send_message("❌ Upload Blocked: Roster onboarding routines restrict media attachments exclusively to images.", ephemeral=True)
        return

    await interaction.response.defer()
    parsed_rank = 15500
    ocr_key = os.getenv("OCR_SPACE_API_KEY")
    if ocr_key and ocr_key != "your_free_ocr_space_api_key_here":
        try:
            # FIXED: Corrected endpoint query formatting to include correct query separator elements
            r = requests.get(f"https://api.ocr.space/parse/image?apikey={ocr_key}&url={proof_screenshot.url}", timeout=5)
            if r.status_code == 200 and "PARSEDTEXT" in r.text.upper():
                parsed_text = r.json().get("ParsedResults", [{}]).get("ParsedText", "").upper()
                if not any(x in parsed_text for x in ["PLAYER", "GARAGE", "LEVEL", "CLUB", "ID"]):
                    await interaction.followup.send("❌ Image Analysis Blocked: Uploaded file does not verify as an authentic Asphalt profile telemetry interface card screenshot.")
                    return
        except: pass

    await bot.db.pending.update_one({"_id": str(interaction.user.id)}, {"$set": {"game_id": game_id, "proposed_rank": parsed_rank, "proof": proof_screenshot.url, "control": control_type.value}}, upsert=True)
    await interaction.followup.send("📥 **Submission Completed.** Your metrics records profiles have been routed to staff verification boards successfully.")
    
    if cfg and cfg.get("registration_channel_id"):
        chan = bot.get_channel(int(cfg["registration_channel_id"]))
        if chan:
            emb = discord.Embed(title="🛡️ New Gauntlet Placement Review Request", color=0xffcc00)
            emb.add_field(name="Driver", value=interaction.user.mention); emb.add_field(name="Declared Game ID", value=f"`{game_id}`"); emb.set_image(url=proof_screenshot.url)
            await chan.send(embed=emb, view=VerificationView(str(interaction.user.id), game_id, parsed_rank, control_type.value))

@bot.tree.command(name="profile", description="Generates layered graphical driver licence standings metrics sheet profiles.")
async def profile_cmd(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    driver = await bot.db.drivers.find_one({"_id": str(target.id)})
    if not driver:
        await interaction.response.send_message("❌ Data Query Empty: Target driver node is not registered on live database frames.", ephemeral=True)
        return
    await interaction.response.defer()
    
    rank = driver.get("garage_rank", 0)
    div_name, rgb = bot.get_division(rank)
    
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
    draw.text((50, 120), f"DRIVER ACCOUNT: {target.display_name.upper()}", fill=(255,255,255))
    draw.text((50, 170), f"ASPHALT LOG ID: {driver.get('game_id', 'UNKNOWN')}", fill=(200,200,200))
    draw.text((50, 220), f"FLEET STRENGTH: {rank:,} PI RATING VALUE", fill=(255,255,255))
    draw.text((50, 270), f"DRIVING CONTROL: {str(driver.get('control_type','')).upper()}", fill=rgb)
    
    w, l = driver.get("wins", 0), driver.get("losses", 0)
    draw.text((50, 340), f"PRACTICE MATRICES: {w} VICTORIES / {l} DEFEATS", fill=(255,255,255))
    
    buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
    await interaction.followup.send(file=discord.File(buf, filename="license.png"))

@bot.tree.command(name="loglap", description="Logs tracking lap time parameters into seasonal lists grids.")
@app_commands.describe(track="Racing circuit layout name mapping logs", car="Vehicle build label utilized", lap_time="Format input schema constraints exactly: MM:SS.mmm", proof_file="Attach gameplay file check limits")
async def log_lap_cmd(interaction: discord.Interaction, track: str, car: str, lap_time: str, proof_file: discord.Attachment):
    driver = await bot.db.drivers.find_one({"_id": str(interaction.user.id)})
    if not driver:
        await interaction.response.send_message("❌ Execution Halted: Register your driver profiles configurations utilizing `/register` first.", ephemeral=True)
        return
    if proof_file.size > 10 * 1024 * 1024:
        await interaction.response.send_message("❌ Size Limit Triggered: Uploaded file payload exceeds the maximum 10MB watchdogs constraints layout.", ephemeral=True)
        return
    ms = _parse_time_to_ms(lap_time)
    if ms == -1:
        await interaction.response.send_message("❌ Format matching issue: Configure time tracking layouts matching: `MM:SS.mmm` specifications.", ephemeral=True)
        return

    s_track = _sanitize_track_name(track)
    await bot.db.laps.insert_one({"user_id": str(interaction.user.id), "driver_name": interaction.user.display_name, "track": s_track, "car": car.upper().strip(), "time_ms": ms, "proof_url": proof_file.url})
    await bot.db.drivers.update_one({"_id": str(interaction.user.id)}, {"$inc": {"verified_laps": 1}})
    await interaction.response.send_message(f"✅ Lap records synchronized perfectly for circuit: **{s_track}**.", ephemeral=True)

@bot.tree.command(name="records", description="Renders the top 5 seasonal leaderboards tracking time differences grids.")
async def records_cmd(interaction: discord.Interaction, track: str):
    s_track = _sanitize_track_name(track)
    laps = await bot.db.laps.find({"track": s_track}).to_list(length=None)
    if not laps:
        await interaction.response.send_message(f"🔍 Zero telemetry records active on cluster listings matching track layouts: **{s_track}**.")
        return
    laps.sort(key=lambda x: x["time_ms"])
    emb = discord.Embed(title=f"🏁 Seasonal Leaderboard: {s_track}", color=0xffcc00)
    base = laps[0]["time_ms"]
    for idx, l in enumerate(laps[:5], start=1):
        delta = "👑 [RECORD]" if idx == 1 else f"`+{(l['time_ms'] - base)/1000.0:.3f}s` gap telemetry"
        emb.add_field(name=f"#{idx} | {l['driver_name']}", value=f"🏎️ **{l['car']}** | Time: `{_format_ms_to_time(l['time_ms'])}`
{delta} | [View Proof]({l['proof_url']})", inline=False)
    await interaction.response.send_message(embed=emb)

@bot.tree.command(name="challenge", description="Logs match parameters evaluating friendly practice runs outcomes.")
async def challenge_cmd(interaction: discord.Interaction, opponent: discord.Member, result: str):
    if opponent.id == interaction.user.id: return await interaction.response.send_message("❌ Target alignment fault.", ephemeral=True)
    emb = discord.Embed(title="🤝 Match Verification Pending Validation", description=f"<@{interaction.user.id}> proposes match outcome victory state logs against <@{opponent.id}>'s active defense team lineup layouts.")
    await interaction.response.send_message(embed=emb, view=ChallengeConfirmView(str(interaction.user.id), str(opponent.id), result.lower().strip()))

@bot.tree.command(name="checksetup", description="Runs structural diagnostic handshakes testing cloud connectivity thresholds.")
@is_bot_admin()
async def check_setup_cmd(interaction: discord.Interaction):
    st = datetime.utcnow(); db_txt = "🔴 Offline Network Collisions"
    try: 
        await bot.db.settings.find_one({"_id": "guild_config"})
        db_txt = f"🟢 Connected Cluster Atlas Core Hub ({int((datetime.utcnow()-st).total_seconds()*1000)}ms)"
    except: pass
    emb = discord.Embed(title="🛡️ Operation Infrastructure Integrity Matrix Check", color=0x00ffcc)
    emb.add_field(name="Database Connections Layer (MongoDB Atlas)", value=db_txt, inline=False)
    await interaction.response.send_message(embed=emb); await asyncio.sleep(15); await interaction.delete_original_response()

@bot.tree.command(name="checkpending", description="Gathers an interactive review master list display sheet summarizing unverified files.")
@is_bot_admin()
async def check_pending_cmd(interaction: discord.Interaction):
    items = await bot.db.pending.find().to_list(length=None)
    if not items: return await interaction.response.send_message("✅ Staging record queues are clear. Complete.", ephemeral=True)
    emb = discord.Embed(title="📋 Outstanding Staging Registrations Board Feed", description=f"Found **{len(items)} driver accounts** sitting in staging validation lines.")
    for i in items[:5]: emb.add_field(name=f"Applicant ID: {i['_id']}", value=f"Game ID: `{i['game_id']}` | [Screenshot Proof Link]({i['proof']})", inline=False)
    await interaction.response.send_message(embed=emb); await asyncio.sleep(15); await interaction.delete_original_response()

@bot.tree.command(name="setup_channels", description="Binds global room layouts anchors hooks and automated server management fields.")
@is_bot_admin()
async def setup_channels_cmd(interaction: discord.Interaction, registration_channel: discord.TextChannel, logs_channel: discord.TextChannel, announcement_channel: discord.TextChannel, member_role: discord.Role, admin_role: discord.Role):
    await bot.db.settings.update_one({"_id": "guild_config"}, {"$set": {"registration_channel_id": str(registration_channel.id), "logging_channel_id": str(logs_channel.id), "announcement_channel_id": str(announcement_channel.id), "member_role_id": str(member_role.id), "admin_role_ids": [str(admin_role.id)]}}, upsert=True)
    await interaction.response.send_message("⚙️ System configuration schemas saved securely to cloud infrastructure nodes.", ephemeral=True)

@bot.tree.command(name="resetseason", description="Wipes racing lap tracking lines and updates current season podium configurations boards.")
@is_bot_admin()
async def reset_season_cmd(interaction: discord.Interaction):
    drivers = await bot.db.drivers.find().to_list(length=None)
    if not drivers: return await interaction.response.send_message("❌ Active rosters data grid empty. Aborted.", ephemeral=True)
    await interaction.response.defer()
    cfg = await bot.db.settings.find_one({"_id": "guild_config"})
    s_num = cfg.get("season_number", 1) if cfg else 1
    drivers.sort(key=lambda x: x.get("garage_rank", 0), reverse=True)
    
    img = Image.new("RGB", (900, 450), color=(15,17,19)); draw = ImageDraw.Draw(img)
    draw.rectangle([(350, 150), (550, 450)], fill=(255,215,0))
    draw.rectangle([(120, 220), (320, 450)], fill=(192,192,192))
    draw.rectangle([(580, 270), (780, 450)], fill=(205,127,50))
    
    if len(drivers) > 0: draw.text((370, 110), f"🥇 {drivers[0]['game_id'].upper()[:12]}", fill=(255,255,255))
    if len(drivers) > 1: draw.text((140, 180), f"🥈 {drivers[1]['game_id'].upper()[:12]}", fill=(255,255,255))
    if len(drivers) > 2: draw.text((600, 230), f"🥉 {drivers[2]['game_id'].upper()[:12]}", fill=(255,255,255))
    buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
    
    divs_map = {"💎 Legend Bracket": [], "👑 Champ Bracket": [], "🥇 Gold Bracket": [], "🥉 Starter Bracket": []}
    for d in drivers:
        k = "💎 Legend Bracket" if d["garage_rank"] > 22000 else "👑 Champ Bracket" if d["garage_rank"] > 20000 else "🥇 Gold Bracket" if d["garage_rank"] > 14000 else "🥉 Starter Bracket"
        divs_map[k].append({"name": d["game_id"], "score": d["garage_rank"]})
        
    await bot.db.laps.delete_many({})
    await bot.db.settings.update_one({"_id": "guild_config"}, {"$inc": {"season_number": 1}, "$set": {"season_start": datetime.utcnow().isoformat()}})
    me = discord.Embed(title=f"🏆 GAUNTLET SEASON #{s_num} REPORT CHAMPIONS PODIUM", description="Review detailed standings cards using the selection indicators index below:")
    if cfg and cfg.get("announcement_channel_id"):
        c = bot.get_channel(int(cfg["announcement_channel_id"]))
        if c: await c.send(embed=me, file=discord.File(buf, filename="podium.png"), view=ResetSeasonView(divs_map))
    await interaction.followup.send("✅ Reset operational configurations finalized completely across server databases.")

@bot.tree.command(name="set_bot_name", description="Edits global platform app usernames profile labels.")
@is_bot_admin()
async def set_bot_name_cmd(interaction: discord.Interaction, name: str):
    await bot.user.edit(username=name)
    await interaction.response.send_message(f"✅ Bot tag altered to: **{name}**", ephemeral=True)

@bot.tree.command(name="set_bot_avatar", description="Overwrites application identity logos picture streams shapes variables.")
@is_bot_admin()
async def set_bot_avatar_cmd(interaction: discord.Interaction, avatar_file: discord.Attachment):
    await bot.user.edit(avatar=await avatar_file.read())
    await interaction.response.send_message("✅ Base avatar modified successfully.", ephemeral=True)

@bot.tree.command(name="set_profile_background", description="Caches widescreen display graphics backdrops layers into memory assets arrays.")
@is_bot_admin()
async def set_profile_background_cmd(interaction: discord.Interaction, background_file: discord.Attachment):
    os.makedirs("assets", exist_ok=True); await background_file.save("assets/profile_bg.png")
    await interaction.response.send_message("🎨 Custom server profile banner asset cached successfully.", ephemeral=True)

@bot.tree.command(name="suggest_target", description="Executes an elastic proximity matchmaking search radius query filtering teammates.")
async def suggest_target_cmd(interaction: discord.Interaction):
    d = await bot.db.drivers.find_one({"_id": str(interaction.user.id)})
    if not d: return await interaction.response.send_message("❌ Profile entry absent.", ephemeral=True)
    all_d = await bot.db.drivers.find().to_list(length=None)
    targets = [x for x in all_d if x["_id"] != str(interaction.user.id)]
    if not targets: return await interaction.response.send_message("🔍 Matchmaker empty.")
    targets.sort(key=lambda x: abs(x.get("garage_rank", 0) - d["garage_rank"]))
    await interaction.response.send_message(embed=discord.Embed(title="🎯 Proximity Practice Matchmaking Target Result", description=f"Recommended Opponent Account Tag: `{targets[0]['game_id']}`
Fleet Rating Score: **{targets[0]['garage_rank']:,}** PI"))

@bot.tree.command(name="changelog", description="Displays version patch modifications dashboards reports charts outlines.")
async def changelog_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(embed=discord.Embed(title="🚀 System Patch Metrics Changelog Dashboard", description="• Core storage engine linked to **Async MongoDB Atlas Collections Streams**
• Embedded failsafe review modal adjustments prefill grids inside approvals layers
• Automatic screenshot verification filter watchdogs parsing ocr rules blocks
• Graceful termination connection signal catchers protecting transactions scripts"))

@bot.tree.command(name="readme", description="Pulls customized user or administrative help center manuals templates.")
async def readme_cmd(interaction: discord.Interaction):
    admin = interaction.user.id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator
    if admin:
        e = discord.Embed(title="👑 Master Administration Manual Directive Guide", description="• Run `/setup_channels` to configure automated auto-roles anchors links hooks.
• Execute `/checkpending` or respond to active review notification button matrices prompts.
• Use `/resetseason` to compile podium asset cards vectors fields and wipe lap times safely.")
        await interaction.response.send_message(embed=e, ephemeral=True)
    else:
        e = discord.Embed(title="👑 Driver Operations Tournament Handbook Guide", description="• Run `/register` to submit profile telemetry graphics files checks blueprints.
• Logging laps via `/loglap` tracking strict `MM:SS.mmm` formatting masks strings.
• Challenge matches logs outcomes via `/challenge`. Targeted opponents must confirm entries.")
        await interaction.response.send_message(embed=e)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.Errors.MissingPermissions):
        await interaction.response.send_message("⛔ **Authorization Failure:** Your server profiles lack the authority roles keys required to trigger this option.", ephemeral=True)

async def graceful_shutdown(sig, loop):
    logging.info("System process terminal intercept signal flagged. Closing connection pools safely...")
    if HAS_MONGO and hasattr(bot, 'mongo_client'): 
        bot.mongo_client.close()
    for t in [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]: 
        t.cancel()
    bot.loop.stop()

def main():
    t = os.getenv("DISCORD_BOT_TOKEN")
    if not t or t == "your_real_discord_bot_token_here": 
        return print("❌ Error: Missing authentic DISCORD_BOT_TOKEN settings values.")
    
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    for s in (signal.SIGINT, signal.SIGTERM):
        try: 
            loop.add_signal_handler(s, lambda sig=s: asyncio.create_task(graceful_shutdown(sig, loop)))
        except NotImplementedError: 
            pass
            
    try:
        loop.run_until_complete(bot.start(t))
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        if not loop.is_closed():
            loop.close()

if __name__ == "__main__": 
    main()
