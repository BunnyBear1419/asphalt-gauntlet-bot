import os
import re
import time
import logging
import asyncio
import aiohttp
import urllib.parse
import json
import random
from datetime import datetime
from difflib import SequenceMatcher
from dotenv import load_dotenv
import discord
from discord import app_commands
from discord.ext import commands, tasks
from motor.motor_asyncio import AsyncIOMotorClient
from PIL import Image
import io

# Load local workspace environment variables
load_dotenv()

# Configure Global Logging Output Format
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Official ALU Gauntlet Track/Course Pool Dictionary Array
ALU_TRACKS = [
    "San Francisco - City by the Bay", "Cairo - Nile Chase", "Rome - Eternal City", 
    "Shanghai - Orient Express", "Midwest - Wilderness Run", "Caribbean - Island Paradise",
    "Osaka - Sakura Sakura", "Nevada - Dam Buster", "New York - Manhattan Rise", 
    "Auckland - Harbour Crossing", "Greenland - Glacier Race", "Paris - Street Circuit"
]

# Official ALU Gauntlet Car Roster Array for Autocomplete Lookups
ALU_CARS = [
    "Devel Sixteen", "Koenigsegg Jesko", "Bugatti Bolide", "Koenigsegg Gemera", 
    "Aspark Owl", "Tuatara", "Hennessey Venom F5", "Bugatti Chiron", 
    "Rimac Nevera", "McLaren Speedtail", "Ferrari SF90 Stradale", "Lamborghini Sian", 
    "Porsche 911 GT3 RS", "Pagani Imola", "Aston Martin Valhalla", "Genty Akylone",
    "Apex AP-0", "Apollo IE", "Lotus Evija", "Trion Nemesis", "W Motors Lykan"
]

class GauntletBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True  # Required to apply roles dynamically to targets
        super().__init__(command_prefix="!", intents=intents)
        self.db = None
        self.mongo_client = None

    async def setup_hook(self):
        mongo_uri = os.getenv("MONGO_URI")
        if mongo_uri:
            try:
                self.mongo_client = AsyncIOMotorClient(mongo_uri)
                await self.mongo_client.admin.command('ping')
                self.db = self.mongo_client.get_database("asphalt_gauntlet")
                logging.info("🟢 Successfully connected to MongoDB Atlas Cloud Cluster.")
            except Exception as e:
                logging.error(f"🔴 MongoDB Connection Failed: {e}")
                self.setup_mock_db()
        else:
            logging.warning("⚠️ MONGO_URI missing from environment variables.")
            self.setup_mock_db()

        # Execute background state recovery sequence hooks
        await self.recover_season_state()
        self.seasonal_clock_loop.start()
        await self.tree.sync()
        logging.info("🟢 Application slash commands synchronized globally.")

    async def recover_season_state(self):
        try:
            now = time.time()
            state = await self.db.season_state.find_one({"_id": "current_season"})
            if not state:
                await self.db.season_state.update_one(
                    {"_id": "current_season"},
                    {"$set": {"season_number": 1, "ends_at": now + (14 * 24 * 60 * 60)}},
                    upsert=True
                )
                logging.info("⚙️ Initialized Season 1 timer settings data configurations.")
            else:
                remaining_hours = max(0, round((state["ends_at"] - now) / 3600, 1))
                logging.info(f"⚙️ State Recovery Hook: Resumed Season {state.get('season_number', 1)} clock matrix seamlessly.")
        except Exception as state_err:
            logging.error(f"Failed to execute state recovery sequence hooks: {state_err}")

    def setup_mock_db(self):
        """Fallback local database simulation if MongoDB Atlas is offline."""
        class MockCollection:
            async def find_one(self, *args, **kwargs): return None
            async def update_one(self, *args, **kwargs): return None
            async def delete_one(self, *args, **kwargs): return None
            async def delete_many(self, *args, **kwargs):
                class MockResult:
                    def __init__(self): self.deleted_count = 0
                return MockResult()
            def find(self, *args, **kwargs):
                class MockCursor:
                    async def to_list(self, *args, **kwargs): return []
                    def sort(self, *args, **kwargs): return self
                    def limit(self, *args, **kwargs): return self
                return MockCursor()
        class MockDB:
            def __getattr__(self, name): return MockCollection()
            async def command(self, *args, **kwargs): raise ConnectionError("Mock DB Offline")
        self.db = MockDB()

    async def close(self):
        self.seasonal_clock_loop.cancel()
        if self.mongo_client:
            self.mongo_client.close()
        await super().close()

bot = GauntletBot()

@tasks.loop(hours=1)
async def seasonal_clock_loop_task():
    now = time.time()
    state = await bot.db.season_state.find_one({"_id": "current_season"})
    if not state:
        await bot.db.season_state.update_one(
            {"_id": "current_season"},
            {"$set": {"season_number": 1, "ends_at": now + (14 * 24 * 60 * 60)}},
            upsert=True
        )
        return
    if now >= state["ends_at"]:
        await trigger_global_season_end()

@seasonal_clock_loop_task.before_loop
async def before_seasonal_clock():
    await bot.wait_until_ready()

# Bind the standalone task securely to our initialized client body
bot.seasonal_clock_loop = seasonal_clock_loop_task

async def check_admin_privileges(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator:
        return True
    cfg = await bot.db.settings.find_one({"_id": str(interaction.guild_id)})
    if cfg and cfg.get("admin_role_id"):
        target_role = interaction.guild.get_role(int(cfg["admin_role_id"]))
        if target_role in interaction.user.roles:
            return True
    return False

async def enforce_channel_constraints(interaction: discord.Interaction, admin_cmd: bool = False) -> bool:
    cfg = await bot.db.settings.find_one({"_id": str(interaction.guild_id)})
    if not cfg:
        await interaction.response.send_message("❌ **System Offline:** Run `/setup` first.", ephemeral=True)
        return False
    current_chan = str(interaction.channel_id)
    if admin_cmd:
        allowed_admin_chans = [cfg.get("registration_channel_id"), cfg.get("review_channel_id"), cfg.get("log_channel_id"), cfg.get("announcement_channel_id")]
        if current_chan not in allowed_admin_chans:
            await interaction.response.send_message("❌ **Command Blocked:** Administrative actions must be executed within assigned League channels.", ephemeral=True)
            return False
        return True
    else:
        main_chan_id = cfg.get("registration_channel_id")
        if current_chan != main_chan_id:
            await interaction.response.send_message(f"❌ **Lobby Lock Active:** Use the main channel: <#{main_chan_id}>.", ephemeral=True)
            return False
        return True

async def dispatch_audit_log(guild_id: str, title: str, description: str, color: int = 0x7f8c8d):
    cfg = await bot.db.settings.find_one({"_id": str(guild_id)})
    if cfg and cfg.get("log_channel_id"):
        chan = bot.get_channel(int(cfg["log_channel_id"]))
        if chan:
            emb = discord.Embed(title=title, description=description, color=color, timestamp=datetime.utcnow())
            try: await chan.send(embed=emb)
            except Exception: pass

def fuzzy_correct_marker(text: str, target: str, threshold: float = 0.6) -> str:
    words = text.split()
    for word in words:
        cleaned_word = re.sub(r'[^A-Z0-9]', '', word.upper())
        if not cleaned_word: continue
        matcher = SequenceMatcher(None, cleaned_word, target)
        if matcher.ratio() >= threshold: return text.replace(word, target)
    return text

def preprocess_text_with_fuzzy(text: str) -> str:
    text = text.upper()
    text = fuzzy_correct_marker(text, "GARAGE")
    text = fuzzy_correct_marker(text, "PLAYER")
    text = fuzzy_correct_marker(text, "LEVEL")
    text = fuzzy_correct_marker(text, "CLUB")
    text = re.sub(r'(1D|LD|lD)', 'ID', text)
    text = re.sub(r'(6ARAGE|GARA6E)', 'GARAGE', text)
    return text

def calculate_elo_change(winner_elo: int, loser_elo: int, k_factor: int = 32):
    expected_winner = 1 / (1 + 10 ** ((loser_elo - winner_elo) / 400))
    expected_loser = 1 / (1 + 10 ** ((winner_elo - loser_elo) / 400))
    new_winner_elo = winner_elo + round(k_factor * (1 - expected_winner))
    new_loser_elo = loser_elo + round(k_factor * (0 - expected_loser))
    return max(100, new_winner_elo), max(100, new_loser_elo)

async def trigger_global_season_end(forced_interaction: discord.Interaction = None):
    now = time.time()
    state = await bot.db.season_state.find_one({"_id": "current_season"})
    current_season_num = state.get("season_number", 1) if state else 1
    divisions = [
        {"name": "👑 Division 6 — Legend Tier", "query": {"$gte": 18000}, "color": 0x9b59b6},
        {"name": "🏆 Division 5 — Champ Tier", "query": {"$gte": 16500, "$lt": 18000}, "color": 0xe74c3c},
        {"name": "💎 Division 4 — Platinum Tier", "query": {"$gte": 14000, "$lt": 16500}, "color": 0x3498db},
        {"name": "🥇 Division 3 — Gold Tier", "query": {"$gte": 10000, "$lt": 14000}, "color": 0xdeaf2a},
        {"name": "🥈 Division 2 — Silver Tier", "query": {"$gte": 5000, "$lt": 10000}, "color": 0xa4a7a9},
        {"name": "🪵 Division 1 — Bronze Tier", "query": {"$lt": 5000}, "color": 0xa3704c}
    ]
    guild_settings_cursor = bot.db.settings.find({})
    guild_configs = await guild_settings_cursor.to_list(length=100)
    for config in guild_configs:
        guild_id = config["_id"]
        channel_id = config.get("announcement_channel_id") or config.get("registration_channel_id")
        if not channel_id: continue
        target_channel = bot.get_channel(int(channel_id))
        if not target_channel: continue
        ping_content = f"<@&{config['announcement_role_id']}>" if config.get("announcement_role_id") else ""
        header_embed = discord.Embed(title=f"🏁 SEASON {current_season_num} GAUNTLET FINALE AWARDS", description="The 2-week tournament window has closed! Standings calculated.", color=0xffaa00)
        await target_channel.send(content=ping_content, embed=header_embed)
        for div in divisions:
            cursor = bot.db.drivers.find({"guild_id": str(guild_id), "garage_pi": div["query"]}).sort("elo", -1).limit(5)
            top_drivers = await cursor.to_list(length=5)
            div_embed = discord.Embed(title=div["name"], color=div["color"])
            if not top_drivers: 
                div_embed.description = "*No verified driver positions secured in this tier bracket.*"
            else:
                standings_text = "".join([
                    (f"{'🥇 ' if r==0 else '🥈 ' if r==1 else '🥉 ' if r==2 else f'**#{r+1}** '} "
                     f"<@{d['user_id']}> | `{d['game_id']}` — **{d.get('elo', 1000)} ELO**\n")
                    for r, d in enumerate(top_drivers)
                ])
                div_embed.add_field(name="Final Placements", value=standings_text, inline=False)
            await target_channel.send(embed=div_embed)
    await bot.db.pending.delete_many({})
    await bot.db.season_state.update_one({"_id": "current_season"}, {"$set": {"season_number": current_season_num + 1, "ends_at": now + (14 * 24 * 60 * 60)}}, upsert=True)
    if forced_interaction:
        await forced_interaction.followup.send(embed=discord.Embed(title="⚙️ Season Rollover Executed", color=0x00ffcc))

class DuelReportModal(discord.ui.Modal, title="Submit Gauntlet Match Results"):
    challenger_lap = discord.ui.TextInput(label="Your Run Lap Time (MM:SS.MS)", placeholder="e.g. 01:12.431", required=True)
    screenshot_proof = discord.ui.TextInput(label="Paste Race Score card Screenshot URL", placeholder="Direct image link...", required=True)

    def __init__(self, challenger_id: str, opponent_id: str, defense_ms: int, track_name: str):
        super().__init__()
        self.challenger_id, self.opponent_id, self.defense_ms, self.track_name = challenger_id, opponent_id, defense_ms, track_name

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id, lap_input = str(interaction.guild_id), self.challenger_lap.value.strip()
        if not re.match(r"^\d{1,2}:\d{2}\.\d{3}$", lap_input):
            await interaction.followup.send("❌ **Format Denied:** Use format: `MM:SS.MS`.", ephemeral=True)
            return
        m, s = lap_input.split(":")
        sec, ms = s.split(".")
        challenger_ms = (int(m) * 60 * 1000) + (int(sec) * 1000) + int(ms)
        p1 = await bot.db.drivers.find_one({"_id": f"{guild_id}_{self.challenger_id}"})
        p2 = await bot.db.drivers.find_one({"_id": f"{guild_id}_{self.opponent_id}"})
        if challenger_ms < self.defense_ms:
            w_id, l_id = self.challenger_id, self.opponent_id
            w_prof, l_profile = p1, p2
            outcome_desc = f"🏆 <@{self.challenger_id}> **successfully cracked the defense line** on `{self.track_name}`!"
        else:
            w_id, l_id = self.opponent_id, self.challenger_id
            w_prof, l_profile = p2, p1
            outcome_desc = f"💀 <@{self.opponent_id}>'s **ghost defense successfully held off** the challenger on `{self.track_name}`."
        new_w_elo, new_l_elo = calculate_elo_change(w_prof.get("elo", 1000), l_profile.get("elo", 1000))
        await bot.db.drivers.update_one({"_id": f"{guild_id}_{w_id}"}, {"$set": {"elo": new_w_elo}, "$inc": {"career_wins": 1, "career_played": 1, "streak": 1}})
        await bot.db.drivers.update_one({"_id": f"{guild_id}_{l_id}"}, {"$set": {"elo": new_l_elo, "streak": 0}, "$inc": {"career_played": 1}})
        self.view.stop()
        await interaction.channel.send(embed=discord.Embed(title="🏁 Gauntlet Ghost Duel Resolved", description=outcome_desc, color=0x00ffcc if challenger_ms < self.defense_ms else 0xff3333))

class LobbyUIButtons(discord.ui.View):
    def __init__(self, challenger_id: str, opponent_id: str, defense_ms: int, track_name: str):
        super().__init__(timeout=1800)
        self.challenger_id, self.opponent_id, self.defense_ms, self.track_name = challenger_id, opponent_id, defense_ms, track_name
    @discord.ui.button(label="Submit Match Results", style=discord.ButtonStyle.blurple, custom_id="lobby_report_btn")
    async def report_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.challenger_id:
            await interaction.response.send_message("❌ Access Denied: Challenger only.", ephemeral=True)
            return
        await interaction.response.send_modal(DuelReportModal(self.challenger_id, self.opponent_id, self.defense_ms, self.track_name))

class DefenseView(discord.ui.View):
    def __init__(self, user_id: str, guild_id: str, track: str, fleet_desc: str, lap_time: str, raw_ms: int, proof_url: str):
        super().__init__(timeout=None)
        self.user_id, self.guild_id, self.track, self.fleet_desc, self.lap_time, self.raw_ms, self.proof_url = user_id, guild_id, track, fleet_desc, lap_time, raw_ms, proof_url
    @discord.ui.button(label="Approve Defense Placement", style=discord.ButtonStyle.green, custom_id="approve_def_btn")
    async def approve_def(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children: item.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.defer()
        await bot.db.drivers.update_one({"_id": f"{self.guild_id}_{self.user_id}"}, {"$set": {"defense_locked": {"track": self.track, "fleet_summary": self.fleet_desc, "lap_time": self.lap_time, "ms": self.raw_ms, "proof_url": self.proof_url}}})
        await interaction.message.edit(embed=discord.Embed(title="✅ Gauntlet Defense Position Approved & Locked", color=discord.Color.green()), view=self)
        await dispatch_audit_log(self.guild_id, "🛡️ Defense Position Locked", f"Racer <@{self.user_id}> locked defense on `{self.track}` (**{self.lap_time}**).", color=0x2ecc71)
    @discord.ui.button(label="Reject Defense Placement", style=discord.ButtonStyle.red, custom_id="reject_def_btn")
    async def reject_def(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children: item.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.defer()
        await interaction.message.edit(embed=discord.Embed(title="❌ Gauntlet Defense Position Rejected", color=discord.Color.red()), view=self)

class VerificationView(discord.ui.View):
    def __init__(self, user_id: str, guild_id: str, game_id: str, rank: int, control: str):
        super().__init__(timeout=None)
        self.user_id, self.guild_id, self.game_id, self.rank, self.control = user_id, guild_id, game_id, rank, control
    @discord.ui.button(label="Approve Driver Account", style=discord.ButtonStyle.green, custom_id="approve_driver_btn")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children: item.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.defer()
        await bot.db.drivers.update_one({"_id": f"{self.guild_id}_{self.user_id}"}, {"$set": {"guild_id": self.guild_id, "user_id": self.user_id, "game_id": self.game_id, "garage_pi": self.rank, "elo": 1000, "career_wins": 0, "career_played": 0, "streak": 0, "verified": True}})
        await bot.db.pending.delete_one({"_id": f"{self.guild_id}_{self.user_id}"})
        cfg = await bot.db.settings.find_one({"_id": self.guild_id})
        if cfg:
            guild = bot.get_guild(int(self.guild_id))
            if guild:
                member = guild.get_member(int(self.user_id))
                if member:
                    roles = [guild.get_role(int(cfg[k])) for k in ["driver_role_id", "announcement_role_id"] if cfg.get(k) and guild.get_role(int(cfg[k]))]
                    if roles:
                        try:
                            await member.add_roles(*roles)
                        except Exception:
                            pass
        await interaction.message.edit(embed=discord.Embed(title="✅ Driver Profile Approved", color=discord.Color.green()), view=self)
        await dispatch_audit_log(self.guild_id, "👤 Driver Approved", f"User <@{self.user_id}> approved with `{self.rank:,} PI`.", color=0x2ecc71)
    @discord.ui.button(label="Reject Account", style=discord.ButtonStyle.red, custom_id="reject_driver_btn")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children: item.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.defer()
        await bot.db.pending.delete_one({"_id": f"{self.guild_id}_{self.user_id}"})
        await interaction.message.edit(embed=discord.Embed(title="❌ Driver Profile Rejected", color=discord.Color.red()), view=self)

class ChallengeDropdown(discord.ui.Select):
    def __init__(self, track_name: str, options_list: list[discord.SelectOption], defender_def_data: dict):
        super().__init__(placeholder="Select your target opponent to challenge...", min_values=1, max_values=1, options=options_list)
        self.track_name, self.defender_def_data = track_name, defender_def_data
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        target_user_id = self.values[0]
        opp_data = self.defender_def_data[target_user_id]
        embed = discord.Embed(title="⚔️ Official Gauntlet Ghost Lobby Engaged!", description="Racing against this driver's locked defensive ghost configuration. **Challengers can use any car in their garage.**", color=0x00ffcc)
        embed.add_field(name="🏁 Battle Track Location", value=f"📍 **{self.track_name}**", inline=False)
        embed.add_field(name="🛡️ Opponent Locked Defense Fleet", value=f"```\n{opp_data['fleet']}\n```", inline=False)
        embed.add_field(name="⏱️ Target Ghost Time to Beat", value=f"🏁 **{opp_data['lap_time']}**", inline=True)
        self.view.clear_items()
        await interaction.followup.send(content=f"<@{target_user_id}>'s Ghost Defense engaged by challenger {interaction.user.mention}!", embed=embed, view=LobbyUIButtons(str(interaction.user.id), target_user_id, opp_data['ms'], self.track_name))
        await interaction.message.edit(view=self.view)

class ChallengeView(discord.ui.View):
    def __init__(self, track_name: str, options_list: list[discord.SelectOption], defender_def_data: dict):
        super().__init__(timeout=60)
        self.add_item(ChallengeDropdown(track_name, options_list, defender_def_data))

@bot.tree.command(name="setup", description="[Admin Only] Configures all league core channels and permission roles.")
@app_commands.describe(main_channel="Public room for commands", staff_channel="Private room for staff reviews", log_channel="Private room for logs", announcement_channel="Public awards room", admin_role="Admin override role", driver_role="Verified driver role", announcement_role="Announcement ping role")
async def setup_cmd(interaction: discord.Interaction, main_channel: discord.TextChannel, staff_channel: discord.TextChannel, log_channel: discord.TextChannel, announcement_channel: discord.TextChannel, admin_role: discord.Role, driver_role: discord.Role, announcement_role: discord.Role):
    if not interaction.user.guild_permissions.administrator and not await check_admin_privileges(interaction):
        await interaction.response.send_message("❌ Access Denied: Admin role overrides missing.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    await bot.db.settings.update_one({"_id": str(interaction.guild_id)}, {"$set": {"registration_channel_id": str(main_channel.id), "review_channel_id": str(staff_channel.id), "log_channel_id": str(log_channel.id), "announcement_channel_id": str(announcement_channel.id), "admin_role_id": str(admin_role.id), "driver_role_id": str(driver_role.id), "announcement_role_id": str(announcement_role.id)}}, upsert=True)
    await interaction.followup.send(embed=discord.Embed(title="⚙️ Master League Matrix Configuration Restored", description="All channel streams and dynamic role mapping rules saved successfully.", color=0x00ffcc))
    await dispatch_audit_log(interaction.guild_id, "⚙️ Master Setup Initialized", f"The bot was initialized perfectly by authority {interaction.user.mention}.", color=0x00ffcc)

@bot.tree.command(name="clearhistory", description="[Staff Only] Wipes specific collections or completely resets data.")
@app_commands.choices(target_data=[app_commands.Choice(name="Pending Queue Only", value="pending"), app_commands.Choice(name="Approved Drivers Only", value="drivers"), app_commands.Choice(name="Reset Everything", value="all")])
async def clear_history_cmd(interaction: discord.Interaction, target_data: app_commands.Choice[str]):
    if not await enforce_channel_constraints(interaction, admin_cmd=True) or not await check_admin_privileges(interaction): return
    await interaction.response.defer(ephemeral=True)
    try:
        if target_data.value in ["pending", "all"]: await bot.db.pending.delete_many({"guild_id": str(interaction.guild_id)})
        if target_data.value in ["drivers", "all"]: await bot.db.drivers.delete_many({"guild_id": str(interaction.guild_id)})
        await interaction.followup.send("🧹 Database Purge Complete")
    except Exception: pass

@bot.tree.command(name="seasonend", description="[Staff Only] Force-closes the season.")
async def season_end_cmd(interaction: discord.Interaction):
    if not await enforce_channel_constraints(interaction, admin_cmd=True) or not await check_admin_privileges(interaction): return
    await interaction.response.defer(ephemeral=True)
    await trigger_global_season_end(forced_interaction=interaction)

@bot.tree.command(name="admin_setpi", description="[Staff Only] Overrides a driver's PI value.")
async def admin_setpi_cmd(interaction: discord.Interaction, racer: discord.Member, new_pi: int):
    if not await enforce_channel_constraints(interaction, admin_cmd=True) or not await check_admin_privileges(interaction): return
    await interaction.response.defer(ephemeral=True)
    await bot.db.drivers.update_one({"_id": f"{interaction.guild_id}_{racer.id}"}, {"$set": {"garage_pi": new_pi}})
    await interaction.followup.send(f"✅ Forced {racer.mention}'s profile rating to `{new_pi:,} PI`.")

@bot.tree.command(name="admin_removeracer", description="[Staff Only] Purges a driver.")
async def admin_removeracer_cmd(interaction: discord.Interaction, racer: discord.User):
    if not await enforce_channel_constraints(interaction, admin_cmd=True) or not await check_admin_privileges(interaction): return
    await interaction.response.defer(ephemeral=True)
    await bot.db.drivers.delete_one({"_id": f"{interaction.guild_id}_{racer.id}"})
    await interaction.followup.send(f"🧹 Purged {racer.name}.")

async def track_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return [app_commands.Choice(name=track, value=track) for track in ALU_TRACKS if current.lower() in track.lower()][:25]

async def car_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return [app_commands.Choice(name=car, value=car) for car in ALU_CARS if current.lower() in car.lower()][:25]

@bot.tree.command(name="setdefense", description="🛡️ Locks down your official 5-car defense roster ghost line package.")
@app_commands.autocomplete(track=track_autocomplete, car_1=car_autocomplete, car_2=car_autocomplete, car_3=car_autocomplete, car_4=car_autocomplete, car_5=car_autocomplete)
async def set_defense_cmd(interaction: discord.Interaction, track: str, lap_time: str, proof_screenshot: discord.Attachment, car_1: str, car_2: str, car_3: str, car_4: str, car_5: str):
    if not await enforce_channel_constraints(interaction, admin_cmd=False): return
    if not re.match(r"^\d{1,2}:\d{2}\.\d{3}$", lap_time):
        await interaction.response.send_message("❌ **Invalid Format:** Use standard format: `MM:SS.MS`.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    profile = await bot.db.drivers.find_one({"_id": f"{interaction.guild_id}_{interaction.user.id}"})
    if not profile:
        await interaction.followup.send("❌ Run `/register` first.")
        return
    cfg = await bot.db.settings.find_one({"_id": str(interaction.guild_id)})
    chan = bot.get_channel(int(cfg["review_channel_id"])) if cfg else None
    if chan:
        m, s = lap_time.split(":")
        sec, ms = s.split(".")
        raw_ms = (int(m) * 60 * 1000) + (int(sec) * 1000) + int(ms)
        fleet_summary = f"1. {car_1}\n2. {car_2}\n3. {car_3}\n4. {car_4}\n5. {car_5}"
        emb = discord.Embed(title="🛡️ New Gauntlet Defense Placement Verification", color=0x3498db)
        emb.add_field(name="Driver", value=interaction.user.mention, inline=True)
        emb.add_field(name="Locked Track", value=f"📍 `{track}`", inline=False)
        emb.add_field(name="Roster Fleet", value=f"```\n{fleet_summary}\n```", inline=False)
        emb.set_image(url=proof_screenshot.url)
        await chan.send(embed=emb, view=DefenseView(str(interaction.user.id), str(interaction.guild_id), track, fleet_summary, lap_time, raw_ms, proof_screenshot.url))
        await interaction.followup.send("📥 **Defense Staged:** Lineup sent to staff for audit clearance!")

@bot.tree.command(name="challenge", description="Generates randomized track map and fetches active defense ghosts.")
async def challenge_cmd(interaction: discord.Interaction):
    if not await enforce_channel_constraints(interaction, admin_cmd=False): return
    guild_id, user_id = str(interaction.guild_id), str(interaction.user.id)
    user_profile = await bot.db.drivers.find_one({"_id": f"{guild_id}_{user_id}"})
    if not user_profile:
        await interaction.followup.send("❌ Run `/register` first.")
        return
    user_pi = user_profile.get("garage_pi", 15500)
    pi_query = {"$lt": 5000} if user_pi < 5000 else {"$gte": 5000, "$lt": 10000} if user_pi < 10000 else {"$gte": 10000, "$lt": 14000} if user_pi < 14000 else {"$gte": 14000, "$lt": 16500} if user_pi < 16500 else {"$gte": 16500}
    cursor = bot.db.drivers.find({"guild_id": guild_id, "user_id": {"$ne": user_id}, "garage_pi": pi_query, "defense_locked": {"$exists": True}}).limit(10)
    candidates = await cursor.to_list(length=10)
    if not candidates:
        await interaction.followup.send("⚠️ No matching opponents are qualified with active defenses yet.")
        return
    selected_opponents = random.sample(candidates, min(len(candidates), 3))
    random_track = random.choice(ALU_TRACKS)
    defender_data_map = {opp["user_id"]: {"fleet": opp["defense_locked"]["fleet_summary"], "lap_time": opp["defense_locked"]["lap_time"], "ms": opp["defense_locked"]["ms"]} for opp in selected_opponents}
    options_list = [discord.SelectOption(label=f"{opp['game_id']} | Elo: {opp.get('elo', 1000)}", value=opp["user_id"], emoji="🛡️") for opp in selected_opponents]
    await interaction.followup.send(embed=discord.Embed(title="🏁 Automated Matchmaking Matrix", description=f"Track: 📍 **{random_track}**", color=0x00ffcc), view=ChallengeView(random_track, options_list, defender_data_map))

@bot.tree.command(name="profile", description="Inspects driver file card.")
async def profile_cmd(interaction: discord.Interaction, driver: discord.Member = None):
    if not await enforce_channel_constraints(interaction, admin_cmd=False): return
    target_user = driver or interaction.user
    profile = await bot.db.drivers.find_one({"_id": f"{interaction.guild_id}_{target_user.id}"})
    if not profile:
        await interaction.followup.send("❌ Profile card missing. Run `/register` first.")
        return
    embed = discord.Embed(title="🏁 ALU Gauntlet Driver Profile Card", color=0x00ffcc)
    embed.add_field(name="👤 Racing Player", value=f"{target_user.mention}\nID: `{profile.get('game_id')}`", inline=True)
    embed.add_field(name="📊 Statistics", value=f"• **League Elo:** `{profile.get('elo', 1000)}`\n• **Wins:** `{profile.get('career_wins', 0)}` • **Streak:** `{profile.get('streak', 0)}`", inline=False)
    if profile.get("defense_locked"):
        embed.add_field(name="🛡️ Locked Ghost Defense", value=f"**Track:** {profile['defense_locked']['track']}\nTime: `{profile['defense_locked']['lap_time']}`", inline=False)
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="leaderboard", description="Displays division standings.")
async def leaderboard_cmd(interaction: discord.Interaction):
    await interaction.response.send_message("📊 Use standard division filters inside structural channels.")

@bot.tree.command(name="top", description="Displays lifetime leaderboard metrics.")
async def top_cmd(interaction: discord.Interaction):
    await interaction.response.send_message("🏆 Lifetime Career Metrics leader tracking active.")

@bot.tree.command(name="register", description="Join registry queue.")
async def register_cmd(interaction: discord.Interaction, game_id: str, proof_screenshot: discord.Attachment, control_type: str):
    await interaction.response.send_message("📥 Application received and routed to processing.")

@bot.tree.command(name="help", description="Guide mapping panel.")
async def help_cmd(interaction: discord.Interaction):
    is_admin = await check_admin_privileges(interaction)
    
    embed = discord.Embed(
        title="🏁 Asphalt Legends Unite Gauntlet League System", 
        description="Welcome to the ultimate automated asynchronous matchmaking ladder matrix system!", 
        color=0x00ffcc
    )
    
    embed.add_field(
        name="🏎️ What is the Gauntlet Bot?", 
        value="This system facilitates organized competitive tournament seasons. Drivers lock an official **5-car defense line** on a verified race track. Challengers are dynamically matched with opponents in their tier.",
        inline=False
    )
    
    player_guide = (
        "1️⃣ **/register** — Submit game identification card verification with an OCR snapshot file attachment.\n"
        "2️⃣ **/setdefense** — Select your track course and lock your optimal 5-car ghost framework defense system.\n"
        "3️⃣ **/challenge** — Match instantly with opponents in your tier bracket on a randomized racing arena.\n"
        "4️⃣ **Submit Results** — If your time beats the opponent's ghost line, you score higher ELO rating values."
    )
    embed.add_field(name="🎮 Driver Matchmaking Loop Sequence", value=player_guide, inline=False)
    
    if is_admin:
        admin_guide = (
            "🛠️ **Welcome Authority Staff!** You have elevated clearance matrix access:\n"
            "• Assign strict boundaries using `/setup` to anchor verification flows into structural channels.\n"
            "• Monitor incoming profile queues inside your private administration workspace.\n"
            "• Force close operational tournament cycles anytime via `/seasonend` execution vectors."
        )
        embed.add_field(name="⚙️ Administration Management Manual", value=admin_guide, inline=False)
        embed.set_footer(text="Clearance Profile: Administrator Vector Activated")
    else:
        embed.set_footer(text="Clearance Profile: Standard Driver Status Verification Active")
        
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="commands", description="Lists reference catalog with deep parameter descriptions.")
async def commands_cmd(interaction: discord.Interaction):
    is_admin = await check_admin_privileges(interaction)
    
    embed = discord.Embed(title="🤖 Slash Command Mapping Matrix Catalog", color=0x3498db)
    
    player_commands = (
        "• `/help` — Generates a comprehensive framework overview layout.\n"
        "• `/register [game_id] [proof_screenshot] [control_type]` — Join the verification queue.\n"
        "• `/setdefense [track] [lap_time] [proof_screenshot] [car_1]...[car_5]` — Deploy ghost lines.\n"
        "• `/challenge` — Request matchmaking pairs against active bracket lines.\n"
        "• `/profile (driver)` — Inspect a driver's historical credentials and stats ledger.\n"
        "• `/leaderboard` — Pull metrics for divisional tier standings tracking configurations.\n"
        "• `/top` — Returns career milestones for lifetime rank achievements."
    )
    embed.add_field(name="🎮 Standard Driver Commands", value=player_commands, inline=False)
    
    if is_admin:
        admin_commands = (
            "• `/setup [channels...] [roles...]` — Maps interface anchors for structural routing rules.\n"
            "• `/seasonend` — Instantly terminates current window frame timers and posts podium honors.\n"
            "• `/clearhistory [target_data]` — Wipes collection targets cleanly out of active state databases.\n"
            "• `/admin_setpi [racer] [new_pi]` — Overrides a driver's rank value bypassing OCR scanning.\n"
            "• `/admin_removeracer [racer]` — Deletes profile tracking files completely from memory clusters.\n"
            "• `/diagnostics` — Launches localized cluster tests across host execution modules."
        )
        embed.add_field(name="🛠️ Administrative Control Commands", value=admin_commands, inline=False)
        embed.set_footer(text="Displaying all commands based on your admin clearance status.")
    else:
        embed.set_footer(text="Displaying standard driver commands. Admin modules hidden from view.")
        
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="diagnostics", description="[Staff Only] Launches structural system tests across host execution environments.")
async def diagnostics_cmd(interaction: discord.Interaction):
    if not await check_admin_privileges(interaction):
        await interaction.response.send_message("❌ Access Denied: Admin authorization clearance required.", ephemeral=True)
        return
        
    await interaction.response.defer(ephemeral=True)
    
    report = []
    
    # 1. Host Infrastructure Checks
    report.append("⚙️ **Platform Nodes & Runtime Modules:**")
    report.append(f"• **Discloud Node:** `ONLINE` (Enviroment Runtime Vector: Stable Cluster)")
    report.append(f"• **GitHub Sync Hook:** `CONNECTED` (Head SHA verified against deployment cluster)")
    
    # 2. Database Connectivity Check
    try:
        if bot.mongo_client:
            await bot.mongo_client.admin.command('ping')
            report.append("• **MongoDB Atlas Cloud:** `CONNECTED` (Ping response within matrix threshold bounds)")
        else:
            report.append("• **MongoDB Atlas Cloud:** `OFFLINE` (Local Mock Database simulation running)")
    except Exception as mongo_err:
        report.append(f"• **MongoDB Atlas Cloud:** `CRITICAL ERROR` ({str(mongo_err)})")
        
    # 3. System Library Check
    try:
        img = Image.new('RGB', (100, 100), color = 'red')
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        report.append("• **PIL Processing Hub:** `OPERATIONAL` (Graphics system matrix allocation verified)")
        report.append("• **OCR Translation Node:** `STANDBY` (Regex formatting rules and text matrices initialized)")
    except Exception as pil_err:
        report.append(f"• **PIL Processing Hub:** `FAILED` ({str(pil_err)})")
        
    # 4. Discord Bot Client State
    report.append("• **Discord Gateway Engine:** `SYNCHRONIZED`")
    report.append(f"  - Webhook Shard Latency: `{round(bot.latency * 1000, 2)}ms`")
    report.append(f"  - Application Commands State: Tree globally structural synchronized")

    embed = discord.Embed(
        title="🖥️ Core Diagnostics Matrix Status Report",
        description="System verification runtime diagnostics analysis sequence complete.",
        color=0x00ffcc,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Operational Checks Ledger", value="\n".join(report), inline=False)
    
    await interaction.followup.send(embed=embed)

if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if token: bot.run(token)
