import os
import re
import time
import logging
import asyncio
import aiohttp
import urllib.parse
import json
import base64
import random
import csv
from datetime import datetime, timezone
from difflib import SequenceMatcher
from dotenv import load_dotenv
import discord
from discord import app_commands
from discord.ext import commands, tasks
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError
from PIL import Image
import io
import sys
import platform

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
    # Classic & Base Maps — each map includes both listed Gauntlet routes.
    "Auckland - Hairpin Finish", "Auckland - Straight Sprint",
    "Buenos Aires - La Boca", "Buenos Aires - Water Run",
    "Cairo - A King's Revival", "Cairo - Gezira Island",
    "Greenland - Ice Breakers", "Greenland - Out of the Center",
    "Himalayas - Freefall", "Himalayas - Leap of Faith",
    "Nevada - Bridge to Bridge", "Nevada - Tunnel Sprint",
    "New York - A Run In The Park", "New York - Wall Street Ride",
    "Norway - Future Fusion", "Norway - Rocketing to the Future",
    "Osaka - Meiji Rush", "Osaka - Namba Park",
    "Paris - Along the Seine", "Paris - Notre Dame",
    "Rome - Roman Byroads", "Rome - Roman Tumble",
    "San Francisco - Railroad Bustle", "San Francisco - The Tunnel",
    "Scotland - Ghost Ships", "Scotland - Rocky Valley",
    "Shanghai - Double Roundabout", "Shanghai - Paris of the East",
    "Singapore - Urban Rush", "Singapore - Waterslide Whirl",
    "The Caribbean - Hell Vale", "The Caribbean - Resort Dash",
    "Tuscany - Riverine Launch", "Tuscany - Vineyard Voyage",
    "U.S. Midwest - It's A Twister!", "U.S. Midwest - Trainspotter",
    "Chicago - Echo Drift", "Chicago - Ironclad Descent",
    "India - Gravel Grooves", "India - Rock Terrain",
    "Mt. Fuji - Bullet Train Sprint", "Mt. Fuji - Countryside Sprint",
    "San Diego - Container Chaos", "San Diego - Pacific Rampage"
]

# Map icon assets supplied in the Gauntlet map reference sheet (matched to each map by city).
# The assets are embedded so the bot remains portable as a single Python file.
ALU_MAP_ICONS = {
    'Auckland': 'iVBORw0KGgoAAAANSUhEUgAAAIwAAABFCAMAAACv+f5wAAAAwFBMVEXt6uvg3+bh2uDM2ezf0tjQ0uPF0ei30ezCyOLRxs2xxumzxN+7vdGrvOC1tMKzoZSbwemauOGOseSXsNaOqNmHntGVnaSNjZdhsupso+BznNhYnN5okdZvjLdTj9Y',
    'Buenos Aires': 'iVBORw0KGgoAAAANSUhEUgAAAIwAAABFCAMAAACv+f5wAAAAwFBMVEXu8vjv7uri5vDn39jY4ezM3+/Q1+O+1e3XyLfEyNKwze6xwt3JsZiwr7S5nIqrmY6dx/CVv+yQuOaBtuuNrdd7rOV0quVnqOaFnMKblI9uod5rmNRan+Faldp',
    'Cairo': 'iVBORw0KGgoAAAANSUhEUgAAAIwAAABFCAMAAACv+f5wAAAAwFBMVEX87dD86Lrv3s/53qru07v20IHtwprwwG7c19fdzsHbwrLevZPQz9fQwrzJyNGqyNXWtaHhsm7Ita7KsJPKo4vQolDElmDBiVirq7Osl4CqhXSrgUaWnrKUgmh/jaBEjL',
    'Greenland': 'iVBORw0KGgoAAAANSUhEUgAAAIwAAABFCAMAAACv+f5wAAAAwFBMVEX9/v31+/3y9vnv7/Pm8vnm6/LU8frV6vfg4+3Y4u/Q4fLC4fTR2OfC1urCz+S+xtyo4Pmk0vCxxeCcxuipu9iYuNqcrcuQq898yfN7tuaFptJ1pttIvPE/r+1KpO',
    'Himalayas': 'iVBORw0KGgoAAAANSUhEUgAAAIwAAABFCAMAAACv+f5wAAAAwFBMVEX8/Pz08fXm6/Te4O7Y1uTG0+zFyNvAvMqqx+2out+isdukq7+KvO6Jqt1xs+kyuOyKndGVm6aQiH1/hpRwnNpwjcZtf7Rwc2NdjdJbe7YtiM08eMVRb7VVbIxBbb',
    'Nevada': 'iVBORw0KGgoAAAANSUhEUgAAAIwAAABFCAMAAACv+f5wAAAAwFBMVEX27+Lr3M7ryrbVyMfktqDLtLDXoI7CnpSYweaSrNeonKh/nNFkr+wltOxlmds8muPGiH2uhICQiJqQeoKsamqUZGd/a3V/Wl9kg7pjaIYmidMvcbBiXXVgU2NKVXksV',
    'New York': 'iVBORw0KGgoAAAANSUhEUgAAAIwAAABFCAMAAACv+f5wAAAAwFBMVEX4+fns7O3b6fbQ4PPV2ty92fjGytfJw5+v0/WlyvKbw/KnvcaGy/aGuu5rxPM6xvSrqbeupnWHp9CPnYuTjYR9jIiHfHR3eHhlpNolotdqf49DgJ9ib5ZmbWJQbIU',
    'Norway': 'iVBORw0KGgoAAAANSUhEUgAAAIwAAABFCAMAAACv+f5wAAAAwFBMVEXz8vLB4PjRzcCnyPDKs4intbe7nHKkmG6UwveRrsxus9orseGFlriLk2hpk8kulMWYhWeVdF96gnp3cmhdgsFmeXVfaYBhZkNJe85GealBa7RIZnoaeagmbKAtZLAiY',
    'Osaka': 'iVBORw0KGgoAAAANSUhEUgAAAIwAAABFCAMAAACv+f5wAAAAwFBMVEX98PXm6/L43evj3Ofz0Ojfzefvy9rRy9Xput7Sttzatc7TtLvapMvJosLKl7/HjLas0vehwe+Vtu2qsMaCvPJ/ru1qsu43veycn8mqiruhlYqdhY5uoOt0j7pYl98Xkt',
    'Paris': 'iVBORw0KGgoAAAANSUhEUgAAAIwAAABFCAMAAACv+f5wAAAAwFBMVEXz8evs5Nne4unP3uvM1eXb08C/0uWy0Ou8x9jVwpqqyuiqwt3OsX+ssK6zmpO7lUKcx+qXwemXut+Mu+aSrdKVqMGSmrWXkFqCuOWBp89xrt49reJ5lsJ8jqNkjrk3ks',
    'Rome': 'iVBORw0KGgoAAAANSUhEUgAAAIwAAABFCAMAAACv+f5wAAAAwFBMVEX69u/t5+Ty5c3n2cLh0L/vxHvmsHfjoGHR0dnRyKnOuIbSn2u7t5G3oXGjp5RitcbSj1a9i1+ji3+kh0yzeU6Zd1ypaT+UZ0mHfVyHbFyEY1KEWUV2aFNSbWd1WE5jWE5',
    'San Francisco': 'iVBORw0KGgoAAAANSUhEUgAAAIwAAABFCAMAAACv+f5wAAAAwFBMVEXq6vTh2+rl0uHN0uvPyefHv+TawMjVsLWfzPagv/GntOCNs/V0u/txrfhBuPxGq/rLmZSelbK+fXmUfZp2mth5hLqBdZttdKhUnfU5mfcRnPkHkfZHf9BNb7',
    'Scotland': 'iVBORw0KGgoAAAANSUhEUgAAAIwAAABFCAMAAACv+f5wAAAAwFBMVEXx9vvV3ue91vWs1frVwKSzxdSgyvifvuSOyPuMwfiLvfaHt/F8v/l7tfRxt/ZXt/nBpIikoHx4q+qJnZuZjGiQe2B4hnV4dWNjqvFfmtZJpOwhovFggI9gcWlIeqI',
    'Shanghai': 'iVBORw0KGgoAAAANSUhEUgAAAIwAAABFCAMAAACv+f5wAAAAwFBMVEX08/bf4u7Y1uLE0uvEyt7QuLG0xeWzvNOow+qlu+Ghtd2ers+TsuGQqdiHqt5rrN/JlYeWkaOEotiEjaZ0oNx0nNNxksZzepJjmNdhj81TjdE0jtBSfLZbdJUzfMU',
    'Singapore': 'iVBORw0KGgoAAAANSUhEUgAAAIwAAABFCAMAAACv+f5wAAAAwFBMVEX28/Pd5fXX1uXA0/K1x/DDxc22tdC5rZGVwfOQteuJqeOWo7FxsflqpvNepPk4pO2NkrKSjW1blN9piLJ2d5V5cFBXdKlaaGxCj+oUid43eMUKeNlBZp0oZrEJas',
    'The Caribbean': 'iVBORw0KGgoAAAANSUhEUgAAAIwAAABFCAMAAACv+f5wAAAAwFBMVEXz/Pzp8ffl7+zs39TP8PO27vPH3+yo3+rf09Ppzraqzvqwy9u9vsSZvvCuq6Crk2J53ux/xuuItepzsulU0+cfyOhHsugJsuV0nMd7kohAo/FBktEfnOkDn9',
    'Tuscany': 'iVBORw0KGgoAAAANSUhEUgAAAIwAAABFCAMAAACv+f5wAAAAwFBMVEXv7t/i1rTiw5DFv6/NsIGxrqnNmWasnHaRqr2PmZsRsukJn+WMjpeUjFBjjL4Ii+W2b02KelN7fF94bEhoeJBrcDlmZkJkXT1TeK5TZWoFguQScblVV05WVy9LVEgq',
    'U.S. Midwest': 'iVBORw0KGgoAAAANSUhEUgAAAIwAAABFCAMAAACv+f5wAAAAwFBMVEXz6eHJ3/XY0ter0ffbw77Ssq6qxu2pudiUyPmLv/WMue2RsOF6ufd0svNms/QsufXPn5u2m6GWocSZk6qzhIebgI2JgqKLeH9pouBwjb9ofLRvdpg9lt4NldF',
    'Chicago': 'iVBORw0KGgoAAAANSUhEUgAAAIwAAABFCAMAAACv+f5wAAAAwFBMVEX18OrZ5/Pd2drD1e7awbS+wdLErKfDmoCrzO+mvuOprcmnmZeTtd9ft+WFl7Q7lsurhG+VgH55h59+eIKPamF8ZmNuanVsWVtXfqpVZoITgsMca6NWVnNZU1BAU3Ei',
    'India': 'iVBORw0KGgoAAAANSUhEUgAAAIwAAABFCAMAAACv+f5wAAAAwFBMVEX54bLxz67ixMLwwI3eq5XvpVPrkVLYkFuxxdKyrMW+mZGbma8wz/Y7rOJHlecJkd/igEnPfVGzfna4eUbGbUTBXzina1KlW0SPc1mPYk2OV0qLT0NyYVFyUUcNgNg8VG',
    'Mt. Fuji': 'iVBORw0KGgoAAAANSUhEUgAAAIwAAABFCAMAAACv+f5wAAAAwFBMVEXu7+ne2tq+2e2ozenLuMGwtc6Uv+iYq86Ewe+Auu15tOt8qdtrsu0ste9mqOktpua4lZWBk7bEc2CEc4dhm+Nkj8hkgKtjZoVLl+sgk+FJgMUsfMg/bKk+XYobbbY',
    'San Diego': 'iVBORw0KGgoAAAANSUhEUgAAAIwAAABFCAMAAACv+f5wAAAAwFBMVEXw7u7f3ejH0e3Y0dDTxMC7xeHWrZS+qZ+sxe2nvumlt9ypo66XuOh0uOyIoswsoNq6j3iTjJe9cVmOcmlyjb5xeZhqZYVvYFVGhs1KcqobhssicsFKYJRQW3E1XJ',
}

def parse_lap_time(time_str):
    """Parse a lap time string in format 'M:SS.sss' to milliseconds, or return -1 if invalid."""
    try:
        # Empty or None string is invalid
        if not time_str:
            return -1
        
        # Must match pattern like "1:23.456"
        match = re.match(r'^(\d+):(\d{2})\.(\d{3})$', time_str)
        if not match:
            return -1
        
        minutes_str, seconds_str, millis_str = match.groups()
        minutes = int(minutes_str)
        seconds = int(seconds_str)
        millis = int(millis_str)
        
        # Validate seconds are in range 0-59
        if seconds >= 60:
            return -1
        
        # Convert to total milliseconds
        total_millis = minutes * 60000 + seconds * 1000 + millis
        return total_millis
    except (ValueError, AttributeError):
        return -1

def format_lap_time(millis):
    """Format milliseconds to lap time string 'M:SS.sss'."""
    minutes = millis // 60000
    remaining = millis % 60000
    seconds = remaining // 1000
    ms = remaining % 1000
    return f"{minutes}:{seconds:02d}.{ms:03d}"

async def claim_active_challenge(guild_id, user_id):
    """
    Claim an active challenge for a user. Returns the updated challenge document if successful,
    or None if the challenge is already processing or doesn't exist.
    """
    guild_user_id = f"{guild_id}_{user_id}"
    
    # Look up the challenge
    challenge = await bot.db.active_challenges.find_one({"_id": guild_user_id})
    
    if challenge is None:
        return None
    
    # If the challenge is active, claim it
    if challenge.get("status") == "active":
        result = await bot.db.active_challenges.update_one(
            {"_id": guild_user_id, "status": "active"},
            {"$set": {"status": "processing", "processing_at": time.time()}}
        )
        if result.modified_count > 0:
            return await bot.db.active_challenges.find_one({"_id": guild_user_id})
        return None
    
    # If the challenge is processing, recover it (refresh the processing_at timestamp)
    if challenge.get("status") == "processing":
        await bot.db.active_challenges.update_one(
            {"_id": guild_user_id},
            {"$set": {"processing_at": time.time()}}
        )
        return await bot.db.active_challenges.find_one({"_id": guild_user_id})
    
    # Any other status means we can't claim it
    return None

async def release_active_challenge(guild_user_id):
    """
    Release an active challenge back to 'active' status so it can be claimed again.
    """
    await bot.db.active_challenges.update_one(
        {"_id": guild_user_id},
        {"$set": {"status": "active"}}
    )

# Placeholder for bot instance (will be initialized in actual Discord bot setup)
bot = None
