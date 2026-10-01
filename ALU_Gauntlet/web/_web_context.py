"""A secure, guild-aware web control center shared with the Discord bot."""
from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from io import BytesIO
import mimetypes
from urllib.parse import urlsplit
import html
import re
import ipaddress
import socket
from typing import Any

from aiohttp import web
import discord
from PIL import Image, ImageOps, UnidentifiedImageError

from .auth import DiscordOAuth, SESSION_COOKIE
from .players import PlayerService
from ..core.core import ALU_TRACKS, has_5_course_defense, submit_registration_application, get_current_season_number, get_division_for_pi
from ..core.match_scoring import apply_rsl_performance_bonus
from ..core.fairness import fair_match_snapshot, build_fairness_review
from ..core.rsl_economy import purchase_daily_ticket, next_ticket_purchase
from ..core.rsl_economy_ledger import recent_coin_transactions
from ..core.gauntlet_progression import FREE_DAILY_TICKETS, MAX_DAILY_TICKETS
from ..core.rsl_activity import collect_overall_activity_stats
from ..core.rsl_language import RSL_LANGUAGES, normalize_language
from ..release import current_release_revision
from ..core.production_controls import is_maintenance_enabled, is_mutating_competition_path, maintenance_message, set_maintenance_mode, record_system_event
from ..core.platform_assurance import redact_document, privacy_export_metadata, readiness_check, public_status_snapshot, performance_bucket, SUSPICIOUS_EVENT_TYPES
from ..core.rsl_reliability import build_reliability_snapshot, create_recovery_checkpoint

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent / "static"
THEMES = ("dark", "light", "ocean", "purple", "crimson", "emerald", "sunset", "graphite")

TIMEZONE_LABELS = (
    ("UTC", "UTC"), ("Eastern Time", "America/New_York"), ("Central Time", "America/Chicago"),
    ("Mountain Time", "America/Denver"), ("Pacific Time", "America/Los_Angeles"),
    ("Alaska Time", "America/Anchorage"), ("Hawaii Time", "Pacific/Honolulu"),
    ("UK / Ireland", "Europe/London"), ("Central Europe", "Europe/Berlin"),
    ("Eastern Europe", "Europe/Bucharest"), ("India", "Asia/Kolkata"),
    ("China / Singapore", "Asia/Shanghai"), ("Japan", "Asia/Tokyo"),
    ("Korea", "Asia/Seoul"), ("Australian Eastern", "Australia/Sydney"),
    ("New Zealand", "Pacific/Auckland"),
)

SETUP_CHANNELS = (
    ("registration_channel_id", "Main / registration channel"),
    ("review_channel_id", "Staff review channel"),
    ("log_channel_id", "Log channel"),
    ("announcement_channel_id", "Announcement channel"),
    ("match_results_channel_id", "Match-results channel"),
)
SETUP_ROLES = (("admin_role_id", "Staff / admin role"), ("player_role_id", "Player role"))

DEFAULT_WEB_BRANDING = {
    "identity": {"name":"Racing Syndicate League","short_name":"RSL","site_title":"Racing Syndicate League","tagline":"Race, Compete, Unite","favicon_url":"/assets/rsl-favicon.png?v=20260922-favicon1","logo_url":"/assets/rsl-shield.png","mobile_logo_url":"/assets/rsl-shield.png"},
    "colors": {"primary":"#25dfff","secondary":"#1878ff","accent":"#ffd22d","background":"#020817","surface":"#061226","text":"#f5f7ff","muted":"#91a5c3"},
    "images": {"hero_url":"/assets/hero.jpg","welcome_url":"/assets/hero.jpg","gauntlet_url":"/assets/hero.jpg","tournament_url":"/assets/hero.jpg","club_url":"/assets/hero.jpg","login_url":"/assets/hero.jpg","background_url":""},
    "links": {"site_logo":"/","website":"https://asph.discloud.app","discord":"https://discord.gg/fmFk8Ejf2H","cashapp":"https://cash.app/","youtube":"","twitch":"","facebook":"","instagram":"","x":"","support":"","companion":"https://alu.shohanlab.com/","custom":[]},
    "navigation": {"home":"Home","gauntlet":"Gauntlet","tournaments":"Tournaments","clubs":"Clubs","help":"Help","calendar":"Calendar","companion":"Companion"},
    "terminology": {"gauntlet":"Gauntlet","tournaments":"Tournaments","clubs":"Clubs","players":"Drivers","season":"Season","matches":"Matches","support":"Help Center"},
}
BRANDING_COLOR_KEYS = ("primary","secondary","accent","background","surface","text","muted")
BRANDING_IMAGE_KEYS = ("hero_url","welcome_url","gauntlet_url","tournament_url","club_url","login_url","background_url")
BRANDING_LINK_KEYS = ("site_logo","discord","website","youtube","twitch","facebook","instagram","x","support","companion")



__all__ = [name for name in globals() if not name.startswith("__")]
