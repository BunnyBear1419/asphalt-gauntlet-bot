import os
import re
import time
import logging
import asyncio
import aiohttp
import urllib.parse
import json
import random
import csv
from datetime import datetime, timezone
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

# UI Design & Premium Media Asset Configuration Matrix (Official Asphalt Legends Assets)
ASPHALT_THEME_COLOR = 0x00FFCC  # Main electric cyan theme
ASPHALT_ADMIN_COLOR = 0xFF3366  # Cyber pink/red for staff metrics
ASPHALT_ALERT_COLOR = 0xFFCC00  # Warning amber
ASPHALT_VICTORY_COLOR = 0x2ECC71  # Racing victory green
ASPHALT_DEFEAT_COLOR = 0xE74C3C  # Defeat crimson red

ASPHALT_MEDIA = {
    "banner_help": "https://images.squarespace-cdn.com/content/v1/5b16954ad274cb7609206ad6/01e9d1bf-5b23-4560-843e-c6df6ba88cc4/Asphalt_Legends_Unite_Key_Art_16x9.jpg",
    "banner_match": "https://img.youtube.com/vi/M7W-wZby6O0/maxresdefault.jpg",
    "banner_leaderboard": "https://images.squarespace-cdn.com/content/v1/5b16954ad274cb7609206ad6/cbda3907-fbfa-45b6-9bb2-bf727ea198d5/ALU_Showroom_Concept_Art.jpg",
    "thumb_profile": "https://i.imgur.com/vHwZofG.png",
    "thumb_diagnostics": "https://i.imgur.com/f9WvCsc.png"
}

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

# Single source of truth for PI-based divisions/tiers
PI_DIVISIONS = [
    {"name": "👑 Division 6 — Legend Tier", "min": 22001, "max": None, "color": 0x9b59b6},
    {"name": "🏆 Division 5 — Champ Tier", "min": 18501, "max": 22001, "color": 0xe74c3c},
    {"name": "💎 Division 4 — Platinum Tier", "min": 15001, "max": 18501, "color": 0x3498db},
    {"name": "🥇 Division 3 — Gold Tier", "min": 11501, "max": 15001, "color": 0xdeaf2a},
    {"name": "🥈 Division 2 — Silver Tier", "min": 8001, "max": 11501, "color": 0xa4a7a9},
    {"name": "🥉 Division 1 — Bronze Tier", "min": 0, "max": 8001, "color": 0xa3704c},
]

def division_mongo_query(division: dict) -> dict:
    query = {}
    if division.get("min") is not None:
        query["$gte"] = division["min"]
    if division.get("max") is not None:
        query["$lt"] = division["max"]
    return query

def get_division_for_pi(pi: int) -> dict:
    for division in PI_DIVISIONS:
        if pi >= division["min"] and (division["max"] is None or pi < division["max"]):
            return division
    return PI_DIVISIONS[-1]

def format_lap_time(total_ms: int) -> str:
    minutes = total_ms // 60000
    seconds = (total_ms % 60000) // 1000
    millis = total_ms % 1000
    return f"{minutes:01d}:{seconds:02d}.{millis:03d}"

def parse_lap_time(lap_str: str) -> int:
    if not re.match(r"^\d{1,2}:\d{2}\.\d{3}$", lap_str):
        return -1
    m, s = lap_str.split(":")
    sec, ms = s.split(".")
    return (int(m) * 60 * 1000) + (int(sec) * 1000) + int(ms)

def has_5_course_defense(profile: dict) -> bool:
    if not profile: return False
    defense = profile.get("defense_locked")
    if not defense: return False
    courses = defense.get("courses")
    if not courses or len(courses) < 5: return False
    return True

ELO_DELTA_BY_WINS = {5: 25, 4: 15, 3: 5, 2: -5, 1: -15, 0: -25}

class GauntletBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
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

        await self.recover_season_state()
        self.seasonal_clock_loop.start()
        try:
            media_doc = await self.db.settings.find_one({"_id": "global_media"})
            if media_doc and media_doc.get("custom_images"):
                for key, url in media_doc["custom_images"].items():
                    ASPHALT_MEDIA[key] = url
        except Exception as e:
            logging.warning(f"⚠️ Could not load custom images: {e}")
        await self.tree.sync()
        self.add_view(TopLeaderboardView())
        self.add_view(LeaderboardDivisionView())
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
        except Exception as state_err:
            logging.error(f"Failed to execute state recovery sequence hooks: {state_err}")

    def setup_mock_db(self):
        class MockCollection:
            async def find_one(self, *args, **kwargs): return None
            async def update_one(self, *args, **kwargs): return None
            async def insert_one(self, *args, **kwargs): return None
            async def delete_one(self, *args, **kwargs): return None
            async def count_documents(self, *args, **kwargs): return 0
            async def delete_many(self, *args, **kwargs):
                class MockResult:
                    def __init__(self): self.deleted_count = 0
                return MockResult()
            def find(self, *args, **kwargs):
                class MockCursor:
                    async def to_list(self, *args, **kwargs): return []
                    def sort(self, *args, **kwargs): return self
                    def skip(self, *args, **kwargs): return self
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
    if not state: return
    if now >= state["ends_at"]:
        await trigger_global_season_end()

@seasonal_clock_loop_task.before_loop
async def before_seasonal_clock():
    await bot.wait_until_ready()

bot.seasonal_clock_loop = seasonal_clock_loop_task

async def check_admin_privileges(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator or interaction.user.id == interaction.guild.owner_id:
        return True
    cfg = await bot.db.settings.find_one({"_id": str(interaction.guild_id)})
    if cfg and cfg.get("admin_role_id"):
        target_role = interaction.guild.get_role(int(cfg["admin_role_id"]))
        if target_role in interaction.user.roles:
            return True
    return False

async def enforce_channel_constraints(interaction: discord.Interaction, admin_cmd: bool = False) -> bool:
    if await check_admin_privileges(interaction):
        return True
        
    cfg = await bot.db.settings.find_one({"_id": str(interaction.guild_id)})
    if not cfg:
        await interaction.response.send_message("❌ **System Offline:** Run `/setup` first.", ephemeral=True)
        return False
        
    current_chan = str(interaction.channel_id)
    if admin_cmd:
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
            emb = discord.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
            try: await chan.send(embed=emb)
            except Exception: pass

async def dispatch_automated_announcement(guild_id: str, title: str, description: str, color: int = 0x00FFCC, image_url: str = None):
    cfg = await bot.db.settings.find_one({"_id": str(guild_id)})
    if cfg and cfg.get("announcement_channel_id"):
        chan = bot.get_channel(int(cfg["announcement_channel_id"]))
        if chan:
            emb = discord.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
            if image_url: emb.set_image(url=image_url)
            ping_content = f"<@&{cfg['player_role_id']}>" if cfg.get("player_role_id") else ""
            try: await chan.send(content=ping_content, embed=emb)
            except Exception: pass

async def apply_season_soft_reset(guild_id: str):
    cursor = bot.db.drivers.find({"guild_id": str(guild_id)})
    drivers = await cursor.to_list(length=10000)
    for d in drivers:
        old_elo = d.get("elo", 1000)
        new_elo = max(100, round(1000 + (old_elo - 1000) * 0.5))
        await bot.db.drivers.update_one(
            {"_id": d["_id"]}, 
            {
                "$set": {"elo": new_elo, "streak": 0, "needs_re_registration": True},
                "$unset": {"defense_locked": "", "pending_tracks": "", "defense_review_pending": ""}
            }
        )

async def trigger_global_season_end(forced_interaction: discord.Interaction = None):
    now = time.time()
    state = await bot.db.season_state.find_one({"_id": "current_season"})
    current_season_num = state.get("season_number", 1) if state else 1
    guild_settings_cursor = bot.db.settings.find({})
    guild_configs = await guild_settings_cursor.to_list(length=100)
    for config in guild_configs:
        guild_id = config["_id"]
        channel_id = config.get("announcement_channel_id") or config.get("registration_channel_id")
        if not channel_id: continue
        target_channel = bot.get_channel(int(channel_id))
        if not target_channel: continue
        
        header_embed = discord.Embed(
            title=f"🏁 SEASON {current_season_num} GAUNTLET FINALE PODIUMS", 
            description="🏁 **Tournament locks activated!**\n\n⚙️ *ELO ratings soft-reset. Defensive frameworks cleared completely. Existing drivers must update their garage profiles using `/register` for new division placements.*", 
            color=0xffaa00
        )
        header_embed.set_image(url=ASPHALT_MEDIA["banner_leaderboard"])
        await target_channel.send(embed=header_embed)
        
        csv_buffer = io.StringIO()
        csv_writer = csv.writer(csv_buffer)
        csv_writer.writerow(["Division", "Rank", "User ID", "Game ID", "ELO Rating", "Garage PI"])
        
        for div in PI_DIVISIONS:
            cursor = bot.db.drivers.find({"guild_id": str(guild_id), "garage_pi": division_mongo_query(div)}).sort("elo", -1).limit(100)
            top_drivers = await cursor.to_list(length=100)
            div_embed = discord.Embed(title=div["name"], color=div["color"])
            if not top_drivers: 
                div_embed.description = "*No verified driver positions secured in this tier bracket.*"
            else:
                standings_text = ""
                for r, d in enumerate(top_drivers[:10]):
                    medal = '🥇 ' if r==0 else '🥈 ' if r==1 else '🥉 ' if r==2 else f'**#{r+1}** '
                    standings_text += f"{medal} <@{d['user_id']}> | `{d['game_id']}` — **{d.get('elo', 1000)} ELO**\n"
                for r, d in enumerate(top_drivers):
                    csv_writer.writerow([div["name"], r+1, d['user_id'], d['game_id'], d.get('elo', 1000), d.get('garage_pi', 0)])
                div_embed.add_field(name="🏆 Final Elite Placements", value=standings_text, inline=False)
            await target_channel.send(embed=div_embed)
            
        csv_buffer.seek(0)
        discord_file = discord.File(fp=io.BytesIO(csv_buffer.getvalue().encode('utf-8')), filename=f"season_{current_season_num}_final_leaderboard.csv")
        await target_channel.send(content="📊 **Divisional Standings Ledger Matrix Download:**", file=discord_file)
        await apply_season_soft_reset(guild_id)
            
    await bot.db.pending.delete_many({})
    await bot.db.season_state.update_one({"_id": "current_season"}, {"$set": {"season_number": current_season_num + 1, "ends_at": now + (14 * 24 * 60 * 60)}}, upsert=True)
    if forced_interaction:
        await forced_interaction.followup.send(embed=discord.Embed(title="⚙️ Season Rollover Executed", description="All dynamic structure maps cycled securely, podium files dispatched, and defenses wiped.", color=ASPHALT_THEME_COLOR))

async def process_match_result(guild_id: str, challenger_id: str, opponent_id: str, defense_courses: list, challenger_times: list, proof_url: str, defender_proof_url: str = None, origin_channel_id: int = None):
    p1 = await bot.db.drivers.find_one({"_id": f"{guild_id}_{challenger_id}"})
    p2 = await bot.db.drivers.find_one({"_id": f"{guild_id}_{opponent_id}"})
    if not p1 or not p2: return None

    courses_beat = sum(1 for i in range(5) if challenger_times[i]["ms"] < defense_courses[i]["ms"])
    challenger_won = courses_beat >= 3
    challenger_delta = ELO_DELTA_BY_WINS[courses_beat]
    defender_delta = -challenger_delta
    old_challenger_elo = p1.get("elo", 1000)
    old_defender_elo = p2.get("elo", 1000)

    breakdown = ""
    for i in range(5):
        beat = challenger_times[i]["ms"] < defense_courses[i]["ms"]
        icon = "✅" if beat else "❌"
        breakdown += f"{icon} **Course {i+1}** — `{defense_courses[i]['track']}`\n   🛡️ `{defense_courses[i]['car']}` | `{defense_courses[i]['lap_time']}`\n   ⚔️ `{challenger_times[i]['car']}` | `{challenger_times[i]['lap_time_str']}`\n"

    if challenger_won:
        current_streak = p1.get("streak", 0) + 1
        streak_bonus = min(20, (current_streak // 2) * 4) if current_streak >= 2 else 0
        new_challenger_elo = max(100, old_challenger_elo + challenger_delta + streak_bonus)
        new_defender_elo = max(100, old_defender_elo + defender_delta)
        outcome_desc = f"🏆 <@{challenger_id}> **won the match** — beat {courses_beat}/5 ghost times!\n\n{breakdown}"
        display_color = ASPHALT_VICTORY_COLOR
        announce_title = "⚡ GAUNTLET MATCH WON"
        w_id, l_id = challenger_id, opponent_id
        new_w_elo, new_l_elo = new_challenger_elo, new_defender_elo
        old_w_elo, old_l_elo = old_challenger_elo, old_defender_elo
    else:
        current_streak = p2.get("streak", 0) + 1
        streak_bonus = min(20, (current_streak // 2) * 4) if current_streak >= 2 else 0
        new_defender_elo = max(100, old_defender_elo + defender_delta + streak_bonus)
        new_challenger_elo = max(100, old_challenger_elo + challenger_delta)
        outcome_desc = f"💀 <@{opponent_id}>'s **ghost defense held** — challenger only beat {courses_beat}/5 courses.\n\n{breakdown}"
        display_color = ASPHALT_DEFEAT_COLOR
        announce_title = "🛡️ DEFENSE HOLD SECURED"
        w_id, l_id = opponent_id, challenger_id
        new_w_elo, new_l_elo = new_defender_elo, new_challenger_elo
        old_w_elo, old_l_elo = old_defender_elo, old_challenger_elo

    await bot.db.drivers.update_one({"_id": f"{guild_id}_{w_id}"}, {"$set": {"elo": new_w_elo}, "$inc": {"career_wins": 1, "career_played": 1, "streak": 1}})
    await bot.db.drivers.update_one({"_id": f"{guild_id}_{l_id}"}, {"$set": {"elo": new_l_elo, "streak": 0}, "$inc": {"career_played": 1}})

    for i in range(5):
        c_time = challenger_times[i]
        await bot.db.universal_bests.update_one(
            {"guild_id": guild_id, "track": defense_courses[i]["track"], "user_id": challenger_id},
            {"$min": {"ms": c_time["ms"]}, "$set": {"car": c_time["car"], "lap_time": c_time["lap_time_str"]}},
            upsert=True
        )

    match_id = f"{guild_id}_{challenger_id}_{opponent_id}_{int(time.time())}"
    match_record = {
        "_id": match_id, "guild_id": guild_id, "challenger_id": challenger_id, "opponent_id": opponent_id,
        "courses_beat": courses_beat, "challenger_won": challenger_won, "challenger_delta": new_challenger_elo - old_challenger_elo,
        "defender_delta": new_defender_elo - old_defender_elo, "w_id": w_id, "l_id": l_id, "new_w_elo": new_w_elo, "new_l_elo": new_l_elo,
        "outcome_desc": outcome_desc, "display_color": display_color, "announce_title": announce_title, "proof_url": proof_url, "reverted": False
    }
    await bot.db.matches.insert_one(match_record)
    return match_record

class MatchResultPostView(discord.ui.View):
    def __init__(self, match_id: str):
        super().__init__(timeout=None)
        self.match_id = match_id

    @discord.ui.button(label="Report Issue", style=discord.ButtonStyle.danger, custom_id="report_match_btn")
    async def report_issue(self, interaction: discord.Interaction, button: discord.ui.Button):
        match = await bot.db.matches.find_one({"_id": self.match_id})
        if not match or match.get("reverted"):
            await interaction.response.send_message("❌ Match unavailable or reverted.", ephemeral=True)
            return
        cfg = await bot.db.settings.find_one({"_id": match["guild_id"]})
        admin_chan = bot.get_channel(int(cfg["review_channel_id"])) if cfg else None
        if not admin_chan: return

        report_emb = discord.Embed(title="⚠️ Match Result Reported", description=match["outcome_desc"], color=0xe74c3c)
        report_emb.add_field(name="Reported by", value=interaction.user.mention)
        report_emb.set_image(url=match["proof_url"])
        await admin_chan.send(embed=report_emb, view=MatchRevertView(self.match_id))
        await interaction.response.send_message("✅ Match reported to staff panels.", ephemeral=True)

class MatchRevertView(discord.ui.View):
    def __init__(self, match_id: str):
        super().__init__(timeout=None)
        self.match_id = match_id

    @discord.ui.button(label="Revert ELO", style=discord.ButtonStyle.danger, custom_id="revert_elo_btn")
    async def revert_elo(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await check_admin_privileges(interaction): return
        match = await bot.db.matches.find_one({"_id": self.match_id})
        if not match or match.get("reverted"): return

        p1 = await bot.db.drivers.find_one({"_id": f"{match['guild_id']}_{match['challenger_id']}"})
        p2 = await bot.db.drivers.find_one({"_id": f"{match['guild_id']}_{match['opponent_id']}"})
        
        await bot.db.drivers.update_one({"_id": p1["_id"]}, {"$inc": {"elo": -match["challenger_delta"]}})
        await bot.db.drivers.update_one({"_id": p2["_id"]}, {"$inc": {"elo": -match["defender_delta"]}})
        await bot.db.matches.update_one({"_id": self.match_id}, {"$set": {"reverted": True}})
        
        await interaction.response.send_message("✅ ELO ratings rolled back safely.", ephemeral=True)
        await dispatch_audit_log(match["guild_id"], "⚠️ Match ELO Reverted", f"Staff {interaction.user.mention} reverted match `{self.match_id}`.")

class RegistrationDeclineModal(discord.ui.Modal, title="Specify Application Rejection Reason"):
    reason_input = discord.ui.TextInput(label="Reason for Disapproval", style=discord.TextStyle.paragraph, required=True)
    def __init__(self, user_id: str, guild_id: str):
        super().__init__()
        self.user_id, self.guild_id = user_id, guild_id
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await bot.db.pending.delete_one({"_id": f"{self.guild_id}_{self.user_id}"})
        guild = bot.get_guild(int(self.guild_id))
        member = guild.get_member(int(self.user_id)) if guild else None
        if member:
            emb = discord.Embed(title="❌ REGISTRY APPLICATION DECLINED", description=f"Your packet for **{guild.name}** was rejected.\nReason: `{self.reason_input.value}`", color=ASPHALT_DEFEAT_COLOR)
            try: await member.send(embed=emb)
            except Exception: pass
        await dispatch_audit_log(self.guild_id, "👤 Driver Application Declined", f"User <@{self.user_id}> denied by {interaction.user.mention}. Reason: {self.reason_input.value}")

class VerificationView(discord.ui.View):
    def __init__(self, user_id: str, guild_id: str, game_id: str, rank: int, control: str):
        super().__init__(timeout=None)
        self.user_id, self.guild_id, self.game_id, self.rank, self.control = user_id, guild_id, game_id, rank, control

    @discord.ui.button(label="Approve Driver Account", style=discord.ButtonStyle.green, custom_id="approve_driver_btn")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children: item.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.defer()
        
        existing = await bot.db.drivers.find_one({"_id": f"{self.guild_id}_{self.user_id}"})
        if existing:
            await bot.db.drivers.update_one(
                {"_id": existing["_id"]},
                {"$set": {"game_id": self.game_id, "garage_pi": int(self.rank), "needs_re_registration": False}}
            )
        else:
            await bot.db.drivers.update_one(
                {"_id": f"{self.guild_id}_{self.user_id}"},
                {"$set": {
                    "guild_id": self.guild_id, "user_id": self.user_id, "game_id": self.game_id, 
                    "garage_pi": int(self.rank), "elo": 1000, "career_wins": 0, "career_played": 0, 
                    "streak": 0, "verified": True, "needs_re_registration": False
                }}, upsert=True
            )
            
        await bot.db.pending.delete_one({"_id": f"{self.guild_id}_{self.user_id}"})
        cfg = await bot.db.settings.find_one({"_id": self.guild_id})
        guild = bot.get_guild(int(self.guild_id))
        member = guild.get_member(int(self.user_id)) if guild else None
        if member and cfg and cfg.get("player_role_id"):
            try: await member.add_roles(guild.get_role(int(cfg["player_role_id"])))
            except Exception: pass
            
        await interaction.message.edit(embed=discord.Embed(title="✅ Driver Profile Approved", color=ASPHALT_VICTORY_COLOR), view=self)
        await dispatch_audit_log(self.guild_id, "👤 Driver Approved", f"User <@{self.user_id}> verified at `{self.rank:,} PI` by staff panel action.")

    @discord.ui.button(label="Reject Account", style=discord.ButtonStyle.red, custom_id="reject_driver_btn")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RegistrationDeclineModal(self.user_id, self.guild_id))
        for item in self.children: item.disabled = True
        await interaction.message.edit(view=self)

class ReferenceApprovalView(discord.ui.View):
    def __init__(self, track: str, lap_time: str, video_url: str, submitter_id: str, guild_id: str):
        super().__init__(timeout=None)
        self.track, self.lap_time, self.video_url, self.submitter_id, self.guild_id = track, lap_time, video_url, submitter_id, guild_id

    @discord.ui.button(label="Approve Reference", style=discord.ButtonStyle.green, custom_id="approve_ref_btn")
    async def approve_ref(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children: item.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.defer()
        
        await bot.db.map_references.update_one(
            {"guild_id": self.guild_id, "track": self.track},
            {"$set": {"lap_time": self.lap_time, "video_url": self.video_url, "user_id": self.submitter_id}},
            upsert=True
        )
        await interaction.message.edit(embed=discord.Embed(title="✅ Reference Map Video Approved", color=ASPHALT_VICTORY_COLOR))
        await dispatch_audit_log(self.guild_id, "🎬 Reference Video Added", f"New record video for `{self.track}` approved by {interaction.user.mention}.")

    @discord.ui.button(label="Decline Reference", style=discord.ButtonStyle.red, custom_id="reject_ref_btn")
    async def reject_ref(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ReferenceDeclineModal(self.submitter_id, self.guild_id, self.track))
        for item in self.children: item.disabled = True
        await interaction.message.edit(view=self)

class ReferenceDeclineModal(discord.ui.Modal, title="Reference Video Rejection Reason"):
    reason = discord.ui.TextInput(label="Reason", style=discord.TextStyle.paragraph, required=True)
    def __init__(self, submitter_id: str, guild_id: str, track: str):
        super().__init__()
        self.submitter_id, self.guild_id, self.track = submitter_id, guild_id, track
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        guild = bot.get_guild(int(self.guild_id))
        member = guild.get_member(int(self.submitter_id)) if guild else None
        if member:
            emb = discord.Embed(title="❌ Reference Video Submission Declined", description=f"Your reference track update for `{self.track}` was rejected.\nReason: `{self.reason.value}`", color=ASPHALT_DEFEAT_COLOR)
            try: await member.send(embed=emb)
            except Exception: pass

class DuelReportModal(discord.ui.Modal, title="Submit Gauntlet Match Results"):
    challenger_laps = discord.ui.TextInput(label="Your 5 Lap Times (one per line, MM:SS.MS)", style=discord.TextStyle.paragraph, placeholder="01:12.431\n01:15.123...", required=True)
    challenger_cars = discord.ui.TextInput(label="Your 5 Attack Cars (one per line)", style=discord.TextStyle.paragraph, placeholder="Devel Sixteen...", required=True)
    screenshot_proof = discord.ui.TextInput(label="Paste Race Score card Screenshot URL", placeholder="Direct image link...", required=True)

    def __init__(self, challenger_id: str, opponent_id: str, defense_courses: list, defender_proof_url: str = None):
        super().__init__()
        self.challenger_id, self.opponent_id, self.defense_courses = challenger_id, opponent_id, defense_courses
        self.defender_proof_url = defender_proof_url

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)

        raw_lines = [line.strip() for line in self.challenger_laps.value.strip().split("\n") if line.strip()]
        car_lines = [line.strip() for line in self.challenger_cars.value.strip().split("\n") if line.strip()]
        if len(raw_lines) != 5 or len(car_lines) != 5:
            await interaction.followup.send("❌ Out of bounds entries. Provide exactly 5 parameters lines.", ephemeral=True)
            return

        challenger_times = []
        for i, line in enumerate(raw_lines):
            ms = parse_lap_time(line)
            if ms < 0: return
            challenger_times.append({"lap_time_str": line, "ms": ms, "car": car_lines[i]})

        cfg = await bot.db.settings.find_one({"_id": guild_id})
        results_chan = bot.get_channel(int(cfg["match_results_channel_id"])) if cfg else None
        if not results_chan: return

        match_data = await process_match_result(guild_id, self.challenger_id, self.opponent_id, self.defense_courses, challenger_times, self.screenshot_proof.value.strip(), self.defender_proof_url, interaction.channel_id)
        if not match_data: return

        result_emb = discord.Embed(title="🏁 Gauntlet Match Result", description=match_data["outcome_desc"], color=match_data["display_color"])
        result_emb.set_image(url=self.screenshot_proof.value.strip())
        await results_chan.send(embed=result_emb, view=MatchResultPostView(match_data["_id"]))
        await interaction.followup.send("✅ **Match processed successfully!**", ephemeral=True)

class LobbyUIButtons(discord.ui.View):
    def __init__(self, challenger_id: str, opponent_id: str, defense_courses: list, defender_proof_url: str = None):
        super().__init__(timeout=1800)
        self.challenger_id, self.opponent_id, self.defense_courses = challenger_id, opponent_id, defense_courses
        self.defender_proof_url = defender_proof_url
    @discord.ui.button(label="Submit Match Results", style=discord.ButtonStyle.blurple, custom_id="lobby_report_btn")
    async def report_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.challenger_id: return
        await interaction.response.send_modal(DuelReportModal(self.challenger_id, self.opponent_id, self.defense_courses, self.defender_proof_url))

class DefenseView(discord.ui.View):
    def __init__(self, user_id: str, guild_id: str, courses: list, proof_url: str, is_change: bool = False):
        super().__init__(timeout=None)
        self.user_id, self.guild_id, self.courses, self.proof_url = user_id, guild_id, courses, proof_url
        self.is_change = is_change
    @discord.ui.button(label="Approve Defense Placement", style=discord.ButtonStyle.green, custom_id="approve_def_btn")
    async def approve_def(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children: item.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.defer()
        await bot.db.drivers.update_one({"_id": f"{self.guild_id}_{self.user_id}"}, {"$set": {"defense_locked": {"courses": self.courses, "proof_url": self.proof_url}, "last_defense_change": time.time()}, "$unset": {"pending_tracks": "", "pending_is_change": "", "defense_review_pending": ""}})
        await interaction.message.edit(embed=discord.Embed(title="✅ Defense Verified & Locked", color=ASPHALT_VICTORY_COLOR))

    @discord.ui.button(label="Reject Defense Placement", style=discord.ButtonStyle.red, custom_id="reject_def_btn")
    async def reject_def(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children: item.disabled = True
        await interaction.message.edit(view=self)
        await bot.db.drivers.update_one({"_id": f"{self.guild_id}_{self.user_id}"}, {"$unset": {"defense_review_pending": ""}})
        await interaction.message.edit(embed=discord.Embed(title="❌ Defense Rejected", color=ASPHALT_DEFEAT_COLOR))

class ChallengeDropdown(discord.ui.Select):
    def __init__(self, options_list: list[discord.SelectOption], defender_def_data: dict):
        super().__init__(placeholder="Select your target opponent...", options=options_list)
        self.defender_def_data = defender_def_data
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        target_user_id = str(self.values[0])
        opp_data = self.defender_def_data[target_user_id]
        embed = discord.Embed(title="⚔️ GAUNTLET GHOST LOBBY RECRUITED", description="Best-of-5 match dashboard asset engaged.", color=0xFF3366)
        for i, c in enumerate(opp_data["courses"]):
            embed.add_field(name=f"🏁 Course {i+1}", value=f"📍 `{c['track']}`\n⏱️ `{c['lap_time']}`")
        await interaction.followup.send(embed=embed, view=LobbyUIButtons(str(interaction.user.id), target_user_id, opp_data["courses"], opp_data.get("proof_url")))

class ChallengeView(discord.ui.View):
    def __init__(self, options_list: list[discord.SelectOption], defender_def_data: dict):
        super().__init__(timeout=60)
        self.add_item(ChallengeDropdown(options_list, defender_def_data))

async def track_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return [app_commands.Choice(name=track, value=track) for track in ALU_TRACKS if current.lower() in track.lower()][:25]

# --- COMMAND ARRAYS ---

@bot.tree.command(name="register", description="Join or update your seasonal profile registry parameters.")
@app_commands.describe(game_id="Asphalt Player ID string", garage_pi="Garage Performance Index numerical rating", proof_screenshot="Attachment sheet")
async def register_cmd(interaction: discord.Interaction, game_id: str, garage_pi: int, proof_screenshot: discord.Attachment):
    if not await enforce_channel_constraints(interaction, admin_cmd=False): return
    await interaction.response.defer(ephemeral=True)
    cfg = await bot.db.settings.find_one({"_id": str(interaction.guild_id)})
    if not cfg or not cfg.get("review_channel_id"): return

    pending_exist = await bot.db.pending.find_one({"_id": f"{interaction.guild_id}_{interaction.user.id}"})
    if pending_exist:
        await interaction.followup.send("⚠️ You already have a pending registration profile updating system pipelines.", ephemeral=True)
        return

    review_chan = bot.get_channel(int(cfg["review_channel_id"]))
    if review_chan:
        emb = discord.Embed(title="👤 New Driver Registration Application", color=ASPHALT_ADMIN_COLOR)
        emb.add_field(name="Applicant User", value=interaction.user.mention)
        emb.add_field(name="Declared Game ID", value=f"`{game_id}`")
        emb.add_field(name="Declared Garage PI", value=f"`{garage_pi:,} PI`")
        emb.set_image(url=proof_screenshot.url)
        
        await bot.db.pending.update_one(
            {"_id": f"{interaction.guild_id}_{interaction.user.id}"},
            {"$set": {"guild_id": str(interaction.guild_id), "user_id": str(interaction.user.id), "game_id": game_id, "rank": garage_pi, "control": "manual"}},
            upsert=True
        )
        await review_chan.send(embed=emb, view=VerificationView(str(interaction.user.id), str(interaction.guild_id), game_id, garage_pi, "manual"))
        await interaction.followup.send("📥 Application safely transferred to administrative review queues.", ephemeral=True)

@bot.tree.command(name="leaderboard", description="View division standings matrix lines.")
async def leaderboard_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    embed = discord.Embed(title="🏆 DIVISION LEADERBOARD", description="Select a target bracket tier down below:", color=ASPHALT_THEME_COLOR)
    embed.set_image(url=ASPHALT_MEDIA["banner_leaderboard"])
    await interaction.followup.send(embed=embed, view=LeaderboardDivisionView())

class LeaderboardDivisionView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.select(
        placeholder="Select a division to view standings...",
        custom_id="leaderboard_division_select",
        options=[discord.SelectOption(label=div["name"], value=str(i)) for i, div in enumerate(PI_DIVISIONS)]
    )
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        div = PI_DIVISIONS[int(self.values[0])]
        cursor = bot.db.drivers.find({"guild_id": str(interaction.guild_id), "garage_pi": division_mongo_query(div)}).sort("elo", -1).limit(25)
        drivers = await cursor.to_list(length=25)
        
        embed = discord.Embed(title=div["name"], color=div["color"])
        board = ""
        for r, d in enumerate(drivers):
            board += f"`#{r+1}` <@{d['user_id']}> | ID: `{d['game_id']}` — **`{d.get('elo', 1000)} ELO`** ({d.get('garage_pi', 0):,} PI)\n"
        embed.description = board if board else "*No ranked drivers verified in this bracket zone.*"
        await interaction.followup.send(embed=embed)

@bot.tree.command(name="profile", description="Inspect driver dossier profiles.")
async def profile_cmd(interaction: discord.Interaction, driver: discord.Member = None):
    if not await enforce_channel_constraints(interaction, admin_cmd=False): return
    await interaction.response.defer()
    target_user = driver or interaction.user
    profile = await bot.db.drivers.find_one({"_id": f"{interaction.guild_id}_{target_user.id}"})
    if not profile:
        await interaction.followup.send("❌ Target user ledger records missing.")
        return

    embed = discord.Embed(title="🏁 ALU GAUNTLET DRIVER DOSSIER CARD", color=ASPHALT_THEME_COLOR)
    stats_matrix = f"• **ELO:** `{profile.get('elo', 1000)}`\n• **PI Group:** `{profile.get('garage_pi', 0):,} PI`\n• **Wins:** `{profile.get('career_wins', 0)}`\n• **Played:** `{profile.get('career_played', 0)}`"
    embed.add_field(name="👤 Credentials", value=target_user.mention)
    embed.add_field(name="📊 Statistics", value=stats_matrix, inline=False)
    
    if has_5_course_defense(profile):
        def_lines = "".join([f"🏁 `{c['track']}` | 🚗 `{c['car']}` | ⏱️ `{c['lap_time']}`\n" for c in profile["defense_locked"]["courses"]])
        embed.add_field(name="🛡️ Deployed Ghost Defense Framework", value=def_lines, inline=False)
    else:
        embed.add_field(name="🛡️ Deployed Ghost Defense Framework", value="⚠️ *No locked defense active this season. Run `/setdefense` to generate tracks.*", inline=False)
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="setdefense", description="🛡️ Generates 5 random seasonal verification tracks.")
async def set_defense_cmd(interaction: discord.Interaction):
    if not await enforce_channel_constraints(interaction, admin_cmd=False): return
    await interaction.response.defer(ephemeral=True)
    profile = await bot.db.drivers.find_one({"_id": f"{interaction.guild_id}_{interaction.user.id}"})
    if not profile: return

    if profile.get("needs_re_registration"):
        await interaction.followup.send("❌ **Seasonal Calibration Required:** You must update your garage parameters with `/register` before locking defenses.", ephemeral=True)
        return

    if has_5_course_defense(profile):
        await interaction.followup.send("ℹ️ Current configuration locked. Use `/changedefense` to request rolling parameters.", ephemeral=True)
        return
        
    tracks = random.sample(ALU_TRACKS, 5)
    await bot.db.drivers.update_one({"_id": profile["_id"]}, {"$set": {"pending_tracks": tracks, "pending_is_change": False}})
    await interaction.followup.send(f"🛡️ **Dynamic Track Group Staged:**\n" + "\n".join([f"{i+1}. {t}" for i, t in enumerate(tracks)]), ephemeral=True)

@bot.tree.command(name="submitdefense", description="🛡️ Submit times and matching screenshot files.")
async def submit_defense_cmd(interaction: discord.Interaction, lap_1: str, lap_2: str, lap_3: str, lap_4: str, lap_5: str, car_1: str, car_2: str, car_3: str, car_4: str, car_5: str, p_1: discord.Attachment, p_2: discord.Attachment, p_3: discord.Attachment, p_4: discord.Attachment, p_5: discord.Attachment):
    if not await enforce_channel_constraints(interaction, admin_cmd=False): return
    await interaction.response.defer(ephemeral=True)
    profile = await bot.db.drivers.find_one({"_id": f"{interaction.guild_id}_{interaction.user.id}"})
    if not profile or not profile.get("pending_tracks"): return

    laps = [lap_1, lap_2, lap_3, lap_4, lap_5]
    cars = [car_1, car_2, car_3, car_4, car_5]
    attachments = [p_1, p_2, p_3, p_4, p_5]
    courses = []
    
    for i in range(5):
        ms = parse_lap_time(laps[i])
        courses.append({"track": profile["pending_tracks"][i], "car": cars[i], "lap_time": laps[i], "ms": ms, "proof_url": attachments[i].url})

    cfg = await bot.db.settings.find_one({"_id": str(interaction.guild_id)})
    chan = bot.get_channel(int(cfg["review_channel_id"])) if cfg else None
    if chan:
        emb = discord.Embed(title="🛡️ New Gauntlet Defense Placement Verification", description=f"Verification packets logged for <@{interaction.user.id}>.")
        await chan.send(embed=emb, view=DefenseView(str(interaction.user.id), str(interaction.guild_id), courses, attachments[0].url))
        await interaction.followup.send("📥 Defense assets uploaded to audit verification pipelines safely.", ephemeral=True)

@bot.tree.command(name="challenge", description="Matchmake against tier ghosts.")
async def challenge_cmd(interaction: discord.Interaction):
    if not await enforce_channel_constraints(interaction, admin_cmd=False): return
    await interaction.response.defer()
    prof = await bot.db.drivers.find_one({"_id": f"{interaction.guild_id}_{interaction.user.id}"})
    if not has_5_course_defense(prof):
        await interaction.followup.send("❌ Complete your own defensive configuration profile matrices before challenging others.")
        return

    div_q = division_mongo_query(get_division_for_pi(prof["garage_pi"]))
    cursor = bot.db.drivers.find({"guild_id": str(interaction.guild_id), "user_id": {"$ne": str(interaction.user.id)}, "garage_pi": div_q, "defense_locked.courses.4": {"$exists": True}}).limit(5)
    candidates = await cursor.to_list(length=5)
    if not candidates:
        await interaction.followup.send("⚠️ No qualified tier opponents found holding active defenses.")
        return

    opts = [discord.SelectOption(label=f"{c['game_id']} ({c.get('elo',1000)} ELO)", value=c["user_id"]) for c in candidates]
    d_map = {c["user_id"]: {"courses": c["defense_locked"]["courses"], "proof_url": c["defense_locked"].get("proof_url")} for c in candidates}
    await interaction.followup.send(content="🚦 Matchmaking target frames established.", view=ChallengeView(opts, d_map))

# --- ADMINISTRATIVE LOGGING OVERRIDES & UTILITIES ---

@bot.tree.command(name="admin_removeracer", description="[Staff Only] Delete a driver complete profile configuration entry.")
async def admin_removeracer_cmd(interaction: discord.Interaction, racer: discord.User):
    if not await check_admin_privileges(interaction): return
    await interaction.response.defer(ephemeral=True)
    res = await bot.db.drivers.delete_one({"_id": f"{interaction.guild_id}_{racer.id}"})
    await interaction.followup.send(f"🧹 Purge sequence complete. Records tracking removed: `{res.deleted_count}`", ephemeral=True)
    await dispatch_audit_log(interaction.guild_id, "🧹 Administrative Deletion", f"Staff action invoked by {interaction.user.mention}: Driver configuration records tracking <@{racer.id}> were deleted safely from DB targets.", color=ASPHALT_ADMIN_COLOR)

@bot.tree.command(name="pending", description="[Staff Only] Inspect outstanding registry files tracking inside unverified queues.")
async def pending_cmd(interaction: discord.Interaction):
    if not await check_admin_privileges(interaction): return
    await interaction.response.defer(ephemeral=True)
    cursor = bot.db.pending.find({"guild_id": str(interaction.guild_id)})
    items = await cursor.to_list(length=100)
    if not items:
        await interaction.followup.send("✅ Registry configuration clean. Zero files pending inside validation queues.", ephemeral=True)
        return
    emb = discord.Embed(title="📋 Outstanding Registration Verification Queue", color=ASPHALT_ADMIN_COLOR)
    lines = "".join([f"• User: <@{i['user_id']}> | ID: `{i['game_id']}` | Strength: `{i['rank']:,} PI` \n" for i in items])
    emb.description = lines
    await interaction.followup.send(embed=emb, ephemeral=True)
    await dispatch_audit_log(interaction.guild_id, "🔍 Queue Inspection Run", f"Staff context user {interaction.user.mention} inspected verification queue logs.", color=ASPHALT_ADMIN_COLOR)

@bot.tree.command(name="listplayers", description="[Staff Only] Tabular ledger report showing every verified driver status ranking.")
async def list_players_cmd(interaction: discord.Interaction):
    if not await check_admin_privileges(interaction): return
    await interaction.response.defer(ephemeral=True)
    cursor = bot.db.drivers.find({"guild_id": str(interaction.guild_id)}).sort("elo", -1)
    drivers = await cursor.to_list(length=1000)
    if not drivers:
        await interaction.followup.send("❌ Structural system data empty.", ephemeral=True)
        return

    emb = discord.Embed(title="📊 Verified Gauntlet Circuit Registration Ledger", color=ASPHALT_ADMIN_COLOR)
    text = ""
    for d in drivers:
        div = get_division_for_pi(d.get("garage_pi", 0))
        text += f"• <@{d['user_id']}> | `{d['game_id']}` — **{d.get('elo', 1000)} ELO** | `{div['name']}`\n"
    emb.description = text
    await interaction.followup.send(embed=emb, ephemeral=True)
    await dispatch_audit_log(interaction.guild_id, "📊 Ledger Summary Pulled", f"Staff context panel run by {interaction.user.mention} extracted all ledger entries mapping records.", color=ASPHALT_ADMIN_COLOR)

# --- TIME TRIAL & TRACK REFERENCE UTILITIES ---

@bot.tree.command(name="best_times", description="Inspect verified time trial ghost data across database indices.")
@app_commands.autocomplete(track=track_autocomplete)
async def best_times_cmd(interaction: discord.Interaction, track: str):
    await interaction.response.defer()
    cursor = bot.db.universal_bests.find({"guild_id": str(interaction.guild_id), "track": track}).sort("ms", 1).limit(10)
    records = await cursor.to_list(length=10)
    if not records:
        await interaction.followup.send("ℹ️ No historical lap times logged on this course layout yet.")
        return
    emb = discord.Embed(title=f"⏱️ Universal Lap Records — {track}", color=ASPHALT_THEME_COLOR)
    lines = ""
    for r, rec in enumerate(records):
        lines += f"`#{r+1}` <@{rec['user_id']}> — **`{rec['lap_time']}`** using `{rec.get('car','Unknown')}`\n"
    emb.description = lines
    await interaction.followup.send(embed=emb)

@bot.tree.command(name="reference", description="Display verified course record details and performance streaming loops.")
@app_commands.autocomplete(track=track_autocomplete)
async def reference_cmd(interaction: discord.Interaction, track: str):
    await interaction.response.defer()
    rec = await bot.db.map_references.find_one({"guild_id": str(interaction.guild_id), "track": track})
    if not rec:
        await interaction.followup.send("ℹ️ No verified video reference tracking recorded for this course layer yet.")
        return
    emb = discord.Embed(title=f"🎬 Track Reference Map: {track}", color=ASPHALT_THEME_COLOR)
    emb.description = f"• **Target Ghost Pace:** `{rec['lap_time']}`\n• **Pilot Origin Source:** <@{rec['user_id']}>\n\n🔗 **Streaming Reference Loop Video:** [Watch Lap Video]({rec['video_url']})"
    await interaction.followup.send(embed=emb)

@bot.tree.command(name="add_reference", description="Submit reference track update files to management panels for approval verification.")
@app_commands.autocomplete(track=track_autocomplete)
async def add_reference_cmd(interaction: discord.Interaction, track: str, lap_time: str, video_url: str):
    await interaction.response.defer(ephemeral=True)
    if not video_url.lower().startswith(("http://", "https://")): return
    cfg = await bot.db.settings.find_one({"_id": str(interaction.guild_id)})
    review_chan = bot.get_channel(int(cfg["review_channel_id"])) if cfg else None
    if not review_chan: return

    emb = discord.Embed(title="🎬 Reference Track Update Request Logging", color=ASPHALT_ALERT_COLOR)
    emb.description = f"Driver <@{interaction.user.id}> submitted a performance reference update:\n• Course: `{track}`\n• Lap Time: `{lap_time}`\n\n🔗 Link: {video_url}"
    await review_chan.send(embed=emb, view=ReferenceApprovalView(track, lap_time, video_url, str(interaction.user.id), str(interaction.guild_id)))
    await interaction.followup.send("✅ Submission pushed to validation pipelines successfully.", ephemeral=True)

# --- BOOTSTRAP STUBS INHERITED ---

@bot.tree.command(name="setup", description="[Admin Only] Configures league core channel streams.")
async def setup_cmd(interaction: discord.Interaction, main_channel: discord.TextChannel, staff_channel: discord.TextChannel, log_channel: discord.TextChannel, announcement_channel: discord.TextChannel, match_results_channel: discord.TextChannel, admin_role: discord.Role, player_role: discord.Role):
    if not interaction.user.guild_permissions.administrator and not await check_admin_privileges(interaction): return
    await interaction.response.defer(ephemeral=True)
    await bot.db.settings.update_one({"_id": str(interaction.guild_id)}, {"$set": {"registration_channel_id": str(main_channel.id), "review_channel_id": str(staff_channel.id), "log_channel_id": str(log_channel.id), "announcement_channel_id": str(announcement_channel.id), "match_results_channel_id": str(match_results_channel.id), "admin_role_id": str(admin_role.id), "player_role_id": str(player_role.id)}}, upsert=True)
    await interaction.followup.send("⚙️ Settings saved successfully.", ephemeral=True)

@bot.tree.command(name="seasonend", description="[Staff Only] Force-closes the season runtime.")
async def season_end_cmd(interaction: discord.Interaction):
    if not await check_admin_privileges(interaction): return
    await interaction.response.defer(ephemeral=True)
    await trigger_global_season_end(forced_interaction=interaction)

class TopLeaderboardView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

@bot.tree.command(name="sync", description="[Admin Only] Synchronize configuration options.")
async def sync_cmd(interaction: discord.Interaction):
    if not await check_admin_privileges(interaction): return
    await interaction.response.defer(ephemeral=True)
    await bot.tree.sync()
    await interaction.followup.send("🔄 Commands synced globally.", ephemeral=True)

if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if token: bot.run(token)
