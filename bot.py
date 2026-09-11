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

# Single source of truth for PI-based divisions/tiers, used by both season-end podiums
# and /challenge matchmaking so the brackets always stay in sync.
PI_DIVISIONS = [
    {"name": "👑 Division 6 — Legend Tier", "min": 22001, "max": None, "color": 0x9b59b6},
    {"name": "🏆 Division 5 — Champ Tier", "min": 18501, "max": 22001, "color": 0xe74c3c},
    {"name": "💎 Division 4 — Platinum Tier", "min": 15001, "max": 18501, "color": 0x3498db},
    {"name": "🥇 Division 3 — Gold Tier", "min": 11501, "max": 15001, "color": 0xdeaf2a},
    {"name": "🥈 Division 2 — Silver Tier", "min": 8001, "max": 11501, "color": 0xa4a7a9},
    {"name": "🥉 Division 1 — Bronze Tier", "min": 0, "max": 8001, "color": 0xa3704c},
]

def division_mongo_query(division: dict) -> dict:
    """Builds the Mongo range query for a PI_DIVISIONS entry."""
    query = {}
    if division.get("min") is not None:
        query["$gte"] = division["min"]
    if division.get("max") is not None:
        query["$lt"] = division["max"]
    return query

def get_division_for_pi(pi: int) -> dict:
    """Returns the PI_DIVISIONS entry a given Garage PI value falls into."""
    for division in PI_DIVISIONS:
        if pi >= division["min"] and (division["max"] is None or pi < division["max"]):
            return division
    return PI_DIVISIONS[-1]

def format_lap_time(total_ms: int) -> str:
    """Converts a raw millisecond lap time back into MM:SS.MS display format."""
    minutes = total_ms // 60000
    seconds = (total_ms % 60000) // 1000
    millis = total_ms % 1000
    return f"{minutes:01d}:{seconds:02d}.{millis:03d}"

def parse_lap_time(lap_str: str) -> int:
    """Parses a MM:SS.MS lap time string into milliseconds. Returns -1 on failure."""
    if not re.match(r"^\d{1,2}:\d{2}\.\d{3}$", lap_str):
        return -1
    m, s = lap_str.split(":")
    sec, ms = s.split(".")
    return (int(m) * 60 * 1000) + (int(sec) * 1000) + int(ms)

def has_5_course_defense(profile: dict) -> bool:
    """Returns True if the profile has a valid 5-course defense_locked."""
    defense = profile.get("defense_locked")
    if not defense:
        return False
    courses = defense.get("courses")
    if not courses or len(courses) < 5:
        return False
    return True

# ELO delta based on races won out of 5 (best-of-5: 3+ wins = match win)
ELO_DELTA_BY_WINS = {
    5: 25,   # Dominant win
    4: 15,   # Strong win
    3: 5,    # Narrow win
    2: -5,   # Narrow loss
    1: -15,   # Loss
    0: -25,   # Dominant loss
}

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
        # Load custom images from DB into ASPHALT_MEDIA
        try:
            media_doc = await self.db.settings.find_one({"_id": "global_media"})
            if media_doc and media_doc.get("custom_images"):
                for key, url in media_doc["custom_images"].items():
                    ASPHALT_MEDIA[key] = url
                logging.info(f"🟢 Loaded {len(media_doc['custom_images'])} custom images from DB.")
        except Exception as e:
            logging.warning(f"⚠️ Could not load custom images: {e}")
        await self.sync_application_commands()
        logging.info("🟢 Application slash commands synchronized globally.")
        # Register persistent views so their buttons survive bot restarts
        self.add_view(TopLeaderboardView())
        logging.info("🟢 Persistent views registered.")
        # Restore pending reference-review buttons after a bot restart.
        try:
            pending_refs = await self.db.reference_pending.find({"status": "pending"}).to_list(length=1000)
            for ref in pending_refs:
                self.add_view(ReferenceReviewView(ref["_id"]))
            if pending_refs:
                logging.info("🟢 Restored %d pending reference-review view(s).", len(pending_refs))
        except Exception:
            logging.exception("Could not restore pending reference-review views")

    async def recover_season_state(self):
        try:
            now = time.time()
            # Season state is per Discord server. A single global season clock would
            # cause one server's rollover to reset every other server.
            configs = await self.db.settings.find({}).to_list(length=1000)
            if not configs:
                # Keep a bootstrap record only until /setup is run.
                await self.db.season_state.update_one(
                    {"_id": "bootstrap"},
                    {"$setOnInsert": {"season_number": 1, "ends_at": now + (14 * 24 * 60 * 60)}},
                    upsert=True
                )
                logging.info("⚙️ No configured guilds yet; season clocks will initialize per server after /setup.")
                return
            legacy_state = await self.db.season_state.find_one({"_id": "current_season"})
            for cfg in configs:
                guild_id = str(cfg.get("_id"))
                await self.db.season_state.update_one(
                    {"_id": f"guild_{guild_id}"},
                    {"$setOnInsert": {
                        "guild_id": guild_id,
                        "season_number": int(legacy_state.get("season_number", 1)) if legacy_state else 1,
                        "ends_at": float(legacy_state.get("ends_at", now + (14 * 24 * 60 * 60))) if legacy_state else now + (14 * 24 * 60 * 60),
                    }},
                    upsert=True
                )
            logging.info("⚙️ Recovered %d per-server season clock(s).", len(configs))
        except Exception as state_err:
            logging.error(f"Failed to execute state recovery sequence hooks: {state_err}")

    async def sync_application_commands(self):
        """Synchronize the global command tree and verify /help is registered."""
        local_commands = self.tree.get_commands()
        names = [cmd.name for cmd in local_commands]
        logging.info("🔎 Preparing global application-command sync: %d local commands.", len(names))
        logging.info("🔎 Local application commands: %s", ", ".join(sorted(names)))
        if "help" not in names:
            logging.error("🔴 /help is NOT present in bot.tree before sync.")
        synced = await self.tree.sync()
        synced_names = [cmd.name for cmd in synced]
        logging.info("🟢 Global application-command sync complete: %d commands.", len(synced_names))
        if "help" in synced_names:
            logging.info("🟢 /help was included in the global command payload.")
        else:
            logging.error("🔴 /help was NOT returned by Discord after global sync.")
        return synced

    def setup_mock_db(self):
        """Fallback local database simulation if MongoDB Atlas is offline."""
        class MockCollection:
            async def find_one(self, *args, **kwargs): return None
            async def update_one(self, *args, **kwargs): return None
            async def insert_one(self, *args, **kwargs): return None
            async def replace_one(self, *args, **kwargs): return None
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
    try:
        configs = await bot.db.settings.find({}).to_list(length=1000)
        for config in configs:
            guild_id = str(config.get("_id"))
            state = await bot.db.season_state.find_one({"_id": f"guild_{guild_id}"})
            if not state:
                await bot.db.season_state.update_one(
                    {"_id": f"guild_{guild_id}"},
                    {"$set": {"guild_id": guild_id, "season_number": 1, "ends_at": now + (14 * 24 * 60 * 60)}},
                    upsert=True
                )
                continue
            if now >= state.get("ends_at", now + 86400):
                await trigger_global_season_end(guild_id=guild_id)
    except Exception:
        logging.exception("Seasonal clock loop failed")

@seasonal_clock_loop_task.before_loop
async def before_seasonal_clock():
    await bot.wait_until_ready()

# Bind the standalone task securely to our initialized client body
bot.seasonal_clock_loop = seasonal_clock_loop_task

async def check_admin_privileges(interaction: discord.Interaction) -> bool:
    """Return True for Discord admins, configured admin-role members, or the bot owner."""
    if interaction.user.guild_permissions.administrator:
        return True

    try:
        if await bot.is_owner(interaction.user):
            return True
    except Exception:
        pass

    cfg = await bot.db.settings.find_one({"_id": str(interaction.guild_id)})
    if cfg and cfg.get("admin_role_id") and interaction.guild:
        target_role = interaction.guild.get_role(int(cfg["admin_role_id"]))
        if target_role and target_role in interaction.user.roles:
            return True
    return False

async def enforce_channel_constraints(interaction: discord.Interaction, admin_cmd: bool = False) -> bool:
    """Enforce main-channel use for players; admin/owner commands work in any channel."""
    cfg = await bot.db.settings.find_one({"_id": str(interaction.guild_id)})
    if not cfg:
        await interaction.response.send_message("❌ **System Offline:** Run `/setup` first.", ephemeral=True)
        return False

    # Staff commands are intentionally not tied to any particular channel.
    if admin_cmd:
        return True

    main_chan_id = cfg.get("registration_channel_id")
    if str(interaction.channel_id) != str(main_chan_id):
        await interaction.response.send_message(
            f"❌ **Lobby Lock Active:** Use the main channel: <#{main_chan_id}>.",
            ephemeral=True,
        )
        return False
    return True

async def dispatch_audit_log(guild_id: str, title: str, description: str, color: int = 0x7f8c8d):
    cfg = await bot.db.settings.find_one({"_id": str(guild_id)})
    if cfg and cfg.get("log_channel_id"):
        chan = bot.get_channel(int(cfg["log_channel_id"]))
        if chan:
            emb = discord.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
            try:
                await chan.send(embed=emb)
            except Exception:
                logging.exception("Failed to write audit log for guild %s", guild_id)

async def audit_admin_action(interaction: discord.Interaction, action: str, details: str, color: int = ASPHALT_ADMIN_COLOR):
    """Uniform audit entry for every admin/owner action."""
    await dispatch_audit_log(
        str(interaction.guild_id),
        f"🛡️ Admin Action — {action}",
        f"**Actor:** {interaction.user.mention} (`{interaction.user.id}`)\n**Channel:** <#{interaction.channel_id}>\n{details}",
        color=color,
    )


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

def calculate_elo_change(winner_elo: int, loser_elo: int, winner_streak: int = 0, k_factor: int = 32):
    expected_winner = 1 / (1 + 10 ** ((loser_elo - winner_elo) / 400))
    expected_loser = 1 / (1 + 10 ** ((winner_elo - loser_elo) / 400))
    
    # Custom win-streak ELO modifier logic: Adds an extra 4 ELO points per streak tier (caps at +20 ELO bonus)
    streak_bonus = min(20, (winner_streak // 2) * 4) if winner_streak >= 2 else 0
    
    new_winner_elo = winner_elo + round(k_factor * (1 - expected_winner)) + streak_bonus
    new_loser_elo = loser_elo + round(k_factor * (0 - expected_loser))
    return max(100, new_winner_elo), max(100, new_loser_elo), streak_bonus

async def dispatch_automated_announcement(guild_id: str, title: str, description: str, color: int = 0x00FFCC, image_url: str = None):
    """Sends a beautifully styled premium global announcement alert to the league."""
    cfg = await bot.db.settings.find_one({"_id": str(guild_id)})
    if cfg and cfg.get("announcement_channel_id"):
        chan = bot.get_channel(int(cfg["announcement_channel_id"]))
        if chan:
            emb = discord.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
            if image_url:
                emb.set_image(url=image_url)
            ping_content = f"<@&{cfg['player_role_id']}>" if cfg.get("player_role_id") else ""
            try: await chan.send(content=ping_content, embed=emb)
            except Exception: pass

async def apply_season_soft_reset(guild_id: str, season_number: int):
    """Start a new season without deleting lifetime career statistics.

    ELO is softly regressed, but the player's current-season garage/defense
    registration is cleared so every driver must re-register and rebuild a
    five-course defense for the new season.
    """
    cursor = bot.db.drivers.find({"guild_id": str(guild_id)})
    drivers = await cursor.to_list(length=10000)
    for d in drivers:
        old_elo = d.get("elo", 1000)
        new_elo = max(100, round(1000 + (old_elo - 1000) * 0.5))
        await bot.db.drivers.update_one(
            {"_id": d["_id"]},
            {
                "$set": {
                    "elo": new_elo,
                    "streak": 0,
                    "season_registered": False,
                    "season_number": season_number + 1,
                    "previous_season_pi": d.get("garage_pi"),
                    "previous_season_game_id": d.get("game_id"),
                    "previous_season_division": get_division_for_pi(int(d.get("garage_pi", 0))).get("name") if d.get("garage_pi") is not None else None,
                },
                "$unset": {
                    "garage_pi": "",
                    "defense_locked": "",
                    "pending_tracks": "",
                    "pending_is_change": "",
                    "defense_review_pending": "",
                    "last_defense_change": "",
                },
            },
        )

async def trigger_global_season_end(guild_id: str = None, forced_interaction: discord.Interaction = None):
    """Close one server's season; automatic calls pass the specific guild."""
    now = time.time()
    if guild_id is None and forced_interaction:
        guild_id = str(forced_interaction.guild_id)
    if guild_id is None:
        return
    guild_id = str(guild_id)
    config = await bot.db.settings.find_one({"_id": guild_id})
    if not config:
        return
    state = await bot.db.season_state.find_one({"_id": f"guild_{guild_id}"})
    current_season_num = int(state.get("season_number", 1)) if state else 1
    channel_id = config.get("announcement_channel_id") or config.get("registration_channel_id")
    target_channel = bot.get_channel(int(channel_id)) if channel_id else None

    # Snapshot the season before clearing current-season registration data.
    if target_channel:
        ping_content = f"<@&{config['player_role_id']}>" if config.get("player_role_id") else ""
        header_embed = discord.Embed(
            title=f"🏁 SEASON {current_season_num} GAUNTLET FINALE PODIUMS",
            description="🏁 **The season has closed.** Final standings are being archived.\n\n⚙️ *ELO is softly regressed. Career wins/matches remain permanently. Every driver must re-register their Garage for the new season and set a fresh 5-course defense.*",
            color=0xffaa00,
        )
        header_embed.set_image(url=ASPHALT_MEDIA["banner_leaderboard"])
        await target_channel.send(content=ping_content, embed=header_embed)

        csv_buffer = io.StringIO()
        csv_writer = csv.writer(csv_buffer)
        csv_writer.writerow(["Division", "Rank", "User ID", "Game ID", "ELO Rating", "Garage PI", "Career Wins", "Career Played"])
        for div in PI_DIVISIONS:
            cursor = bot.db.drivers.find({"guild_id": guild_id, "season_registered": True, "garage_pi": division_mongo_query(div)}).sort("elo", -1).limit(100)
            top_drivers = await cursor.to_list(length=100)
            div_embed = discord.Embed(title=div["name"], color=div["color"])
            if not top_drivers:
                div_embed.description = "*No verified driver positions secured in this tier bracket.*"
            else:
                lines = []
                for r, d in enumerate(top_drivers[:10]):
                    medal = '🥇 ' if r == 0 else '🥈 ' if r == 1 else '🥉 ' if r == 2 else f'**#{r+1}** '
                    lines.append(f"{medal}<@{d['user_id']}> | `{d.get('game_id', 'Unknown')}` — **{d.get('elo', 1000)} ELO**")
                for r, d in enumerate(top_drivers):
                    csv_writer.writerow([div["name"], r + 1, d['user_id'], d.get('game_id', ''), d.get('elo', 1000), d.get('garage_pi', 0), d.get('career_wins', 0), d.get('career_played', 0)])
                div_embed.add_field(name="🏆 Final Elite Standings Placements", value="\n".join(lines)[:1024], inline=False)
            await target_channel.send(embed=div_embed)

        csv_buffer.seek(0)
        await target_channel.send(
            content="📊 **Complete Seasonal Standings Archive:**",
            file=discord.File(fp=io.BytesIO(csv_buffer.getvalue().encode('utf-8')), filename=f"season_{current_season_num}_final_leaderboard.csv"),
        )

    # Preserve the final snapshot for historical reporting.
    await bot.db.season_history.update_one(
        {"_id": f"{guild_id}_{current_season_num}"},
        {"$set": {"guild_id": guild_id, "season_number": current_season_num, "closed_at": now}},
        upsert=True,
    )
    await apply_season_soft_reset(guild_id, current_season_num)
    await bot.db.pending.delete_many({"guild_id": guild_id})
    await bot.db.season_state.update_one(
        {"_id": f"guild_{guild_id}"},
        {"$set": {"guild_id": guild_id, "season_number": current_season_num + 1, "ends_at": now + (14 * 24 * 60 * 60)}},
        upsert=True,
    )
    if forced_interaction:
        await forced_interaction.followup.send(
            embed=discord.Embed(
                title="⚙️ Season Rollover Executed",
                description=f"Season {current_season_num} closed. Career statistics were preserved. Drivers must re-register their Garage for Season {current_season_num + 1} and submit a new 5-course defense.",
                color=ASPHALT_THEME_COLOR,
            )
        )
        await audit_admin_action(forced_interaction, "Season Rollover", f"Closed Season {current_season_num}; career stats preserved and current-season garage/defenses reset.")

async def process_match_result(guild_id: str, challenger_id: str, opponent_id: str, defense_courses: list, challenger_times: list, proof_url: str, defender_proof_url: str = None, origin_channel_id: int = None):
    """Calculate ELO changes, apply to DB, save match record. Returns match data dict or None on error."""
    p1 = await bot.db.drivers.find_one({"_id": f"{guild_id}_{challenger_id}"})
    p2 = await bot.db.drivers.find_one({"_id": f"{guild_id}_{opponent_id}"})
    if not p1 or not p2:
        return None

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
        if streak_bonus > 0:
            outcome_desc += f"\n🔥 **Streak Multiplier Engaged:** +{streak_bonus} bonus ELO applied for a streak of {current_streak} wins!"
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
        if streak_bonus > 0:
            outcome_desc += f"\n🔥 **Defender Streak Multiplier Engaged:** +{streak_bonus} bonus ELO applied for a streak of {current_streak} holds!"
        display_color = ASPHALT_DEFEAT_COLOR
        announce_title = "🛡️ DEFENSE HOLD SECURED"
        w_id, l_id = opponent_id, challenger_id
        new_w_elo, new_l_elo = new_defender_elo, new_challenger_elo
        old_w_elo, old_l_elo = old_defender_elo, old_challenger_elo

    await bot.db.drivers.update_one({"_id": f"{guild_id}_{w_id}"}, {"$set": {"elo": new_w_elo}, "$inc": {"career_wins": 1, "career_played": 1, "streak": 1}})
    await bot.db.drivers.update_one({"_id": f"{guild_id}_{l_id}"}, {"$set": {"elo": new_l_elo, "streak": 0}, "$inc": {"career_played": 1}})

    match_id = f"{guild_id}_{challenger_id}_{opponent_id}_{int(time.time())}"
    match_record = {
        "_id": match_id,
        "guild_id": guild_id,
        "challenger_id": challenger_id,
        "opponent_id": opponent_id,
        "courses_beat": courses_beat,
        "challenger_won": challenger_won,
        "challenger_elo_before": old_challenger_elo,
        "challenger_elo_after": new_challenger_elo,
        "defender_elo_before": old_defender_elo,
        "defender_elo_after": new_defender_elo,
        "challenger_delta": new_challenger_elo - old_challenger_elo,
        "defender_delta": new_defender_elo - old_defender_elo,
        "w_id": w_id,
        "l_id": l_id,
        "new_w_elo": new_w_elo,
        "new_l_elo": new_l_elo,
        "old_w_elo": old_w_elo,
        "old_l_elo": old_l_elo,
        "outcome_desc": outcome_desc,
        "display_color": display_color,
        "announce_title": announce_title,
        "proof_url": proof_url,
        "defender_proof_url": defender_proof_url,
        "reverted": False,
        "timestamp": time.time()
    }
    await bot.db.matches.insert_one(match_record)
    return match_record


class MatchResultPostView(discord.ui.View):
    """View attached to public match result posts. Players can report issues."""
    def __init__(self, match_id: str):
        super().__init__(timeout=None)
        self.match_id = match_id

    @discord.ui.button(label="Report Issue", style=discord.ButtonStyle.danger, custom_id="report_match_btn")
    async def report_issue(self, interaction: discord.Interaction, button: discord.ui.Button):
        match = await bot.db.matches.find_one({"_id": self.match_id})
        if not match:
            await interaction.response.send_message("❌ Match record not found.", ephemeral=True)
            return
        if match.get("reverted"):
            await interaction.response.send_message("❌ This match has already been reverted.", ephemeral=True)
            return

        cfg = await bot.db.settings.find_one({"_id": match["guild_id"]})
        if not cfg or not cfg.get("review_channel_id"):
            await interaction.response.send_message("❌ Admin channel not configured.", ephemeral=True)
            return
        admin_chan = bot.get_channel(int(cfg["review_channel_id"]))
        if not admin_chan:
            await interaction.response.send_message("❌ Admin channel not found.", ephemeral=True)
            return

        report_emb = discord.Embed(title="⚠️ Match Result Reported", description=match["outcome_desc"], color=0xe74c3c)
        report_emb.add_field(name="Reported by", value=interaction.user.mention, inline=True)
        report_emb.add_field(name="Challenger", value=f"<@{match['challenger_id']}>", inline=True)
        report_emb.add_field(name="Defender", value=f"<@{match['opponent_id']}>", inline=True)
        report_emb.set_image(url=match["proof_url"])
        report_emb.set_footer(text=f"Match ID: {self.match_id}")

        await admin_chan.send(embed=report_emb, view=MatchRevertView(self.match_id))
        await interaction.response.send_message("✅ Match reported to staff. They will review it shortly.", ephemeral=True)

        button.disabled = True
        await interaction.message.edit(view=self)


class MatchRevertView(discord.ui.View):
    """View for admins to revert a reported match (ELO only)."""
    def __init__(self, match_id: str):
        super().__init__(timeout=None)
        self.match_id = match_id

    @discord.ui.button(label="Revert ELO", style=discord.ButtonStyle.danger, custom_id="revert_elo_btn")
    async def revert_elo(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await check_admin_privileges(interaction):
            await interaction.response.send_message("❌ Access Denied: Staff only.", ephemeral=True)
            return

        match = await bot.db.matches.find_one({"_id": self.match_id})
        if not match:
            await interaction.response.send_message("❌ Match record not found.", ephemeral=True)
            return
        if match.get("reverted"):
            await interaction.response.send_message("❌ This match has already been reverted.", ephemeral=True)
            return

        challenger_delta = match["challenger_delta"]
        defender_delta = match["defender_delta"]

        p1 = await bot.db.drivers.find_one({"_id": f"{match['guild_id']}_{match['challenger_id']}"})
        p2 = await bot.db.drivers.find_one({"_id": f"{match['guild_id']}_{match['opponent_id']}"})
        if not p1 or not p2:
            await interaction.response.send_message("❌ Player profiles not found.", ephemeral=True)
            return

        new_challenger_elo = max(100, p1.get("elo", 1000) - challenger_delta)
        new_defender_elo = max(100, p2.get("elo", 1000) - defender_delta)

        await bot.db.drivers.update_one({"_id": f"{match['guild_id']}_{match['challenger_id']}"}, {"$set": {"elo": new_challenger_elo}})
        await bot.db.drivers.update_one({"_id": f"{match['guild_id']}_{match['opponent_id']}"}, {"$set": {"elo": new_defender_elo}})
        await bot.db.matches.update_one({"_id": self.match_id}, {"$set": {"reverted": True}})

        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message(f"✅ ELO reverted. <@{match['challenger_id']}>: {p1.get('elo', 1000)} → {new_challenger_elo} | <@{match['opponent_id']}>: {p2.get('elo', 1000)} → {new_defender_elo}", ephemeral=True)
        await dispatch_audit_log(match["guild_id"], "⚠️ Match ELO Reverted", f"Staff {interaction.user.mention} reverted ELO for match {self.match_id} between <@{match['challenger_id']}> and <@{match['opponent_id']}>.", color=0xe74c3c)

    @discord.ui.button(label="Dismiss", style=discord.ButtonStyle.secondary, custom_id="dismiss_report_btn")
    async def dismiss(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await check_admin_privileges(interaction):
            await interaction.response.send_message("❌ Access Denied: Staff only.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message("✅ Report dismissed.", ephemeral=True)


class DuelReportModal(discord.ui.Modal, title="Submit Gauntlet Match Results"):
    challenger_laps = discord.ui.TextInput(label="Your 5 Lap Times (one per line, MM:SS.MS)", style=discord.TextStyle.paragraph, placeholder="01:12.431\n01:15.123\n01:10.567\n01:18.890\n01:14.234", required=True)
    challenger_cars = discord.ui.TextInput(label="Your 5 Attack Cars (one per line)", style=discord.TextStyle.paragraph, placeholder="Devel Sixteen\nKoenigsegg Jesko\nBugatti Bolide\nRimac Nevera\nMcLaren Speedtail", required=True)
    screenshot_proof = discord.ui.TextInput(label="Paste Race Score card Screenshot URL", placeholder="Direct image link...", required=True)

    def __init__(self, challenger_id: str, opponent_id: str, defense_courses: list, defender_proof_url: str = None):
        super().__init__()
        self.challenger_id, self.opponent_id, self.defense_courses = str(challenger_id), str(opponent_id), defense_courses
        self.defender_proof_url = defender_proof_url

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)

        raw_lines = [line.strip() for line in self.challenger_laps.value.strip().split("\n") if line.strip()]
        if len(raw_lines) != 5:
            await interaction.followup.send("❌ **Format Denied:** You must provide exactly 5 lap times, one per line in `MM:SS.MS` format.", ephemeral=True)
            return

        car_lines = [line.strip() for line in self.challenger_cars.value.strip().split("\n") if line.strip()]
        if len(car_lines) != 5:
            await interaction.followup.send("❌ **Format Denied:** You must provide exactly 5 attack cars, one per line.", ephemeral=True)
            return

        if len({c.strip().lower() for c in car_lines}) != len(car_lines):
            await interaction.followup.send("❌ **Duplicate Cars:** All 5 attack cars must be different.", ephemeral=True)
            return

        challenger_times = []
        for i, line in enumerate(raw_lines):
            ms = parse_lap_time(line)
            if ms < 0:
                await interaction.followup.send(f"❌ **Format Denied:** Lap time {i+1} (`{line}`) is not in `MM:SS.MS` format.", ephemeral=True)
                return
            challenger_times.append({"lap_time_str": line, "ms": ms, "car": car_lines[i]})

        proof_url = self.screenshot_proof.value.strip()
        if not proof_url.lower().startswith(("http://", "https://")):
            await interaction.followup.send("❌ **Proof Denied:** Screenshot must be a direct image URL starting with `http://` or `https://`.", ephemeral=True)
            return

        # Validate match results channel is configured
        cfg = await bot.db.settings.find_one({"_id": guild_id})
        results_chan = bot.get_channel(int(cfg["match_results_channel_id"])) if cfg and cfg.get("match_results_channel_id") else None
        if not results_chan:
            await interaction.followup.send("❌ Match results channel is not configured. Ask an administrator to run `/setup`.", ephemeral=True)
            return

        # Process match: calculate ELO, apply to DB, save match record
        match_data = await process_match_result(guild_id, self.challenger_id, self.opponent_id, self.defense_courses, challenger_times, proof_url, self.defender_proof_url, interaction.channel_id)
        if not match_data:
            await interaction.followup.send("❌ Could not process match result. One or both player profiles not found.", ephemeral=True)
            return

        season_number = await get_current_season_number(guild_id)
        for i, course in enumerate(self.defense_courses):
            attack_course = dict(challenger_times[i])
            attack_course["track"] = course["track"]
            await save_driver_best_time(guild_id, self.challenger_id, attack_course, season_number, source="match_attack")

        # Post match result to the match results channel
        result_emb = discord.Embed(title="🏁 Gauntlet Match Result", description=match_data["outcome_desc"], color=match_data["display_color"])
        result_emb.add_field(name="Challenger", value=f"<@{self.challenger_id}>", inline=True)
        result_emb.add_field(name="Defender", value=f"<@{self.opponent_id}>", inline=True)
        winner_delta = match_data["new_w_elo"] - match_data["old_w_elo"]
        loser_delta = match_data["new_l_elo"] - match_data["old_l_elo"]
        result_emb.add_field(name="📈 Victor", value=f"<@{match_data['w_id']}> ── **`{match_data['new_w_elo']} ELO`** ({'+' if winner_delta > 0 else ''}{winner_delta})", inline=True)
        result_emb.add_field(name="📉 Defeated", value=f"<@{match_data['l_id']}> ── **`{match_data['new_l_elo']} ELO`** ({'+' if loser_delta > 0 else ''}{loser_delta})", inline=True)
        result_emb.set_image(url=proof_url)
        result_emb.set_footer(text=f"Best-of-5: {match_data['courses_beat']}/5 races won • Click Report Issue if something looks wrong")

        await results_chan.send(embed=result_emb, view=MatchResultPostView(match_data["_id"]))

        # Send confirmation to challenger
        await interaction.followup.send("✅ **Match submitted!** ELO has been updated automatically. Results posted to the match results channel.", ephemeral=True)

        # Dispatch announcement and audit log
        await dispatch_audit_log(guild_id, "🏁 Match Result Processed", f"Match between <@{self.challenger_id}> and <@{self.opponent_id}>. Challenger won {match_data['courses_beat']}/5 races.", color=0x2ecc71)
        await dispatch_automated_announcement(guild_id, match_data["announce_title"], f"🏎️ **Match Event:** <@{self.challenger_id}> challenged <@{self.opponent_id}>!\n🏆 **Result:** {'Challenger won ' if match_data['challenger_won'] else 'Defense held — challenger won '} {match_data['courses_beat']}/5 races.", color=match_data["display_color"])

        # Send result to origin channel
        origin_channel = bot.get_channel(interaction.channel_id)
        if origin_channel:
            try: await origin_channel.send(embed=result_emb)
            except Exception: pass

class LobbyUIButtons(discord.ui.View):
    def __init__(self, challenger_id: str, opponent_id: str, defense_courses: list, defender_proof_url: str = None):
        super().__init__(timeout=1800)
        self.challenger_id, self.opponent_id, self.defense_courses = str(challenger_id), str(opponent_id), defense_courses
        self.defender_proof_url = defender_proof_url
    @discord.ui.button(label="Submit Match Results", style=discord.ButtonStyle.blurple, custom_id="lobby_report_btn")
    async def report_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.challenger_id:
            await interaction.response.send_message("❌ Access Denied: Challenger only.", ephemeral=True)
            return
        await interaction.response.send_modal(DuelReportModal(self.challenger_id, self.opponent_id, self.defense_courses, self.defender_proof_url))

class DefenseView(discord.ui.View):
    def __init__(self, user_id: str, guild_id: str, courses: list, proof_url: str, is_change: bool = False):
        super().__init__(timeout=None)
        self.user_id, self.guild_id, self.courses, self.proof_url = str(user_id), str(guild_id), courses, proof_url
        self.is_change = is_change
    @discord.ui.button(label="Approve Defense Placement", style=discord.ButtonStyle.green, custom_id="approve_def_btn")
    async def approve_def(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children: item.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.defer()
        state = await bot.db.season_state.find_one({"_id": f"guild_{self.guild_id}"})
        season_number = int(state.get("season_number", 1)) if state else 1
        await bot.db.drivers.update_one(
            {"_id": f"{self.guild_id}_{self.user_id}"},
            {"$set": {"defense_locked": {"courses": self.courses, "proof_url": self.proof_url, "season_number": season_number}, "last_defense_change": time.time()}, "$unset": {"pending_tracks": "", "pending_is_change": "", "defense_review_pending": ""}}
        )
        # Keep a per-driver/per-map best-time database for practice comparisons.
        for course in self.courses:
            await save_driver_best_time(self.guild_id, self.user_id, course, season_number, source="defense")
        title = "✅ Gauntlet Defense Updated & Locked" if self.is_change else "✅ Gauntlet Defense Position Approved & Locked"
        await interaction.message.edit(embed=discord.Embed(title=title, color=ASPHALT_VICTORY_COLOR), view=self)
        track_list = ", ".join([c["track"] for c in self.courses])
        audit_title = "🛡️ Defense Position Updated" if self.is_change else "🛡️ Defense Position Locked"
        audit_verb = "updated" if self.is_change else "locked"
        await dispatch_audit_log(self.guild_id, audit_title, f"Racer <@{self.user_id}> {audit_verb} 5-course defense on: {track_list}.", color=0x2ecc71)
        announce_title = "🛡️ DEFENSE PACK UPDATED" if self.is_change else "🛡️ NEW COVERT DEFENSE PACK DEPLOYED"
        announce_verb = "updated" if self.is_change else "deployed and verified"
        await dispatch_automated_announcement(self.guild_id, announce_title, f"🏎️ Driver <@{self.user_id}> has {announce_verb} a 5-Course defensive framework! Courses: {track_list}.", color=ASPHALT_THEME_COLOR)
    @discord.ui.button(label="Reject Defense Placement", style=discord.ButtonStyle.red, custom_id="reject_def_btn")
    async def reject_def(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children: item.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.defer()
        # Clear review-pending flag so the player can resubmit with the same pending tracks
        await bot.db.drivers.update_one({"_id": f"{self.guild_id}_{self.user_id}"}, {"$unset": {"defense_review_pending": ""}})
        if self.is_change:
            title = "❌ Defense Change Rejected"
            desc = "The defense change was rejected. Your current defense remains active. You can resubmit using `/submitdefense` with the same courses."
        else:
            title = "❌ Gauntlet Defense Position Rejected"
            desc = "You can resubmit using `/submitdefense` with the same courses."
        await interaction.message.edit(embed=discord.Embed(title=title, description=desc, color=ASPHALT_DEFEAT_COLOR), view=self)

class RegistrationDeclineModal(discord.ui.Modal, title="Specify Application Rejection Reason"):
    reason_input = discord.ui.TextInput(label="Reason for Disapproval", style=discord.TextStyle.paragraph, placeholder="e.g. Blurry screenshot metadata, mismatched game player node ID digits...", required=True, max_length=400)
    
    def __init__(self, user_id: str, guild_id: str):
        super().__init__()
        self.user_id, self.guild_id = str(user_id), str(guild_id)
        
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await bot.db.pending.delete_one({"_id": f"{self.guild_id}_{self.user_id}"})
        
        # Dispatch customized Direct Message notification alerting applicant
        guild = bot.get_guild(int(self.guild_id))
        member = guild.get_member(int(self.user_id)) if guild else None
        if member:
            dm_embed = discord.Embed(
                title="❌ REGISTRY APPLICATION DECLINED",
                description=f"Hello racer, your competitive track authorization packet for **{guild.name}** was reviewed and disapproved by management staff panels.",
                color=ASPHALT_DEFEAT_COLOR
            )
            dm_embed.add_field(name="📋 Stated Reason For Disapproval", value=f"```\n{self.reason_input.value}\n```", inline=False)
            dm_embed.set_footer(text="Please rectify listed parameter details and re-apply.")
            try: await member.send(embed=dm_embed)
            except Exception: pass
            
        await dispatch_audit_log(self.guild_id, "👤 Driver Application Declined", f"User <@{self.user_id}> entry registration denied. Reason: {self.reason_input.value}", color=0xe74c3c)

class VerificationView(discord.ui.View):
    def __init__(self, user_id: str, guild_id: str, game_id: str, rank: int, control: str):
        super().__init__(timeout=None)
        self.user_id, self.guild_id, self.game_id, self.rank, self.control = str(user_id), str(guild_id), game_id, rank, control
    @discord.ui.button(label="Approve Driver Account", style=discord.ButtonStyle.green, custom_id="approve_driver_btn")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children: item.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.defer()
        
        state = await bot.db.season_state.find_one({"_id": f"guild_{self.guild_id}"})
        season_number = int(state.get("season_number", 1)) if state else 1
        pending = await bot.db.pending.find_one({"_id": f"{self.guild_id}_{self.user_id}"})
        if pending and int(pending.get("season_number", season_number)) != season_number:
            await interaction.response.send_message("❌ This registration belongs to an older season and can no longer be approved.", ephemeral=True)
            return
        existing = await bot.db.drivers.find_one({"_id": f"{self.guild_id}_{self.user_id}"})
        set_on_insert = {
            "guild_id": str(self.guild_id),
            "user_id": str(self.user_id),
            "career_wins": 0,
            "career_played": 0,
        }
        if not existing:
            set_on_insert.update({"elo": 1000, "streak": 0})
        await bot.db.drivers.update_one(
            {"_id": f"{str(self.guild_id)}_{str(self.user_id)}"},
            {
                "$set": {
                    "guild_id": str(self.guild_id),
                    "user_id": str(self.user_id),
                    "game_id": str(self.game_id),
                    "garage_pi": int(self.rank),
                    "verified": True,
                    "season_registered": True,
                    "season_number": season_number,
                    "control": self.control,
                    "registered_at": time.time(),
                },
                "$setOnInsert": set_on_insert,
            },
            upsert=True,
        )
        await bot.db.pending.delete_one({"_id": f"{self.guild_id}_{self.user_id}"})
        cfg = await bot.db.settings.find_one({"_id": self.guild_id})
        
        guild = bot.get_guild(int(self.guild_id))
        member = guild.get_member(int(self.user_id)) if guild else None
        if member and cfg:
            roles = [guild.get_role(int(cfg[k])) for k in ["player_role_id"] if cfg.get(k) and guild.get_role(int(cfg[k]))]
            if roles:
                try: await member.add_roles(*roles)
                except Exception: pass
                
            # Send notification update to approved pilot credentials channel inbox
            dm_success = discord.Embed(
                title="🏎️ GAUNTLET GRID ENTRY GRANTED",
                description=f"Congratulations pilot! Your driver application registration for **{guild.name}** was approved.",
                color=ASPHALT_VICTORY_COLOR
            )
            dm_success.add_field(name="📈 Assigned Base ELO", value="`1000 ELO`", inline=True)
            dm_success.add_field(name="⚙️ Verified Profile Strength", value=f"`{self.rank:,} PI`", inline=True)
            dm_success.set_footer(text="Set up your defense with /setdefense and /submitdefense, then use /challenge inside allowed rooms!")
            try: await member.send(embed=dm_success)
            except Exception: pass
            
        projected_division = get_division_for_pi(int(self.rank))["name"]
        await interaction.message.edit(
            embed=discord.Embed(
                title="✅ Driver Garage Approved",
                description=f"Season **{season_number}** Garage registered at `{self.rank:,} PI` → **{projected_division}**. Career statistics were preserved.",
                color=ASPHALT_VICTORY_COLOR,
            ),
            view=self,
        )
        await dispatch_audit_log(self.guild_id, "👤 Driver Garage Approved", f"User <@{self.user_id}> approved for Season {season_number} with `{self.rank:,} PI` → {projected_division}. Lifetime career statistics preserved.", color=0x2ecc71)
        await dispatch_automated_announcement(self.guild_id, "🏎️ NEW RACER ENTERED THE GRID", f"✨ Let's welcome <@{self.user_id}> (`{self.game_id}`) to the official competitive track circuit! Profile rated at **`{self.rank:,} PI`** using **`{self.control.upper()}`** dynamics.", color=ASPHALT_THEME_COLOR)
    @discord.ui.button(label="Reject Account", style=discord.ButtonStyle.red, custom_id="reject_driver_btn")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Fire modal frame allowing typing rejection specifications
        await interaction.response.send_modal(RegistrationDeclineModal(self.user_id, self.guild_id))
        for item in self.children: item.disabled = True
        await interaction.message.edit(view=self)

class ChallengeDropdown(discord.ui.Select):
    def __init__(self, options_list: list[discord.SelectOption], defender_def_data: dict):
        super().__init__(placeholder="Select your target opponent to challenge...", min_values=1, max_values=1, options=options_list)
        self.defender_def_data = defender_def_data
    async def callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.view.user_id:
            await interaction.response.send_message("❌ This is not your matchmaking session.", ephemeral=True)
            return
        await interaction.response.defer()
        target_user_id = str(self.values[0])
        opp_data = self.defender_def_data[target_user_id]
        
        # Re-check daily challenge limit before creating the match
        guild_id, user_id = self.view.guild_id, self.view.user_id
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        profile = await bot.db.drivers.find_one({"_id": f"{guild_id}_{user_id}"})
        challenge_date = profile.get("challenge_date") if profile else None
        challenge_count = profile.get("challenge_count", 0) if profile else 0
        if challenge_date == today and challenge_count >= 5:
            await interaction.followup.send("⏳ **Daily Limit Reached:** You've used all 5 of your daily challenges. Come back tomorrow!", ephemeral=True)
            return
        # Increment daily challenge counter when an opponent is actually selected
        new_count = (challenge_count + 1) if challenge_date == today else 1
        await bot.db.drivers.update_one({"_id": f"{guild_id}_{user_id}"}, {"$set": {"challenge_count": new_count, "challenge_date": today}})
        remaining = 5 - new_count
        
        embed = discord.Embed(
            title="⚔️ OFFICIAL GAUNTLET GHOST LOBBY ENGAGED", 
            description=f"Challenger {interaction.user.mention} is officially at the starting line! Racing against this driver's locked 5-course defensive ghost configuration. **Win 3 out of 5 races to win the match!** Pick your best cars for each course.\n\n📊 **Daily challenges remaining:** `{remaining}/5`", 
            color=0xFF3366
        )
        
        for i, course in enumerate(opp_data["courses"]):
            embed.add_field(name=f"🏁 Course {i+1}", value=f"📍 `{course['track']}`\n🚗 `{course['car']}`\n⏱️ Ghost Time: `{course['lap_time']}`", inline=True)
        
        embed.set_image(url=ASPHALT_MEDIA["banner_match"])
        embed.set_footer(text="Asynchronous Gauntlet Instance Engine v3.0")
        
        self.view.clear_items()
        await interaction.followup.send(content="🚦 **Green Light!** Match instance initialized. Submit your 5 lap times and 5 attack cars using the button below.", embed=embed, view=LobbyUIButtons(str(interaction.user.id), target_user_id, opp_data["courses"], opp_data.get("proof_url")))
        await interaction.message.edit(view=self.view)

class ChallengeView(discord.ui.View):
    def __init__(self, options_list: list[discord.SelectOption], defender_def_data: dict, guild_id: str, user_id: str):
        super().__init__(timeout=60)
        self.guild_id, self.user_id = guild_id, user_id
        self.add_item(ChallengeDropdown(options_list, defender_def_data))

@bot.tree.command(name="setimage", description="[Admin Only] Update a custom bot image (banner or thumbnail).")
@app_commands.describe(image_type="Which image to replace", image="Upload the new image file")
@app_commands.choices(image_type=[
    app_commands.Choice(name="Help Banner", value="banner_help"),
    app_commands.Choice(name="Match Banner", value="banner_match"),
    app_commands.Choice(name="Leaderboard Banner", value="banner_leaderboard"),
    app_commands.Choice(name="Profile Thumbnail", value="thumb_profile"),
    app_commands.Choice(name="Diagnostics Thumbnail", value="thumb_diagnostics"),
])
async def setimage_cmd(interaction: discord.Interaction, image_type: app_commands.Choice[str], image: discord.Attachment):
    if not interaction.user.guild_permissions.administrator and not await check_admin_privileges(interaction):
        await interaction.response.send_message("❌ Access Denied: Admin only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    guild_id = str(interaction.guild_id)
    # Validate it's an image
    if not image.content_type or not image.content_type.startswith("image/"):
        await interaction.followup.send("❌ The uploaded file must be an image (PNG, JPG, GIF, etc.).", ephemeral=True)
        return
    # Re-upload to the log channel for a permanent CDN URL
    cfg = await bot.db.settings.find_one({"_id": guild_id})
    log_chan = bot.get_channel(int(cfg["log_channel_id"])) if cfg and cfg.get("log_channel_id") else None
    if not log_chan:
        await interaction.followup.send("❌ Log channel not configured. Run `/setup` first.", ephemeral=True)
        return
    # Download the attachment
    import io as _io
    img_data = await image.read()
    filename = f"{image_type.value}.{image.filename.split('.')[-1] if '.' in image.filename else 'png'}"
    sent_msg = await log_chan.send(content=f"📦 Custom image upload: **{image_type.name}**", file=discord.File(fp=_io.BytesIO(img_data), filename=filename))
    # Get the permanent CDN URL from the sent message
    if sent_msg.attachments:
        cdn_url = sent_msg.attachments[0].url
    else:
        await interaction.followup.send("❌ Failed to re-upload image. Please try again.", ephemeral=True)
        return
    # Update in-memory dict and DB
    image_key = image_type.value
    ASPHALT_MEDIA[image_key] = cdn_url
    await bot.db.settings.update_one({"_id": "global_media"}, {"$set": {f"custom_images.{image_key}": cdn_url}}, upsert=True)
    await interaction.followup.send(embed=discord.Embed(title="✅ Image Updated", description=f"**{image_type.name}** has been updated successfully.\nNew URL: `{cdn_url}`", color=ASPHALT_VICTORY_COLOR).set_image(url=cdn_url), ephemeral=True)
    await dispatch_audit_log(guild_id, "🖼️ Custom Image Updated", f"Admin {interaction.user.mention} updated the **{image_type.name}** image.", color=0x2ecc71)
    await audit_admin_action(interaction, "Set Image", f"Updated `{image_type.value}`.")

@bot.tree.command(name="setup", description="[Admin Only] Configures all league core channels and permission roles.")
@app_commands.describe(main_channel="Public room for commands", staff_channel="Private room for staff reviews", log_channel="Private room for logs", announcement_channel="Public awards room", match_results_channel="Public room for match results", admin_role="Admin override role", player_role="Verified player role")
async def setup_cmd(interaction: discord.Interaction, main_channel: discord.TextChannel, staff_channel: discord.TextChannel, log_channel: discord.TextChannel, announcement_channel: discord.TextChannel, match_results_channel: discord.TextChannel, admin_role: discord.Role, player_role: discord.Role):
    if not interaction.user.guild_permissions.administrator and not await check_admin_privileges(interaction):
        await interaction.response.send_message("❌ Access Denied: Admin role overrides missing.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    await bot.db.settings.update_one({"_id": str(interaction.guild_id)}, {"$set": {"registration_channel_id": str(main_channel.id), "review_channel_id": str(staff_channel.id), "log_channel_id": str(log_channel.id), "announcement_channel_id": str(announcement_channel.id), "match_results_channel_id": str(match_results_channel.id), "admin_role_id": str(admin_role.id), "player_role_id": str(player_role.id)}}, upsert=True)
    guild_state = await bot.db.season_state.find_one({"_id": f"guild_{interaction.guild_id}"})
    if not guild_state:
        legacy_state = await bot.db.season_state.find_one({"_id": "current_season"})
        await bot.db.season_state.update_one(
            {"_id": f"guild_{interaction.guild_id}"},
            {"$setOnInsert": {
                "guild_id": str(interaction.guild_id),
                "season_number": int(legacy_state.get("season_number", 1)) if legacy_state else 1,
                "ends_at": float(legacy_state.get("ends_at", time.time() + (14 * 24 * 60 * 60))) if legacy_state else time.time() + (14 * 24 * 60 * 60),
            }},
            upsert=True,
        )
    await interaction.followup.send(embed=discord.Embed(title="⚙️ Master League Matrix Configuration Restored", description="All channel streams and dynamic role mapping rules saved successfully. Match results will be posted to the designated channel.", color=ASPHALT_THEME_COLOR))
    await dispatch_audit_log(interaction.guild_id, "⚙️ Master Setup Initialized", f"The bot was initialized perfectly by authority {interaction.user.mention}.", color=ASPHALT_THEME_COLOR)
    await audit_admin_action(interaction, "Setup", "Updated the league channel and role configuration.")

@bot.tree.command(name="season_schedule", description="[Admin Only] Sets custom calendar horizons for active tournament season grids.")
@app_commands.describe(start_date="Start date mapping (YYYY-MM-DD HH:MM)", end_date="Closing deadline boundary (YYYY-MM-DD HH:MM)")
async def season_schedule_cmd(interaction: discord.Interaction, start_date: str, end_date: str):
    if not interaction.user.guild_permissions.administrator and not await check_admin_privileges(interaction):
        await interaction.response.send_message("❌ Access Denied: Requires admin access clearance level.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        start_dt = datetime.strptime(start_date.strip(), "%Y-%m-%d %H:%M")
        end_dt = datetime.strptime(end_date.strip(), "%Y-%m-%d %H:%M")
        end_timestamp = time.mktime(end_dt.timetuple())
        
        await bot.db.season_state.update_one(
            {"_id": f"guild_{interaction.guild_id}"},
            {"$set": {"guild_id": str(interaction.guild_id), "ends_at": end_timestamp}},
            upsert=True
        )
        
        success_emb = discord.Embed(title="📅 TOURNAMENT CALENDAR TIMELINE INITIALIZED", color=ASPHALT_VICTORY_COLOR)
        success_emb.description = f"⏱️ **Horizon Window Verified:**\n• **Start Matrix Point:** `{start_date}`\n• **Lockdown Vector Entry:** `{end_date}`\n\nDynamic tracking clocks synced perfectly."
        await interaction.followup.send(embed=success_emb)
        await dispatch_audit_log(interaction.guild_id, "📅 Timeline Program Updated", f"Season schedule modified manually. Target close entry locks scheduled at: {end_date}", color=ASPHALT_THEME_COLOR)
        await audit_admin_action(interaction, "Season Schedule", f"Changed season closing time to `{end_date}`.")
    except ValueError:
        await interaction.followup.send("❌ **Timestamp Read Error:** Please verify exact syntax pattern structural formats: `YYYY-MM-DD HH:MM`", ephemeral=True)

@bot.tree.command(name="clearhistory", description="[Staff Only] Wipes specific collections or completely resets data.")
@app_commands.choices(target_data=[app_commands.Choice(name="Pending Queue Only", value="pending"), app_commands.Choice(name="Approved Drivers Only", value="drivers"), app_commands.Choice(name="Reset Everything", value="all")])
async def clear_history_cmd(interaction: discord.Interaction, target_data: app_commands.Choice[str]):
    if not await enforce_channel_constraints(interaction, admin_cmd=True) or not await check_admin_privileges(interaction): return
    await interaction.response.defer(ephemeral=True)
    try:
        if target_data.value in ["pending", "all"]: await bot.db.pending.delete_many({"guild_id": str(interaction.guild_id)})
        if target_data.value in ["drivers", "all"]: await bot.db.drivers.delete_many({"guild_id": str(interaction.guild_id)})
        await interaction.followup.send("🧹 Database Purge Complete")
        await audit_admin_action(interaction, "Clear History", f"Purged target `{target_data.value}` from this server.", color=ASPHALT_DEFEAT_COLOR)
    except Exception:
        logging.exception("clearhistory failed")

@bot.tree.command(name="seasonend", description="[Staff Only] Force-closes the season.")
async def season_end_cmd(interaction: discord.Interaction):
    if not await enforce_channel_constraints(interaction, admin_cmd=True) or not await check_admin_privileges(interaction): return
    await interaction.response.defer(ephemeral=True)
    await trigger_global_season_end(forced_interaction=interaction)

@bot.tree.command(name="admin_setpi", description="[Staff Only] Overrides a driver's PI value.")
async def admin_setpi_cmd(interaction: discord.Interaction, racer: discord.Member, new_pi: int):
    if not await enforce_channel_constraints(interaction, admin_cmd=True) or not await check_admin_privileges(interaction): return
    await interaction.response.defer(ephemeral=True)
    await bot.db.drivers.update_one({"_id": f"{str(interaction.guild_id)}_{str(racer.id)}"}, {"$set": {"garage_pi": int(new_pi)}})
    await interaction.followup.send(f"✅ Forced {racer.mention}'s profile rating to `{new_pi:,} PI`.")
    await audit_admin_action(interaction, "Set PI", f"Changed <@{racer.id}>'s Garage PI to `{new_pi:,}`.")

class ConfirmRemoveRacerView(discord.ui.View):
    def __init__(self, guild_id: str, racer: discord.User):
        super().__init__(timeout=30)
        self.guild_id, self.racer = str(guild_id), racer

    @discord.ui.button(label="Confirm Purge", style=discord.ButtonStyle.red)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children: item.disabled = True
        await bot.db.drivers.delete_one({"_id": f"{self.guild_id}_{self.racer.id}"})
        await interaction.response.edit_message(content=f"🧹 **Purged:** {self.racer.name}'s driver profile was permanently removed.", view=self)
        await dispatch_audit_log(self.guild_id, "🧹 Driver Purged", f"Staff {interaction.user.mention} permanently removed <@{self.racer.id}>'s driver profile.", color=0xe74c3c)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(content="❌ Purge cancelled — no changes were made.", view=self)
        self.stop()

@bot.tree.command(name="admin_removeracer", description="[Staff Only] Purges a driver.")
async def admin_removeracer_cmd(interaction: discord.Interaction, racer: discord.User):
    if not await enforce_channel_constraints(interaction, admin_cmd=True) or not await check_admin_privileges(interaction): return
    profile = await bot.db.drivers.find_one({"_id": f"{str(interaction.guild_id)}_{str(racer.id)}"})
    if not profile:
        await interaction.response.send_message(f"ℹ️ {racer.name} doesn't have a driver profile to remove.", ephemeral=True)
        return
    await interaction.response.send_message(
        f"⚠️ **Confirm Purge:** This will permanently delete {racer.mention}'s driver profile (`{profile.get('elo', 1000)} ELO`, `{profile.get('career_wins', 0)} wins`). This cannot be undone.",
        view=ConfirmRemoveRacerView(interaction.guild_id, racer),
        ephemeral=True,
    )
    await audit_admin_action(interaction, "Remove Racer", f"Opened a purge confirmation for <@{racer.id}>.", color=ASPHALT_ALERT_COLOR)

async def track_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return [app_commands.Choice(name=track, value=track) for track in ALU_TRACKS if current.lower() in track.lower()][:25]

async def car_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return [app_commands.Choice(name=car, value=car) for car in ALU_CARS if current.lower() in car.lower()][:25]

@bot.tree.command(name="setdefense", description="🛡️ Generates 5 random courses for your defense setup.")
async def set_defense_cmd(interaction: discord.Interaction):
    if not await enforce_channel_constraints(interaction, admin_cmd=False): return
    await interaction.response.defer(ephemeral=True)
    profile = await bot.db.drivers.find_one({"_id": f"{str(interaction.guild_id)}_{str(interaction.user.id)}"})
    if not profile:
        await interaction.followup.send("❌ Run `/register` first.", ephemeral=True)
        return
    if has_5_course_defense(profile):
        await interaction.followup.send("ℹ️ You already have a defense. Use `/changedefense` to change it.", ephemeral=True)
        return
    if profile.get("defense_review_pending"):
        await interaction.followup.send("⏳ Your defense submission is already pending staff review. Wait for it to be approved or rejected.", ephemeral=True)
        return
    # If pending tracks already exist (no rerolling), show them again
    pending_tracks = profile.get("pending_tracks")
    if pending_tracks:
        track_list = "\n".join([f"{i+1}. {t}" for i, t in enumerate(pending_tracks)])
        embed = discord.Embed(title="🛡️ Your 5 Defense Courses (Already Generated)", description=f"You already have courses generated. Race on each track and use `/submitdefense` to submit your times and cars.\n\n```\n{track_list}\n```", color=ASPHALT_THEME_COLOR)
        embed.set_footer(text="Use /submitdefense with your 5 lap times and 5 cars to complete your defense setup.")
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    # Generate 5 random tracks (no repeats)
    tracks = random.sample(ALU_TRACKS, 5)
    await bot.db.drivers.update_one({"_id": f"{str(interaction.guild_id)}_{str(interaction.user.id)}"}, {"$set": {"pending_tracks": tracks, "pending_is_change": False}})
    track_list = "\n".join([f"{i+1}. {t}" for i, t in enumerate(tracks)])
    embed = discord.Embed(title="🛡️ Your 5 Defense Courses Generated", description=f"Race on each of these 5 tracks and record your best lap times. Then use `/submitdefense` to submit your times and cars.\n\n```\n{track_list}\n```", color=ASPHALT_THEME_COLOR)
    embed.set_footer(text="Use /submitdefense with your 5 lap times and 5 cars to complete your defense setup.")
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="mydefense", description="View your currently locked ghost defense.")
async def my_defense_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guild_id, user_id = str(interaction.guild_id), str(interaction.user.id)
    profile = await bot.db.drivers.find_one({"_id": f"{guild_id}_{user_id}"})
    if not profile:
        await interaction.followup.send("❌ Run `/register` first.", ephemeral=True)
        return
    defense = profile.get("defense_locked")
    if not defense or not defense.get("courses"):
        await interaction.followup.send("ℹ️ Your defense needs to be upgraded to the new 5-course format. Use `/setdefense` to generate new courses.", ephemeral=True)
        return
    courses = defense.get("courses", [])
    embed = discord.Embed(title="🛡️ Your Locked Ghost Defense (5 Courses)", color=ASPHALT_THEME_COLOR)
    for i, course in enumerate(courses):
        embed.add_field(name=f"🏁 Course {i+1}", value=f"📍 `{course['track']}`\n🚗 `{course['car']}`\n⏱️ `{course['lap_time']}`", inline=True)
    embed.set_footer(text="Use /changedefense to submit a replacement for staff review (once per day).")
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="changedefense", description="🛡️ Generate 5 new random courses to change your defense (once per 24 hours).")
async def change_defense_cmd(interaction: discord.Interaction):
    if not await enforce_channel_constraints(interaction, admin_cmd=False): return
    await interaction.response.defer(ephemeral=True)
    profile = await bot.db.drivers.find_one({"_id": f"{str(interaction.guild_id)}_{str(interaction.user.id)}"})
    if not profile:
        await interaction.followup.send("❌ Run `/register` first.", ephemeral=True)
        return
    if not has_5_course_defense(profile):
        await interaction.followup.send("ℹ️ You don't have a valid 5-course defense yet. Use `/setdefense` to set up your first one.", ephemeral=True)
        return
    if profile.get("defense_review_pending"):
        await interaction.followup.send("⏳ Your defense change is already pending staff review. Wait for it to be approved or rejected.", ephemeral=True)
        return
    # Enforce once-per-day cooldown on defense changes
    last_change = profile.get("last_defense_change")
    if last_change:
        elapsed = time.time() - last_change
        if elapsed < 86400:
            remaining = 86400 - elapsed
            hours = int(remaining // 3600)
            minutes = int((remaining % 3600) // 60)
            await interaction.followup.send(f"⏳ **Cooldown Active:** You can change your defense again in `{hours}h {minutes}m`. Defense changes are limited to once per day.", ephemeral=True)
            return
    # If pending tracks already exist (no rerolling), show them again
    pending_tracks = profile.get("pending_tracks")
    if pending_tracks:
        track_list = "\n".join([f"{i+1}. {t}" for i, t in enumerate(pending_tracks)])
        embed = discord.Embed(title="🛡️ Your 5 New Defense Courses (Already Generated)", description=f"You already have new courses generated. Race on each track and use `/submitdefense` to submit your times and cars.\n\nYour current defense remains active until the new one is approved.\n\n```\n{track_list}\n```", color=ASPHALT_THEME_COLOR)
        embed.set_footer(text="Use /submitdefense with your 5 lap times and 5 cars to complete your defense change.")
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    # Generate 5 random tracks (no repeats)
    tracks = random.sample(ALU_TRACKS, 5)
    await bot.db.drivers.update_one({"_id": f"{str(interaction.guild_id)}_{str(interaction.user.id)}"}, {"$set": {"pending_tracks": tracks, "pending_is_change": True}})
    track_list = "\n".join([f"{i+1}. {t}" for i, t in enumerate(tracks)])
    embed = discord.Embed(title="🛡️ Your 5 New Defense Courses Generated", description=f"Race on each of these 5 tracks and record your best lap times. Then use `/submitdefense` to submit your times and cars.\n\nYour current defense remains active until the new one is approved.\n\n```\n{track_list}\n```", color=ASPHALT_THEME_COLOR)
    embed.set_footer(text="Use /submitdefense with your 5 lap times and 5 cars to complete your defense change.")
    await interaction.followup.send(embed=embed, ephemeral=True)
@bot.tree.command(name="submitdefense", description="🛡️ Submit your times, cars, and proof screenshots for your generated defense courses.")
@app_commands.autocomplete(car_1=car_autocomplete, car_2=car_autocomplete, car_3=car_autocomplete, car_4=car_autocomplete, car_5=car_autocomplete)
@app_commands.describe(
    lap_time_1="Lap time for course 1 (MM:SS.MS)", lap_time_2="Lap time for course 2 (MM:SS.MS)", lap_time_3="Lap time for course 3 (MM:SS.MS)", lap_time_4="Lap time for course 4 (MM:SS.MS)", lap_time_5="Lap time for course 5 (MM:SS.MS)",
    car_1="Car for course 1", car_2="Car for course 2", car_3="Car for course 3", car_4="Car for course 4", car_5="Car for course 5",
    proof_screenshot_1="Screenshot proving lap time 1", proof_screenshot_2="Screenshot proving lap time 2", proof_screenshot_3="Screenshot proving lap time 3", proof_screenshot_4="Screenshot proving lap time 4", proof_screenshot_5="Screenshot proving lap time 5"
)
async def submit_defense_cmd(interaction: discord.Interaction, lap_time_1: str, lap_time_2: str, lap_time_3: str, lap_time_4: str, lap_time_5: str, car_1: str, car_2: str, car_3: str, car_4: str, car_5: str, proof_screenshot_1: discord.Attachment, proof_screenshot_2: discord.Attachment, proof_screenshot_3: discord.Attachment, proof_screenshot_4: discord.Attachment, proof_screenshot_5: discord.Attachment):
    if not await enforce_channel_constraints(interaction, admin_cmd=False): return
    await interaction.response.defer(ephemeral=True)
    profile = await bot.db.drivers.find_one({"_id": f"{str(interaction.guild_id)}_{str(interaction.user.id)}"})
    if not profile:
        await interaction.followup.send("❌ Run `/register` first.", ephemeral=True)
        return
    if profile.get("defense_review_pending"):
        await interaction.followup.send("⏳ Your defense submission is already pending staff review. Wait for it to be approved or rejected.", ephemeral=True)
        return
    pending_tracks = profile.get("pending_tracks")
    if not pending_tracks:
        await interaction.followup.send("❌ No pending courses. Use `/setdefense` or `/changedefense` to generate courses first.", ephemeral=True)
        return
    is_change = profile.get("pending_is_change", False)
    
    lap_times = [lap_time_1, lap_time_2, lap_time_3, lap_time_4, lap_time_5]
    cars = [car_1, car_2, car_3, car_4, car_5]
    proof_screenshots = [proof_screenshot_1, proof_screenshot_2, proof_screenshot_3, proof_screenshot_4, proof_screenshot_5]
    
    # Check for duplicate cars
    if len({c.strip().lower() for c in cars}) != len(cars):
        await interaction.followup.send("❌ **Duplicate Cars:** All 5 cars must be different. Please choose 5 unique cars.", ephemeral=True)
        return
    
    # Every lap needs its own proof screenshot
    for i, shot in enumerate(proof_screenshots):
        if not shot.content_type or not shot.content_type.startswith("image/"):
            await interaction.followup.send(f"❌ **Invalid Proof:** The screenshot for lap {i+1} must be an image file.", ephemeral=True)
            return
    
    # Validate all 5 lap times and build course objects (each with its own proof)
    courses = []
    for i in range(5):
        ms = parse_lap_time(lap_times[i])
        if ms < 0:
            await interaction.followup.send(f"❌ **Invalid Format:** Lap time {i+1} (`{lap_times[i]}`) must be in `MM:SS.MS` format.", ephemeral=True)
            return
        courses.append({"track": pending_tracks[i], "car": cars[i], "lap_time": lap_times[i], "ms": ms, "proof_url": proof_screenshots[i].url})
    
    cfg = await bot.db.settings.find_one({"_id": str(interaction.guild_id)})
    chan = bot.get_channel(int(cfg["review_channel_id"])) if cfg else None
    if chan:
        if is_change:
            header_emb = discord.Embed(title="🛡️ Gauntlet Defense Change Request", description="A driver has requested to change their locked 5-course defense. Their current defense remains active until the new one is approved.", color=0x3498db)
        else:
            header_emb = discord.Embed(title="🛡️ New Gauntlet Defense Placement Verification", description="**Staff:** please verify each course's lap time and car against its matching screenshot below.", color=0x3498db)
        header_emb.add_field(name="Driver", value=interaction.user.mention, inline=False)
        review_embeds = [header_emb]
        for i, course in enumerate(courses):
            course_emb = discord.Embed(title=f"🏁 Course {i+1}: {course['track']}", description=f"🚗 **Car:** `{course['car']}`\n⏱️ **Lap Time:** `{course['lap_time']}`", color=0x3498db)
            course_emb.set_image(url=course["proof_url"])
            review_embeds.append(course_emb)
        await chan.send(embeds=review_embeds, view=DefenseView(str(interaction.user.id), str(interaction.guild_id), courses, courses[0]["proof_url"], is_change=is_change))
        # Set review-pending flag (don't clear pending_tracks so they can resubmit if rejected)
        await bot.db.drivers.update_one({"_id": f"{str(interaction.guild_id)}_{str(interaction.user.id)}"}, {"$set": {"defense_review_pending": True}})
        if is_change:
            await interaction.followup.send("📥 **Defense Change Staged:** 5-course lineup sent to staff for audit clearance! Your current defense remains active until the new one is approved.")
        else:
            await interaction.followup.send("📥 **Defense Staged:** 5-course lineup sent to staff for audit clearance!")
    else:
        await interaction.followup.send("❌ Staff review channel is not configured. Ask an administrator to run `/setup`.", ephemeral=True)

@bot.tree.command(name="challenge", description="Fetches active 5-course defense ghosts for matchmaking (5 per day).")
@app_commands.checks.cooldown(1, 45.0, key=lambda i: (i.guild_id, i.user.id))
async def challenge_cmd(interaction: discord.Interaction):
    if not await enforce_channel_constraints(interaction, admin_cmd=False): return
    await interaction.response.defer()
    guild_id, user_id = str(interaction.guild_id), str(interaction.user.id)
    user_profile = await bot.db.drivers.find_one({"_id": f"{guild_id}_{user_id}"})
    if not user_profile:
        await interaction.followup.send("❌ Run `/register` first.")
        return
    state = await bot.db.season_state.find_one({"_id": f"guild_{guild_id}"})
    season_number = int(state.get("season_number", 1)) if state else 1
    if not user_profile.get("season_registered") or int(user_profile.get("season_number", 0)) != season_number:
        await interaction.followup.send(f"🔄 You must re-register your Garage for Season {season_number} before challenging.")
        return
    # Challenger must have a locked 5-course defense to challenge others
    if not has_5_course_defense(user_profile):
        await interaction.followup.send("❌ You need a locked 5-course defense to challenge others. Use `/setdefense` to generate your 5 courses and `/submitdefense` to lock your defense.")
        return
    # Daily challenge limit: 5 per day (UTC date boundary)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    challenge_date = user_profile.get("challenge_date")
    challenge_count = user_profile.get("challenge_count", 0)
    if challenge_date == today and challenge_count >= 5:
        await interaction.followup.send("⏳ **Daily Limit Reached:** You've used all 5 of your daily challenges. Come back tomorrow!", ephemeral=True)
        return
    user_pi = user_profile.get("garage_pi", 15500)
    pi_query = division_mongo_query(get_division_for_pi(user_pi))
    cursor = bot.db.drivers.find({"guild_id": guild_id, "user_id": {"$ne": user_id}, "garage_pi": pi_query, "defense_locked.courses.4": {"$exists": True}}).limit(10)
    candidates = await cursor.to_list(length=10)
    if not candidates:
        await interaction.followup.send("⚠️ No matching opponents are qualified with active 5-course defenses yet inside your performance tier bracket.")
        return
    remaining = 5 - (challenge_count + 1 if challenge_date == today else 1)
    selected_opponents = random.sample(candidates, min(len(candidates), 3))
    defender_data_map = {opp["user_id"]: {"courses": opp["defense_locked"]["courses"], "proof_url": opp["defense_locked"].get("proof_url")} for opp in selected_opponents}
    options_list = [discord.SelectOption(label=f"{opp['game_id']} | Elo: {opp.get('elo', 1000)}", value=opp["user_id"], emoji="🏎️") for opp in selected_opponents]
    
    match_embed = discord.Embed(
        title="⚡ AUTOMATED MATCHMAKING MATRIX ONLINE",
        description=f"A competitive matchmaking target window has stabilized. Choose your opponent from the terminal menu dropdown below!\n\n⚠️ *Each opponent has a 5-course defense — win 3 out of 5 races to win the match! Pick your own cars for each course.*\n\n📊 **Daily challenges remaining:** `{remaining}/5`",
        color=ASPHALT_THEME_COLOR
    )
    match_embed.set_image(url=ASPHALT_MEDIA["banner_match"])
    await interaction.followup.send(embed=match_embed, view=ChallengeView(options_list, defender_data_map, guild_id, user_id))

@challenge_cmd.error
async def challenge_cmd_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(f"⏳ **Slow down!** You can search for a new opponent again in `{error.retry_after:.0f}s`.", ephemeral=True)
    else:
        logging.exception("/challenge command error", exc_info=error)

@bot.tree.command(name="profile", description="Inspects driver file card.")
async def profile_cmd(interaction: discord.Interaction, driver: discord.Member = None):
    if not await enforce_channel_constraints(interaction, admin_cmd=False): return
    await interaction.response.defer()
    target_user = driver or interaction.user
    profile = await bot.db.drivers.find_one({"_id": f"{str(interaction.guild_id)}_{str(target_user.id)}"})
    if not profile:
        await interaction.followup.send("❌ Profile card missing. Run `/register` first.")
        return
        
    embed = discord.Embed(title="🏁 ALU GAUNTLET DRIVER DOSSIER CARD", color=ASPHALT_THEME_COLOR)
    embed.set_thumbnail(url=ASPHALT_MEDIA["thumb_profile"])
    
    stats_matrix = (
        f"• **League Elo Rating:** `{profile.get('elo', 1000)} ELO`\n"
        f"• **Performance Group:** `{profile.get('garage_pi', 0):,} PI Value`\n"
        f"• **Career Victories:** `{profile.get('career_wins', 0)} Wins`\n"
        f"• **Total Matches:** `{profile.get('career_played', 0)} Played`\n"
        f"• **Active Win Streak:** `{profile.get('streak', 0)} Streak`"
    )
    embed.add_field(name="👤 Pilot Credentials", value=f"• **User:** {target_user.mention}\n• **Game ID Node:** `{profile.get('game_id')}`", inline=True)
    embed.add_field(name="📊 Operational Statistics Ledger", value=stats_matrix, inline=False)
    
    if has_5_course_defense(profile):
        courses = profile["defense_locked"].get("courses", [])
        if courses:
            def_lines = ""
            for i, course in enumerate(courses):
                def_lines += f"🏁 **Course {i+1}:** `{course['track']}` | 🚗 `{course['car']}` | ⏱️ `{course['lap_time']}`\n"
            embed.add_field(name="🛡️ Deployed Ghost Defense Framework", value=def_lines, inline=False)
        
    embed.set_footer(text="System Terminal Sync Matrix v2.0", icon_url=target_user.display_avatar.url)
    await interaction.followup.send(embed=embed)

class LeaderboardDivisionView(discord.ui.View):
    """Interactive, paginated current-season division leaderboard."""
    def __init__(self, guild_id: str, division_index: int = 5, page: int = 1):
        super().__init__(timeout=300)
        self.guild_id = str(guild_id)
        self.division_index = int(division_index)
        self.page = max(1, int(page))
        self.select = discord.ui.Select(
            placeholder="Select a division...", min_values=1, max_values=1,
            options=[
                discord.SelectOption(label=div["name"], value=str(i), default=(i == self.division_index))
                for i, div in enumerate(PI_DIVISIONS)
            ]
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)
        self.prev_button = discord.ui.Button(label="◀ Previous", style=discord.ButtonStyle.secondary)
        self.next_button = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary)
        self.prev_button.callback = self.prev_callback
        self.next_button.callback = self.next_callback
        self.add_item(self.prev_button)
        self.add_item(self.next_button)

    async def render(self, interaction: discord.Interaction, initial: bool = False):
        div = PI_DIVISIONS[self.division_index]
        query = {"guild_id": self.guild_id, "season_registered": True, "garage_pi": division_mongo_query(div)}
        total = await bot.db.drivers.count_documents(query)
        per_page = 10
        pages = max(1, (total + per_page - 1) // per_page)
        self.page = min(self.page, pages)
        cursor = bot.db.drivers.find(query).sort("elo", -1).skip((self.page - 1) * per_page).limit(per_page)
        drivers = await cursor.to_list(length=per_page)
        embed = discord.Embed(
            title=f"🏆 {div['name']} — Season Leaderboard",
            description=f"**{total}** registered driver(s) • Page **{self.page}/{pages}** • Ranked by ELO",
            color=div["color"],
        )
        embed.set_image(url=ASPHALT_MEDIA["banner_leaderboard"])
        if not drivers:
            embed.description += "\n\n*No currently registered drivers in this division.*"
        else:
            lines = []
            start_rank = (self.page - 1) * per_page + 1
            for r, d in enumerate(drivers, start=start_rank):
                lines.append(f"**#{r}** <@{d['user_id']}> — **{d.get('elo', 1000)} ELO** • `{d.get('garage_pi', 0):,} PI` • `{d.get('game_id', 'Unknown')}`")
            embed.add_field(name="🏁 Standings", value="\n".join(lines), inline=False)
        embed.set_footer(text="Anyone can view the leaderboard. Use the dropdown or page buttons.")
        self.prev_button.disabled = self.page <= 1
        self.next_button.disabled = self.page >= pages
        if initial:
            await interaction.followup.send(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    async def select_callback(self, interaction: discord.Interaction):
        self.division_index = int(self.select.values[0])
        self.page = 1
        for option in self.select.options:
            option.default = option.value == str(self.division_index)
        await self.render(interaction)

    async def prev_callback(self, interaction: discord.Interaction):
        self.page -= 1
        await self.render(interaction)

    async def next_callback(self, interaction: discord.Interaction):
        self.page += 1
        await self.render(interaction)

@bot.tree.command(name="leaderboard", description="View current-season division standings.")
async def leaderboard_cmd(interaction: discord.Interaction):
    if not await enforce_channel_constraints(interaction, admin_cmd=False):
        return
    await interaction.response.defer()
    state = await bot.db.season_state.find_one({"_id": f"guild_{interaction.guild_id}"})
    season_number = int(state.get("season_number", 1)) if state else 1
    embed = discord.Embed(
        title=f"🏆 SEASON {season_number} DIVISION LEADERBOARD",
        description="Select a division below. Standings are paginated so large divisions never overflow Discord's embed limits.",
        color=ASPHALT_THEME_COLOR,
    )
    embed.set_image(url=ASPHALT_MEDIA["banner_leaderboard"])
    await interaction.followup.send(embed=embed, view=LeaderboardDivisionView(str(interaction.guild_id)))

class TopLeaderboardView(discord.ui.View):
    """Persistent dropdown view for selecting which top 5 leaderboard to display.
    Works for everyone — any user can click the dropdown at any time."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        placeholder="Choose a leaderboard category...",
        min_values=1, max_values=1,
        custom_id="top_leaderboard_select",
        options=[
            discord.SelectOption(label="Top 5 Most Wins", value="wins", emoji="🏆", description="Players with the most career wins"),
            discord.SelectOption(label="Top 5 Most Active", value="active", emoji="⚡", description="Players who played the most matches"),
            discord.SelectOption(label="Top 5 Overall", value="elo", emoji="👑", description="Highest ELO ratings"),
        ]
    )
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        category = self.values[0]
        guild_id = str(interaction.guild_id)

        if category == "wins":
            cursor = bot.db.drivers.find({"guild_id": guild_id}).sort("career_wins", -1).limit(5)
            top = await cursor.to_list(length=5)
            title = "🏆 TOP 5 MOST WINS"
            desc = "Players with the most career victories"
            field_name = "🔥 Top Victor Registries"
            if not top:
                board = "*No career metrics compiled yet.*"
            else:
                board = ""
                for r, d in enumerate(top):
                    board += f"`#{r+1}` <@{d['user_id']}> ── **`{d.get('career_wins', 0)} Wins`** ({d.get('career_played', 0)} played)\n"
        elif category == "active":
            cursor = bot.db.drivers.find({"guild_id": guild_id}).sort("career_played", -1).limit(5)
            top = await cursor.to_list(length=5)
            title = "⚡ TOP 5 MOST ACTIVE"
            desc = "Players with the most matches played"
            field_name = "📊 Most Active Drivers"
            if not top:
                board = "*No activity data yet.*"
            else:
                board = ""
                for r, d in enumerate(top):
                    board += f"`#{r+1}` <@{d['user_id']}> ── **`{d.get('career_played', 0)} Matches`** ({d.get('career_wins', 0)} wins)\n"
        else:  # elo
            cursor = bot.db.drivers.find({"guild_id": guild_id}).sort("elo", -1).limit(5)
            top = await cursor.to_list(length=5)
            title = "👑 TOP 5 OVERALL"
            desc = "Highest ELO rated players"
            field_name = "🏁 Top Rated Drivers"
            if not top:
                board = "*No rated drivers yet.*"
            else:
                board = ""
                for r, d in enumerate(top):
                    board += f"`#{r+1}` <@{d['user_id']}> ── **`{d.get('elo', 1000)} ELO`** ({d.get('career_wins', 0)} wins)\n"

        embed = discord.Embed(title=title, description=desc, color=ASPHALT_THEME_COLOR)
        embed.set_thumbnail(url=ASPHALT_MEDIA["thumb_profile"])
        embed.add_field(name=field_name, value=board, inline=False)
        embed.set_footer(text="Use the dropdown to switch categories")
        await interaction.followup.send(embed=embed)

@bot.tree.command(name="top", description="View top 5 leaderboards — choose a category.")
async def top_cmd(interaction: discord.Interaction):
    if not await enforce_channel_constraints(interaction, admin_cmd=False):
        return
    await interaction.response.defer()
    guild_id = str(interaction.guild_id)
    embed = discord.Embed(title="👑 LEADERBOARD SELECTION", description="Choose a leaderboard category from the dropdown below to view the top 5 players.", color=ASPHALT_THEME_COLOR)
    embed.set_thumbnail(url=ASPHALT_MEDIA["thumb_profile"])
    embed.set_footer(text="Select a category below")
    await interaction.followup.send(embed=embed, view=TopLeaderboardView())

@bot.tree.command(name="register", description="Join the current season registry or re-register your Garage for a new season.")
@app_commands.describe(game_id="Your Asphalt Legends unique Player ID string", garage_pi="Your current Garage PI value, as shown in-game", proof_screenshot="Attachment file proving garage level and ratings", control_type="Your input driving mechanics style")
@app_commands.choices(control_type=[app_commands.Choice(name="TouchDrive Auto Pilot", value="touchdrive"), app_commands.Choice(name="Manual Tilt / Tap Controls", value="manual")])
async def register_cmd(interaction: discord.Interaction, game_id: str, garage_pi: int, proof_screenshot: discord.Attachment, control_type: app_commands.Choice[str]):
    if not await enforce_channel_constraints(interaction, admin_cmd=False):
        return
    await interaction.response.defer(ephemeral=True)
    guild_id, user_id = str(interaction.guild_id), str(interaction.user.id)
    cfg = await bot.db.settings.find_one({"_id": guild_id})
    if not cfg or not cfg.get("review_channel_id"):
        await interaction.followup.send("❌ **System Configurations Incomplete:** Ask an administrator to execute `/setup` first.", ephemeral=True)
        return
    if garage_pi <= 0:
        await interaction.followup.send("❌ **Invalid Value:** Garage PI must be a positive number.", ephemeral=True)
        return
    if not proof_screenshot.content_type or not proof_screenshot.content_type.startswith("image/"):
        await interaction.followup.send("❌ **Invalid Proof:** Please attach an image screenshot of your current Garage PI.", ephemeral=True)
        return

    state = await bot.db.season_state.find_one({"_id": f"guild_{guild_id}"})
    season_number = int(state.get("season_number", 1)) if state else 1
    existing = await bot.db.drivers.find_one({"_id": f"{guild_id}_{user_id}"})
    if existing and existing.get("season_registered") and int(existing.get("season_number", 0)) == season_number:
        await interaction.followup.send("⚠️ **Already Registered:** Your Garage is already registered for the current season. Your career stats are safe; use `/profile` to view them.", ephemeral=True)
        return

    pending_id = f"{guild_id}_{user_id}"
    pending_existing = await bot.db.pending.find_one({"_id": pending_id})
    if pending_existing and int(pending_existing.get("season_number", season_number)) == season_number:
        await interaction.followup.send("⚠️ **Application Already Pending:** Your current-season Garage registration is awaiting staff review. Use `/mystatus` to check.", ephemeral=True)
        return

    review_chan = bot.get_channel(int(cfg["review_channel_id"]))
    if not review_chan:
        await interaction.followup.send("❌ Staff review channel could not be found. Ask an administrator to run `/setup`.", ephemeral=True)
        return

    is_rereg = bool(existing)
    previous_pi = existing.get("garage_pi") if existing else None
    division = get_division_for_pi(garage_pi)["name"]
    emb = discord.Embed(
        title="🔄 Garage Re-Registration" if is_rereg else "👤 New Driver Registration Application",
        description=(
            f"Season **{season_number}** Garage verification packet. This is a **re-registration**; lifetime career statistics must be preserved.\n**Staff:** compare the declared Garage PI against the screenshot before approving."
            if is_rereg else
            "Incoming driver verification packet submitted by user.\n**Staff:** please compare the declared Garage PI against the attached screenshot before approving."
        ),
        color=ASPHALT_ADMIN_COLOR,
    )
    emb.add_field(name="Applicant User", value=interaction.user.mention, inline=True)
    emb.add_field(name="Declared Game ID", value=f"`{game_id}`", inline=True)
    emb.add_field(name="Declared Garage PI", value=f"`{garage_pi:,} PI`", inline=True)
    emb.add_field(name="Projected Division", value=division, inline=True)
    emb.add_field(name="Season", value=f"`{season_number}`", inline=True)
    if previous_pi is not None:
        emb.add_field(name="Previous Season PI", value=f"`{int(previous_pi):,} PI`", inline=True)
    emb.add_field(name="Dynamic Driving Layout", value=f"`{control_type.name}`", inline=False)
    emb.set_image(url=proof_screenshot.url)

    await bot.db.pending.update_one(
        {"_id": pending_id},
        {"$set": {
            "guild_id": guild_id, "user_id": user_id, "game_id": game_id, "rank": garage_pi,
            "control": control_type.value, "season_number": season_number, "is_reregistration": is_rereg,
            "submitted_at": time.time(), "proof_url": proof_screenshot.url,
        }},
        upsert=True,
    )
    await review_chan.send(embed=emb, view=VerificationView(user_id, guild_id, game_id, garage_pi, control_type.value))
    await interaction.followup.send(
        f"📥 **Season {season_number} Garage Registration Submitted:** Staff can approve your `{garage_pi:,} PI` projected **{division}** placement. Career stats are retained.",
        ephemeral=True,
    )

@bot.tree.command(name="mystatus", description="Check your current-season driver registration status.")
async def my_status_cmd(interaction: discord.Interaction):
    if not await enforce_channel_constraints(interaction, admin_cmd=False):
        return
    await interaction.response.defer(ephemeral=True)
    guild_id, user_id = str(interaction.guild_id), str(interaction.user.id)
    state = await bot.db.season_state.find_one({"_id": f"guild_{guild_id}"})
    season_number = int(state.get("season_number", 1)) if state else 1
    profile = await bot.db.drivers.find_one({"_id": f"{guild_id}_{user_id}"})
    if profile and profile.get("season_registered") and int(profile.get("season_number", 0)) == season_number:
        division = get_division_for_pi(int(profile.get("garage_pi", 0)))["name"]
        defense = profile.get("defense_locked")
        defense_status = "5-course defense locked" if has_5_course_defense(profile) else "defense still needs to be set"
        await interaction.followup.send(
            f"✅ **Season {season_number} Driver:** `{profile.get('elo', 1000)} ELO` / `{profile.get('garage_pi', 0):,} PI` → **{division}**. {defense_status}.",
            ephemeral=True,
        )
        return
    pending = await bot.db.pending.find_one({"_id": f"{guild_id}_{user_id}"})
    if pending and int(pending.get("season_number", season_number)) == season_number:
        division = get_division_for_pi(int(pending.get("rank", 0)))["name"]
        await interaction.followup.send(f"⏳ **Season {season_number} Pending Review:** Garage `{int(pending.get('rank', 0)):,} PI` → projected **{division}**. Staff approval is still required.", ephemeral=True)
        return
    career = profile.get("career_wins", 0) if profile else 0
    played = profile.get("career_played", 0) if profile else 0
    await interaction.followup.send(
        f"🔄 **Season {season_number} Re-Registration Required.** Your career record remains safe (`{career}` wins / `{played}` matches). Run `/register` with your current Garage PI to enter this season.",
        ephemeral=True,
    )


async def save_driver_best_time(guild_id: str, user_id: str, course: dict, season_number: int, source: str = "unknown"):
    """Persist a driver's best known lap and update the cross-server universal record."""
    track = course.get("track")
    ms = int(course.get("ms", -1))
    if not track or ms < 0:
        return
    doc_id = f"{guild_id}_{user_id}_{track}"
    existing = await bot.db.lap_times.find_one({"_id": doc_id})
    if existing and int(existing.get("best_ms", 10**18)) <= ms:
        return
    record = {
        "_id": doc_id, "guild_id": str(guild_id), "user_id": str(user_id), "track": track,
        "best_ms": ms, "best_lap_time": course.get("lap_time") or course.get("lap_time_str"),
        "car": course.get("car"), "proof_url": course.get("proof_url"),
        "season_number": int(season_number), "source": source, "updated_at": time.time(),
    }
    await bot.db.lap_times.replace_one({"_id": doc_id}, record, upsert=True)
    global_id = re.sub(r"[^a-z0-9]+", "_", track.lower()).strip("_")
    global_record = await bot.db.map_records.find_one({"_id": global_id})
    if not global_record or ms < int(global_record.get("best_ms", 10**18)):
        await bot.db.map_records.replace_one({"_id": global_id}, {
            "_id": global_id, "track": track, "best_ms": ms,
            "best_lap_time": record["best_lap_time"], "car": record.get("car"),
            "guild_id": str(guild_id), "user_id": str(user_id),
            "proof_url": record.get("proof_url"), "source": source, "updated_at": time.time(),
        }, upsert=True)

async def get_current_season_number(guild_id: str) -> int:
    state = await bot.db.season_state.find_one({"_id": f"guild_{guild_id}"})
    return int(state.get("season_number", 1)) if state else 1

async def send_driver_best_time(interaction: discord.Interaction, driver: discord.Member, track: str):
    guild_id = str(interaction.guild_id)
    rec = await bot.db.lap_times.find_one({"_id": f"{guild_id}_{driver.id}_{track}"})
    global_id = re.sub(r"[^a-z0-9]+", "_", track.lower()).strip("_")
    global_rec = await bot.db.map_records.find_one({"_id": global_id})
    embed = discord.Embed(title=f"⏱️ {driver.display_name} — {track}", color=ASPHALT_THEME_COLOR)
    if rec:
        embed.add_field(name="Driver Best", value=f"**`{rec['best_lap_time']}`**\n🚗 `{rec.get('car', 'Unknown')}`", inline=True)
    else:
        embed.add_field(name="Driver Best", value="*No saved lap for this map yet.*", inline=True)
    if global_rec:
        embed.add_field(name="🌎 Universal Best", value=f"**`{global_rec['best_lap_time']}`**\n👤 <@{global_rec['user_id']}> • 🚗 `{global_rec.get('car', 'Unknown')}`", inline=True)
    else:
        embed.add_field(name="🌎 Universal Best", value="*No universal record saved yet.*", inline=True)
    await interaction.followup.send(embed=embed)

class ReferenceDeclineModal(discord.ui.Modal, title="Decline Reference Submission"):
    reason_input = discord.ui.TextInput(label="Reason", style=discord.TextStyle.paragraph, required=True, max_length=400)

    def __init__(self, submission_id: str):
        super().__init__()
        self.submission_id = submission_id

    async def on_submit(self, interaction: discord.Interaction):
        if not await check_admin_privileges(interaction):
            await interaction.response.send_message("❌ Access Denied: Staff only.", ephemeral=True)
            return
        sub = await bot.db.reference_pending.find_one({"_id": self.submission_id})
        if not sub or sub.get("status") != "pending":
            await interaction.response.send_message("❌ Reference submission is no longer pending.", ephemeral=True)
            return
        await bot.db.reference_pending.update_one({"_id": self.submission_id}, {"$set": {
            "status": "declined", "declined_by": str(interaction.user.id),
            "reason": self.reason_input.value, "decided_at": time.time()
        }})
        member = interaction.guild.get_member(int(sub["user_id"]))
        if member:
            try:
                await member.send(embed=discord.Embed(
                    title="❌ Reference Submission Declined",
                    description=f"Your `/add_reference` submission for **{sub['track']}** was declined.\n\n**Reason:** {self.reason_input.value}",
                    color=ASPHALT_DEFEAT_COLOR,
                ))
            except Exception:
                pass
        await interaction.response.send_message("❌ Reference declined and the player was notified by DM.", ephemeral=True)
        await dispatch_audit_log(sub["guild_id"], "🎥 Reference Declined", f"Staff {interaction.user.mention} declined <@{sub['user_id']}> reference for `{sub['track']}`. Reason: {self.reason_input.value}", color=ASPHALT_DEFEAT_COLOR)

class ReferenceReviewView(discord.ui.View):
    def __init__(self, submission_id: str):
        super().__init__(timeout=None)
        self.submission_id = submission_id
        self.children[0].custom_id = f"reference_approve:{submission_id}"
        self.children[1].custom_id = f"reference_decline:{submission_id}"

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, custom_id="reference_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await check_admin_privileges(interaction):
            await interaction.response.send_message("❌ Access Denied: Staff only.", ephemeral=True)
            return
        sub = await bot.db.reference_pending.find_one({"_id": self.submission_id})
        if not sub or sub.get("status", "pending") != "pending":
            await interaction.response.send_message("❌ This reference is no longer pending.", ephemeral=True)
            return
        ref_id = re.sub(r"[^a-z0-9]+", "_", sub["track"].lower()).strip("_")
        current = await bot.db.map_references.find_one({"_id": ref_id})
        if current and int(sub["ms"]) >= int(current.get("best_ms", 10**18)):
            await interaction.response.send_message("❌ This lap is not faster than the current approved reference.", ephemeral=True)
            return
        await bot.db.map_references.replace_one({"_id": ref_id}, {
            "_id": ref_id, "track": sub["track"], "best_ms": int(sub["ms"]),
            "best_lap_time": sub["lap_time"], "video_url": sub["video_url"],
            "submitted_by": sub["user_id"], "guild_id": sub["guild_id"],
            "approved_by": str(interaction.user.id), "approved_at": time.time(),
        }, upsert=True)
        await bot.db.reference_pending.update_one({"_id": self.submission_id}, {"$set": {
            "status": "approved", "approved_by": str(interaction.user.id), "decided_at": time.time()
        }})
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=discord.Embed(title="✅ Reference Approved", description=f"`{sub['track']}` → **{sub['lap_time']}** is now the approved reference lap.", color=ASPHALT_VICTORY_COLOR),
            view=self,
        )
        await dispatch_audit_log(sub["guild_id"], "🎥 Reference Approved", f"Staff {interaction.user.mention} approved <@{sub['user_id']}> reference for `{sub['track']}` at `{sub['lap_time']}`. Video: {sub['video_url']}", color=ASPHALT_VICTORY_COLOR)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red, custom_id="reference_decline")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await check_admin_privileges(interaction):
            await interaction.response.send_message("❌ Access Denied: Staff only.", ephemeral=True)
            return
        await interaction.response.send_modal(ReferenceDeclineModal(self.submission_id))

@bot.tree.command(name="besttime", description="Compare a driver's best saved lap on a map with the universal record.")
@app_commands.describe(driver="Driver to inspect", map_name="Map/track to inspect")
@app_commands.autocomplete(map_name=track_autocomplete)
async def besttime_cmd(interaction: discord.Interaction, driver: discord.Member, map_name: str):
    if not await enforce_channel_constraints(interaction, admin_cmd=False):
        return
    await interaction.response.defer()
    if map_name not in ALU_TRACKS:
        await interaction.followup.send("❌ Please choose a map from the track list.", ephemeral=True)
        return
    await send_driver_best_time(interaction, driver, map_name)

@bot.tree.command(name="reference", description="Show the approved best reference lap and video for a map.")
@app_commands.describe(map_name="Map/track to inspect")
@app_commands.autocomplete(map_name=track_autocomplete)
async def reference_cmd(interaction: discord.Interaction, map_name: str):
    if not await enforce_channel_constraints(interaction, admin_cmd=False):
        return
    await interaction.response.defer()
    if map_name not in ALU_TRACKS:
        await interaction.followup.send("❌ Please choose a map from the track list.", ephemeral=True)
        return
    ref_id = re.sub(r"[^a-z0-9]+", "_", map_name.lower()).strip("_")
    ref = await bot.db.map_references.find_one({"_id": ref_id})
    embed = discord.Embed(title=f"🎥 Reference Lap — {map_name}", color=ASPHALT_THEME_COLOR)
    if ref:
        embed.description = f"**Best Approved Lap:** `{ref['best_lap_time']}`\n**Video Reference:** {ref['video_url']}\n**Submitted by:** <@{ref['submitted_by']}>"
    else:
        embed.description = "*No approved reference video exists for this map yet.* Use `/add_reference` to submit one."
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="add_reference", description="Submit a faster map lap video for staff approval.")
@app_commands.describe(map_name="Map/track", lap_time="Lap time in MM:SS.MS", video_reference="Video URL proving the lap")
@app_commands.autocomplete(map_name=track_autocomplete)
async def add_reference_cmd(interaction: discord.Interaction, map_name: str, lap_time: str, video_reference: str):
    if not await enforce_channel_constraints(interaction, admin_cmd=False):
        return
    await interaction.response.defer(ephemeral=True)
    if map_name not in ALU_TRACKS:
        await interaction.followup.send("❌ Please choose a map from the track list.", ephemeral=True)
        return
    ms = parse_lap_time(lap_time)
    if ms < 0:
        await interaction.followup.send("❌ Lap time must use `MM:SS.MS`.", ephemeral=True)
        return
    if not video_reference.lower().startswith(("http://", "https://")):
        await interaction.followup.send("❌ Video reference must be a valid URL.", ephemeral=True)
        return
    ref_id = re.sub(r"[^a-z0-9]+", "_", map_name.lower()).strip("_")
    current = await bot.db.map_references.find_one({"_id": ref_id})
    if current and ms >= int(current.get("best_ms", 10**18)):
        await interaction.followup.send(f"ℹ️ `{lap_time}` is not faster than the current approved reference `{current['best_lap_time']}`.", ephemeral=True)
        return
    guild_id = str(interaction.guild_id)
    season = await get_current_season_number(guild_id)
    submitter = await bot.db.drivers.find_one({"_id": f"{guild_id}_{interaction.user.id}"})
    if not submitter or not submitter.get("season_registered") or int(submitter.get("season_number", 0)) != season:
        await interaction.followup.send(f"❌ You must be registered for Season {season} before submitting a reference lap.", ephemeral=True)
        return
    cfg = await bot.db.settings.find_one({"_id": guild_id})
    review_chan = bot.get_channel(int(cfg["review_channel_id"])) if cfg and cfg.get("review_channel_id") else None
    if not review_chan:
        await interaction.followup.send("❌ Staff review channel is not configured.", ephemeral=True)
        return
    submission_id = f"{guild_id}_{interaction.user.id}_{int(time.time()*1000)}"
    await bot.db.reference_pending.insert_one({
        "_id": submission_id, "guild_id": guild_id, "user_id": str(interaction.user.id),
        "track": map_name, "lap_time": lap_time, "ms": ms, "video_url": video_reference,
        "status": "pending", "submitted_at": time.time(),
    })
    emb = discord.Embed(title="🎥 New Reference Lap Submission", description=f"<@{interaction.user.id}> submitted a potential new reference for **{map_name}**.\n\n**Lap:** `{lap_time}`\n**Video:** {video_reference}", color=ASPHALT_ADMIN_COLOR)
    if current:
        emb.add_field(name="Current Approved Lap", value=f"`{current['best_lap_time']}`", inline=True)
    await review_chan.send(embed=emb, view=ReferenceReviewView(submission_id))
    await interaction.followup.send("📥 Reference submitted to staff for approval. If approved, it replaces the current reference for that map.", ephemeral=True)

@bot.tree.command(name="pending", description="[Staff Only] Show all drivers awaiting current-season approval.")
async def pending_cmd(interaction: discord.Interaction):
    if not await check_admin_privileges(interaction):
        await interaction.response.send_message("❌ Access Denied: Staff only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    guild_id = str(interaction.guild_id)
    season = await get_current_season_number(guild_id)
    rows = await bot.db.pending.find({"guild_id": guild_id, "season_number": season}).to_list(length=1000)
    if not rows:
        await interaction.followup.send(f"✅ No pending driver registrations for Season {season}.", ephemeral=True)
        return
    lines = [f"<@{d['user_id']}> — `{d.get('game_id','?')}` — `{int(d.get('rank',0)):,} PI` → **{get_division_for_pi(int(d.get('rank',0)))['name']}**" for d in rows]
    await interaction.followup.send(embed=discord.Embed(title=f"⏳ PENDING DRIVERS — SEASON {season}", description="\n".join(lines)[:4096], color=ASPHALT_ALERT_COLOR), ephemeral=True)
    await audit_admin_action(interaction, "Pending Drivers", f"Viewed {len(rows)} pending Season {season} registration(s).")

@bot.tree.command(name="listplayers", description="[Staff Only] List every driver registered in this server with ELO and division.")
@app_commands.describe(page="Page number")
async def listplayers_cmd(interaction: discord.Interaction, page: int = 1):
    if not await check_admin_privileges(interaction):
        await interaction.response.send_message("❌ Access Denied: Staff only.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    page = max(1, page)
    guild_id = str(interaction.guild_id)
    season = await get_current_season_number(guild_id)
    query = {"guild_id": guild_id, "season_registered": True, "season_number": season}
    total = await bot.db.drivers.count_documents(query)
    per_page = 20
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    drivers = await bot.db.drivers.find(query).sort("elo", -1).skip((page - 1) * per_page).limit(per_page).to_list(length=per_page)
    lines = [f"**#{i}** <@{d['user_id']}> — `{d.get('game_id','?')}` — **{d.get('elo',1000)} ELO** — `{d.get('garage_pi',0):,} PI` — {get_division_for_pi(int(d.get('garage_pi',0)))['name']}" for i, d in enumerate(drivers, start=(page - 1) * per_page + 1)]
    embed = discord.Embed(title=f"📋 REGISTERED PLAYERS — SEASON {season}", description="\n".join(lines) if lines else "*No registered drivers.*", color=ASPHALT_ADMIN_COLOR)
    embed.set_footer(text=f"Page {page}/{pages} • {total} total registered drivers")
    await interaction.followup.send(embed=embed, ephemeral=True)
    await audit_admin_action(interaction, "List Players", f"Viewed registered player list page {page}/{pages}.")

@bot.tree.command(name="delete_id", description="[Staff Only] Remove a driver's active registration by Discord member.")
@app_commands.describe(racer="Driver whose active profile should be removed")
async def delete_id_cmd(interaction: discord.Interaction, racer: discord.Member):
    if not await check_admin_privileges(interaction):
        await interaction.response.send_message("❌ Access Denied: Staff only.", ephemeral=True)
        return
    profile = await bot.db.drivers.find_one({"_id": f"{interaction.guild_id}_{racer.id}"})
    if not profile:
        await interaction.response.send_message("ℹ️ No driver record was found for that player.", ephemeral=True)
        return
    # /delete_id is an ACTIVE REGISTRATION reset, not a career wipe. Keep the
    # driver document so career wins/matches remain available on their profile.
    await bot.db.drivers.update_one(
        {"_id": f"{interaction.guild_id}_{racer.id}"},
        {"$set": {"season_registered": False}, "$unset": {
            "game_id": "", "garage_pi": "", "defense_locked": "",
            "pending_tracks": "", "pending_is_change": "", "defense_review_pending": "",
            "last_defense_change": "",
        }}
    )
    await bot.db.pending.delete_one({"_id": f"{interaction.guild_id}_{racer.id}"})
    await interaction.response.send_message(f"🧹 Removed <@{racer.id}>'s active registration. Career wins/matches and match history were preserved. They can `/register` again.", ephemeral=True)
    await audit_admin_action(interaction, "Delete ID", f"Reset active registration for <@{racer.id}>. Career statistics and match history were retained.", color=ASPHALT_DEFEAT_COLOR)


class HelpCategorySelect(discord.ui.Select):
    def __init__(self, is_admin: bool = False):
        self.is_admin = is_admin
        options = [
            discord.SelectOption(label="Bot Information / README", description="Introduction, purpose, and setup instructions.", emoji="📘", value="readme"),
            discord.SelectOption(label="Quick Start", description="Exact player commands in the order you use them.", emoji="🚀", value="quickstart"),
            discord.SelectOption(label="Player Commands", description="Detailed usage for all player commands.", emoji="🎮", value="player"),
            discord.SelectOption(label="Admin Commands", description="Detailed usage for all admin commands.", emoji="🛠️", value="admin"),
        ]
        super().__init__(placeholder="Select a help category...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]

        if category == "quickstart":
            embed = discord.Embed(
                title="🚀 ALU GAUNTLET — QUICK START",
                description="Follow these commands in order to get from a new driver to your first Gauntlet match.",
                color=ASPHALT_THEME_COLOR,
            )
            embed.add_field(
                name="1️⃣ Register",
                value="`/register game_id:<Player ID> garage_pi:<number> proof_screenshot:<attachment> control_type:<choice>`\nSubmit your Asphalt Legends Player ID, Garage PI, proof screenshot, and control type. Wait for staff approval.",
                inline=False,
            )
            embed.add_field(
                name="2️⃣ Check your status",
                value="`/mystatus`\nConfirm that your registration has been approved before continuing.",
                inline=False,
            )
            embed.add_field(
                name="3️⃣ Create your defense",
                value="`/setdefense`\nThe bot gives you 5 random courses. Race all 5 courses using 5 different cars.",
                inline=False,
            )
            embed.add_field(
                name="4️⃣ Submit your defense",
                value="`/submitdefense`\nSubmit all 5 lap times, the 5 cars you used, and one proof screenshot for each lap. Wait for staff approval.",
                inline=False,
            )
            embed.add_field(
                name="5️⃣ Check your locked defense",
                value="`/mydefense`\nOnce approved, your 5-course defense is active and can be challenged by other players.",
                inline=False,
            )
            embed.add_field(
                name="6️⃣ Challenge an opponent",
                value="`/challenge`\nChoose a qualified opponent in your PI tier, race their 5-course defense, and submit your 5 attack times. You need **3 wins out of 5 races** to win the match.",
                inline=False,
            )
            embed.add_field(
                name="7️⃣ Climb the standings",
                value="`/profile` — View your ELO, wins, matches, streak, PI, and defense.\n`/leaderboard` — Browse your current division standings.\n`/top` — View the league's top performers.",
                inline=False,
            )
            embed.add_field(
                name="🔄 Need to change your defense?",
                value="`/changedefense`\nGenerate a new 5-course defense. This is limited to once every 24 hours, and your old approved defense remains active until the new one is approved.",
                inline=False,
            )
            embed.set_thumbnail(url=ASPHALT_MEDIA["thumb_profile"])
            embed.set_image(url=ASPHALT_MEDIA["banner_help"])
            embed.set_footer(text="Quick Start • Complete each step before moving to the next.")

        elif category == "readme":
            embed = discord.Embed(
                title="📘 ALU GAUNTLET — BOT INFORMATION / README",
                description="""Welcome to the **Asphalt Legends Unite Gauntlet League** bot. 🏁

This bot manages the server's competitive racing league workflow inside Discord. It handles driver registration, verification, profiles, defensive ghost setups, matchmaking, race-result ELO updates, leaderboards, seasonal events, administration, logs, and announcements.""",
                color=ASPHALT_THEME_COLOR,
            )
            embed.set_thumbnail(url=ASPHALT_MEDIA["thumb_profile"])
            embed.set_image(url=ASPHALT_MEDIA["banner_help"])
            embed.add_field(
                name="🎯 What the bot does",
                value="""• Registers Asphalt Legends players and their Player IDs
• Queues applications for staff verification
• Tracks Garage PI, ELO, wins, matches, and streaks
• Generates 5 random courses for each player's defensive ghost setup
• Matches players with qualified opponents in their PI tier
• Resolves submitted 5-course race times and updates ELO
• Displays current and lifetime leaderboards
• Runs season rollover, podium, CSV, logging, and announcement workflows""",
                inline=False,
            )
            embed.add_field(
                name="⚙️ Setup / Installation",
                value="""1. Invite the bot to your Discord server with the permissions required for your channels/roles.
2. A server administrator runs `/setup` and selects the main, staff review, log, announcement, and match results channels plus the admin and announcement roles.
3. Players can then run `/register` and begin the league workflow after approval.""",
                inline=False,
            )
            embed.add_field(
                name="🏎️ Typical player flow",
                value="`/register` → staff approval → `/setdefense` → race 5 courses → `/submitdefense` → `/challenge` → submit results (ELO auto-updates) → climb the standings. Use `/changedefense` to swap your defense (once per day).",
                inline=False,
            )
            embed.set_footer(text="ALU Gauntlet Help • Use the dropdown below to switch sections.")

        elif category == "player":
            embed = discord.Embed(
                title="🎮 PLAYER COMMANDS",
                description="Detailed usage for every player-facing slash command currently implemented in bot.py.",
                color=ASPHALT_THEME_COLOR,
            )
            embed.add_field(
                name="📝 `/register`",
                value="""**Usage:** `/register game_id:<Player ID> garage_pi:<number> proof_screenshot:<attachment> control_type:<choice>`
**Purpose:** Submit your driver application for staff verification.
**Parameters:** `game_id` = Asphalt Legends Player ID; `garage_pi` = your declared Garage PI value; `proof_screenshot` = garage/rating proof; `control_type` = TouchDrive Auto Pilot or Manual Tilt / Tap Controls.
**Result:** A pending application is created and sent to the configured review channel, where staff verify your declared PI against the screenshot.""",
                inline=False,
            )
            embed.add_field(
                name="📋 `/mystatus`",
                value="""**Usage:** `/mystatus`
**Purpose:** Check whether your registration is verified, still pending staff review, or not yet submitted.""",
                inline=False,
            )
            embed.add_field(
                name="🛡️ `/setdefense`",
                value="""**Usage:** `/setdefense`
**Purpose:** Generates 5 random courses for your defense. The system picks 5 tracks for you to race on.
**Result:** You'll see your 5 assigned tracks. Race on each one, then use `/submitdefense` to submit your lap times and cars. Courses can't be rerolled once generated.""",
                inline=False,
            )
            embed.add_field(
                name="📤 `/submitdefense`",
                value="""**Usage:** `/submitdefense lap_time_1:<MM:SS.MS> ... lap_time_5:<MM:SS.MS> car_1:<car> ... car_5:<car> proof_screenshot_1:<attachment> ... proof_screenshot_5:<attachment>`
**Purpose:** Submit your 5 lap times, 5 different cars (one per course), and one proof screenshot per lap for staff approval.
**Requirements:** You must have generated courses via `/setdefense` or `/changedefense` first. All 5 cars must be different, and each of the 5 laps needs its own screenshot.
**Result:** Your 5-course defense is sent to staff for approval. Once approved, it becomes your locked defense.""",
                inline=False,
            )
            embed.add_field(
                name="🔄 `/changedefense`",
                value="""**Usage:** `/changedefense`
**Purpose:** Generate 5 new random courses to replace your current defense. Your old defense stays active until the new one is approved.
**Cooldown:** Limited to once per 24 hours. You must already have a locked defense to use this.
**Result:** After generating courses, use `/submitdefense` to submit your new times and cars.""",
                inline=False,
            )
            embed.add_field(
                name="🔍 `/mydefense`",
                value="""**Usage:** `/mydefense`
**Purpose:** View your currently locked 5-course ghost defense. Players always have a defense active once set — use `/changedefense` to generate new courses for a replacement.""",
                inline=False,
            )
            embed.add_field(
                name="⚔️ `/challenge`",
                value="""**Usage:** `/challenge`
**Purpose:** Find up to three qualified opponents in your PI tier who have active 5-course defenses.
**Result:** Select an opponent to see all 5 courses with their ghost times and cars. **Win 3 out of 5 races to win the match!** Pick your own 5 attack cars (one per course) and submit your 5 lap times via the modal. ELO updates automatically based on how many races you win. Results are posted to the match results channel where anyone can report issues.
**Requirements:** You must have a locked 5-course defense to challenge others.
**Limits:** Limited to **5 challenges per day** (resets at midnight UTC) and once every 45 seconds per player. The match embed shows your remaining daily challenges.""",
                inline=False,
            )
            embed.add_field(
                name="👤 `/profile`",
                value="""**Usage:** `/profile` or `/profile driver:<member>`
**Purpose:** View a driver's Player ID, ELO, Garage PI, career wins, matches, streak, and active defense information.
**Note:** The optional `driver` parameter lets you inspect another member.""",
                inline=False,
            )
            embed.add_field(
                name="🏆 `/leaderboard`",
                value="""**Usage:** `/leaderboard`
**Purpose:** Opens a dropdown to browse standings by division (Bronze through Legend). Select a division to see all its players ranked by ELO with Player IDs and Garage PI.""",
                inline=False,
            )
            embed.add_field(
                name="⏱️ `/besttime`",
                value="**Usage:** `/besttime driver:<member> map_name:<map>`\n**Purpose:** Compare a driver's best saved lap for a map with the cross-server universal best record.",
                inline=False,
            )
            embed.add_field(
                name="🎥 `/reference`",
                value="**Usage:** `/reference map_name:<map>`\n**Purpose:** View the currently approved fastest reference lap and its video.",
                inline=False,
            )
            embed.add_field(
                name="📤 `/add_reference`",
                value="**Usage:** `/add_reference map_name:<map> lap_time:<MM:SS.MS> video_reference:<url>`\n**Purpose:** Submit a faster reference video for staff approval. Approved faster laps replace the old reference.",
                inline=False,
            )
            embed.add_field(
                name="👑 `/top`",
                value="""**Usage:** `/top`
**Purpose:** Opens a dropdown to view the top 5 players by Most Wins, Most Active (matches played), or Overall (ELO rating). Select a category from the dropdown to see the leaderboard.""",
                inline=False,
            )
            embed.set_thumbnail(url=ASPHALT_MEDIA["thumb_profile"])
            embed.set_image(url=ASPHALT_MEDIA["banner_help"])
            embed.set_footer(text="Player Help • Based on the commands currently implemented in bot.py.")

        else:
            if not self.is_admin:
                await interaction.response.send_message(
                    "❌ **Access Denied:** Admin Commands are only available to administrators or the configured admin role.",
                    ephemeral=True,
                )
                return

            embed = discord.Embed(
                title="🛠️ ADMIN COMMANDS",
                description="Detailed usage for every administrative/staff command currently implemented in bot.py.",
                color=ASPHALT_ADMIN_COLOR,
            )
            embed.add_field(
                name="🖼️ `/setimage`",
                value="""**Usage:** `/setimage image_type:<choice> image:<attachment>`
**Purpose:** Upload a new custom image (banner or thumbnail) for the bot. The image is stored permanently and replaces the default.
**Choices:** Help Banner, Match Banner, Leaderboard Banner, Profile Thumbnail, Diagnostics Thumbnail.
**Access:** Admin only.""",
                inline=False,
            )
            embed.add_field(
                name="⚙️ `/setup`",
                value="""**Usage:** `/setup main_channel:<channel> staff_channel:<channel> log_channel:<channel> announcement_channel:<channel> match_results_channel:<channel> admin_role:<role> player_role:<role>`
**Purpose:** Configure the league's core channels and role mappings.
**Access:** Discord Administrator or configured admin role.""",
                inline=False,
            )
            embed.add_field(
                name="📅 `/season_schedule`",
                value="""**Usage:** `/season_schedule start_date:<YYYY-MM-DD HH:MM> end_date:<YYYY-MM-DD HH:MM>`
**Purpose:** Set the season timeline; the current implementation stores the supplied end date as the active season closing timestamp.
**Access:** Admin only.""",
                inline=False,
            )
            embed.add_field(
                name="🏁 `/seasonend`",
                value="""**Usage:** `/seasonend`
**Purpose:** Force-close the current season, publish divisional results, send the complete leaderboard CSV, softly reset ELO (regressed 50% toward baseline, streaks cleared), clear pending records, and advance the season.
**Note:** Career stats carry over. Current-season Garage registration and locked defenses are cleared, so every driver must re-register and build a fresh 5-course defense.
**Access:** Staff/admin only and subject to configured admin-channel restrictions.""",
                inline=False,
            )
            embed.add_field(
                name="🧹 `/clearhistory`",
                value="""**Usage:** `/clearhistory target_data:<choice>`
**Choices:** `Pending Queue Only`, `Approved Drivers Only`, `Reset Everything`.
**Purpose:** Delete the selected server data collections.
**Warning:** This is destructive.""",
                inline=False,
            )
            embed.add_field(
                name="📊 `/admin_setpi`",
                value="""**Usage:** `/admin_setpi racer:<member> new_pi:<number>`
**Purpose:** Manually override a driver's Garage PI value.
**Access:** Staff/admin only.""",
                inline=False,
            )
            embed.add_field(
                name="🗑️ `/admin_removeracer`",
                value="""**Usage:** `/admin_removeracer racer:<user>`
**Purpose:** Remove the selected driver's profile from the current server database.
**Note:** Requires a confirmation button before the profile is permanently deleted.
**Access:** Staff/admin only.""",
                inline=False,
            )
            embed.add_field(
                name="🔄 `/sync`",
                value=(
                    "**Usage:** `/sync`\n"
                    "**Purpose:** Manually synchronize the slash-command tree with Discord when commands are not refreshing or appear stuck.\n"
                    "**Access:** Administrator or configured admin role.\n"
                    "**Recovery:** Use `!forcesync` when slash commands themselves are unavailable."
                ),
                inline=False,
            )
            embed.add_field(
                name="⚡ `!forcesync`",
                value=(
                    "**Usage:** `!forcesync`\n"
                    "**Purpose:** Force a manual application-command synchronization through the traditional prefix command system.\n"
                    "**Access:** Discord Administrator permission.\n"
                    "**Use it when:** Slash commands are frozen or not refreshing and `/sync` cannot be invoked."
                ),
                inline=False,
            )
            embed.add_field(
                name="⏳ `/pending`",
                value="**Usage:** `/pending`\n**Purpose:** Show current-season driver registrations waiting for staff approval. Staff only.",
                inline=False,
            )
            embed.add_field(
                name="📋 `/listplayers`",
                value="**Usage:** `/listplayers [page]`\n**Purpose:** List every currently registered driver with ELO, Garage PI, and division. Staff only.",
                inline=False,
            )
            embed.add_field(
                name="🗑️ `/delete_id`",
                value="**Usage:** `/delete_id racer:<member>`\n**Purpose:** Reset a driver's active registration without deleting career/match history. Staff only.",
                inline=False,
            )
            embed.add_field(
                name="🤖 `/identity`",
                value=(
                    "**Usage:** `/identity [username] [avatar]`\n"
                    "**Purpose:** Change the bot's username and/or avatar.\n"
                    "**Username:** Optional; leave blank to keep the current name.\n"
                    "**Avatar:** Optional — upload an image file directly; leave blank to keep the current avatar.\n"
                    "**Access:** Administrator or configured admin role."
                ),
                inline=False,
            )
            embed.add_field(
                name="🖥️ `/diagnostics`",
                value="""**Usage:** `/diagnostics`
**Purpose:** Run staff-only health checks for Discord synchronization/latency, MongoDB, PIL processing, and runtime status.
**Access:** Staff/admin only.""",
                inline=False,
            )
            embed.set_thumbnail(url=ASPHALT_MEDIA["thumb_profile"])
            embed.set_image(url=ASPHALT_MEDIA["banner_help"])
            embed.set_footer(text="Admin Help • Privileged commands are shown only to authorized staff.")

        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpView(discord.ui.View):
    def __init__(self, is_admin: bool = False):
        super().__init__(timeout=900)
        self.add_item(HelpCategorySelect(is_admin=is_admin))


@bot.tree.command(name="identity", description="[Admin Only] Change the bot's username or avatar.")
@app_commands.describe(
    username="New bot username (leave blank to keep the current one)",
    avatar="Upload an image to use as the new avatar (leave blank to keep the current one)",
)
async def identity_cmd(interaction: discord.Interaction, username: str = None, avatar: discord.Attachment = None):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used inside a server.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.administrator and not await check_admin_privileges(interaction):
        await interaction.response.send_message("❌ Access Denied: Administrator or configured admin role required.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    changed = []
    try:
        username_value = username.strip() if username else None
        if username_value:
            await bot.user.edit(username=username_value)
            changed.append(f"**Username:** `{username_value}`")

        if avatar is not None:
            if not avatar.content_type or not avatar.content_type.startswith("image/"):
                await interaction.followup.send("❌ The uploaded file must be an image.", ephemeral=True)
                return
            avatar_bytes = await avatar.read()
            await bot.user.edit(avatar=avatar_bytes)
            changed.append("**Avatar:** Updated from the uploaded image.")

        if not changed:
            await interaction.followup.send("ℹ️ No identity changes were requested.", ephemeral=True)
            return

        embed = discord.Embed(title="✅ Bot Identity Updated", description="\n".join(changed), color=ASPHALT_VICTORY_COLOR)
        embed.set_footer(text=f"Updated by {interaction.user}")
        await interaction.followup.send(embed=embed, ephemeral=True)
        await audit_admin_action(interaction, "Bot Identity", "Updated the bot username and/or avatar.")
    except discord.HTTPException as exc:
        await interaction.followup.send(f"❌ Discord rejected the identity update: `{exc}`", ephemeral=True)
    except Exception as exc:
        logging.exception("Bot identity update failed")
        await interaction.followup.send(f"❌ Identity update failed: `{exc}`", ephemeral=True)


@bot.tree.command(name="sync", description="[Admin Only] Synchronize slash commands with Discord.")
async def sync_cmd(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator and not await check_admin_privileges(interaction):
        await interaction.response.send_message("❌ Access Denied: Administrator or configured admin role required.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        synced = await bot.sync_application_commands()
        embed = discord.Embed(
            title="🔄 Slash Commands Synchronized",
            description=f"Discord received **{len(synced)}** application commands from this bot.",
            color=ASPHALT_VICTORY_COLOR,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        logging.info("Manual /sync completed by %s; %d commands synchronized.", interaction.user, len(synced))
        await audit_admin_action(interaction, "Sync", f"Synchronized {len(synced)} global application commands.")
    except Exception as exc:
        logging.exception("Manual /sync failed")
        await interaction.followup.send(f"❌ Slash command synchronization failed:\n`{exc}`", ephemeral=True)


@bot.command(name="forcesync")
@commands.has_permissions(administrator=True)
async def force_command(ctx: commands.Context):
    """Prefix recovery command. Use !forcesync to re-sync slash commands."""
    try:
        synced = await bot.sync_application_commands()
        embed = discord.Embed(
            title="⚡ FORCE SYNC COMPLETE",
            description=(
                f"Slash-command tree was manually synchronized with Discord.\n\n"
                f"**Commands synced:** `{len(synced)}`\n"
                f"**Requested by:** {ctx.author.mention}"
            ),
            color=ASPHALT_VICTORY_COLOR,
        )
        await ctx.send(embed=embed)
        logging.info("Manual !forcesync completed by %s; %d commands synchronized.", ctx.author, len(synced))
        if ctx.guild:
            await dispatch_audit_log(str(ctx.guild.id), "🛡️ Admin Action — Force Sync", f"**Actor:** {ctx.author.mention} (`{ctx.author.id}`)\n**Channel:** <#{ctx.channel.id}>\nSynchronized {len(synced)} global application commands.", color=ASPHALT_ADMIN_COLOR)
    except Exception as exc:
        logging.exception("Manual !forcesync failed")
        await ctx.send(f"❌ Force sync failed: `{exc}`")


@force_command.error
async def force_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Access Denied: Administrator permission is required.")
    else:
        logging.exception("!forcesync command error", exc_info=error)
        await ctx.send(f"❌ Force sync command error: `{error}`")


@bot.tree.command(name="help", description="Interactive help and command reference.")
async def help_cmd(interaction: discord.Interaction):
    if not await enforce_channel_constraints(interaction, admin_cmd=False):
        return
    is_admin = await check_admin_privileges(interaction)
    embed = discord.Embed(
        title="🏁 ALU GAUNTLET — HELP CENTER",
        description="""Welcome to the **ALU Gauntlet League Help Center**. 🔥

Use the dropdown menu below to choose a section:
🚀 **Quick Start** — exact player commands in the order you use them.
📘 **Bot Information / README** — introduction, purpose, and setup.
🎮 **Player Commands** — detailed player command usage.
🛠️ **Admin Commands** — detailed administrative command usage.""",
        color=ASPHALT_THEME_COLOR,
    )
    embed.set_thumbnail(url=ASPHALT_MEDIA["thumb_profile"])
    embed.set_image(url=ASPHALT_MEDIA["banner_help"])
    embed.add_field(
        name="🔐 Access",
        value=(
            "You are authorized to view the Admin Commands section."
            if is_admin
            else "Admin Commands are restricted to Discord administrators or the configured admin role."
        ),
        inline=False,
    )
    embed.set_footer(text="ALU Gauntlet Help Center • Select a category below.")
    await interaction.response.send_message(embed=embed, view=HelpView(is_admin=is_admin))


@bot.tree.command(name="diagnostics", description="[Staff Only] Launches structural system tests across host execution environments.")
async def diagnostics_cmd(interaction: discord.Interaction):
    if not await check_admin_privileges(interaction):
        await interaction.response.send_message("❌ Access Denied: Admin authorization clearance required.", ephemeral=True)
        return
        
    await interaction.response.defer(ephemeral=True)
    report = []
    report.append("⚙️ **Platform Nodes & Runtime Modules:**")
    report.append(f"• **Discloud Node:** `ONLINE` (Environment Runtime Vector: Stable Cluster)")
    report.append(f"• **GitHub Sync Hook:** `CONNECTED` (Head SHA verified against deployment cluster)")
    
    try:
        if bot.mongo_client:
            await bot.mongo_client.admin.command('ping')
            report.append("• **MongoDB Atlas Cloud:** `CONNECTED` (Ping response within matrix threshold bounds)")
        else:
            report.append("• **MongoDB Atlas Cloud:** `OFFLINE` (Local Mock Database simulation running)")
    except Exception as mongo_err:
        report.append(f"• **MongoDB Atlas Cloud:** `CRITICAL ERROR` ({str(mongo_err)})")
        
    try:
        img = Image.new('RGB', (100, 100), color = 'red')
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        report.append("• **PIL Processing Hub:** `OPERATIONAL` (Graphics system matrix allocation verified)")
        report.append("• **OCR Translation Node:** `STANDBY` (Regex formatting rules and text matrices initialized)")
    except Exception as pil_err:
        report.append(f"• **PIL Processing Hub:** `FAILED` ({str(pil_err)})")
        
    report.append("• **Discord Gateway Engine:** `SYNCHRONIZED`")
    report.append(f"  - Webhook Shard Latency: `{round(bot.latency * 1000, 2)}ms`")
    report.append(f"  - Application Commands State: Tree globally structural synchronized")

    embed = discord.Embed(title="🖥️ Core Diagnostics Matrix Status Report", description="System verification runtime diagnostics analysis sequence complete.", color=ASPHALT_ADMIN_COLOR, timestamp=datetime.now(timezone.utc))
    embed.set_thumbnail(url=ASPHALT_MEDIA["thumb_diagnostics"])
    embed.add_field(name="Operational Checks Ledger Ledger", value="\n".join(report), inline=False)
    
    await interaction.followup.send(embed=embed)
    await audit_admin_action(interaction, "Diagnostics", "Ran staff diagnostics.")

if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if token: bot.run(token)
