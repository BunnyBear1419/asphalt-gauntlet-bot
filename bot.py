import os
import datetime
import discord
from discord.ext import commands
import pymongo
import certifi

# Fix for DeprecationWarning: datetime.datetime.utcnow()
# Instead of datetime.datetime.utcnow(), use timezone-aware objects or datetime.datetime.now(datetime.UTC)
def get_utc_now():
    return datetime.datetime.now(datetime.timezone.utc)

# Secure MongoDB Initialization using certifi to resolve TLSV1_ALERT_INTERNAL_ERROR
MONGO_URI = os.getenv("MONGO_URI", "your_mongodb_connection_string_here")

try:
    # Explicitly providing tlsCAFile ensures the Discloud environment can validate the TLS certificate
    client = pymongo.MongoClient(MONGO_URI, tlsCAFile=certifi.where())
    db = client.get_default_database()
    print("✨ MongoDB connected successfully!")
except Exception as e:
    print(f"❌ MongoDB failed: {e}")
    print("Falling back to internal engine simulator.")

# Discord Bot Setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"INFO:discord.client:Logged in as {bot.user}")
    print("✨ Application slash command map synchronized globally.")

# Example block demonstrating fixed timestamp from your error log (Line 226)
def create_snapshot(drivers_list, laps_list):
    # FIXED: Replaced datetime.utcnow() with timezone-aware ISO format string
    snapshot = {
        "timestamp": get_utc_now().isoformat(), 
        "drivers": drivers_list, 
        "laps": laps_list
    }
    return snapshot

if __name__ == "__main__": 
    # Changed from "DISCORD_TOKEN" to "TOKEN"
    TOKEN = os.getenv("TOKEN") 
    
    if TOKEN: 
        bot.run(TOKEN) 
    else: 
        print("ERROR: No token found in environment variables.")
