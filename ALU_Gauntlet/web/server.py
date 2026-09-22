"""A secure, guild-aware web control center shared with the Discord bot."""
from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path
import mimetypes
import html
import re
from typing import Any

from aiohttp import web
import discord

from .auth import DiscordOAuth, SESSION_COOKIE
from .players import PlayerService
from ..core.core import ALU_TRACKS, has_5_course_defense, submit_registration_application, get_current_season_number

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent / "static"

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
    "identity": {"name":"Racing Syndicate League","short_name":"RSL","site_title":"Racing Syndicate League","tagline":"Compete. Race. Dominate.","favicon_url":"/assets/rsl-shield.svg","logo_url":"/assets/rsl-shield.svg","mobile_logo_url":"/assets/rsl-shield.svg"},
    "colors": {"primary":"#25dfff","secondary":"#1878ff","accent":"#ffd22d","background":"#020817","surface":"#061226","text":"#f5f7ff","muted":"#91a5c3"},
    "images": {"hero_url":"/assets/hero.jpg","welcome_url":"/assets/hero.jpg","gauntlet_url":"/assets/hero.jpg","tournament_url":"/assets/hero.jpg","club_url":"/assets/hero.jpg","login_url":"/assets/hero.jpg","background_url":""},
    "links": {"discord":"https://discord.gg/fmFk8Ejf2H","website":"https://asph.discloud.app","youtube":"","twitch":"","facebook":"","instagram":"","x":"","cashapp":"https://cash.app/","support":"","companion":"https://alu.shohanlab.com/"},
    "navigation": {"home":"Home","gauntlet":"Gauntlet","tournaments":"Tournaments","clubs":"Clubs","help":"Help","calendar":"Calendar","companion":"Companion"},
    "terminology": {"gauntlet":"Gauntlet","tournaments":"Tournaments","clubs":"Clubs","players":"Drivers","season":"Season","matches":"Matches","support":"Help Center"},
}
BRANDING_COLOR_KEYS = ("primary","secondary","accent","background","surface","text","muted")
BRANDING_IMAGE_KEYS = ("hero_url","welcome_url","gauntlet_url","tournament_url","club_url","login_url","background_url")
BRANDING_LINK_KEYS = ("discord","website","youtube","twitch","facebook","instagram","x","cashapp","support","companion")


class WebControlCenter:
    """Guild-aware player/staff web UI backed by the same MongoDB as Discord."""

    def __init__(self, bot: Any, host: str = "127.0.0.1", port: int = 8080) -> None:
        self.bot = bot
        self.host = host
        self.port = port
        self.auth = DiscordOAuth(bot)
        self.players = PlayerService(bot)
        self.app = web.Application(middlewares=[self._error_middleware], client_max_size=8 * 1024 * 1024)
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self._configure_routes()

    @web.middleware
    async def _error_middleware(self, request: web.Request, handler: Any) -> web.StreamResponse:
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except Exception:
            # Never expose aiohttp's generic "Server got itself in trouble"
            # page. Log the full traceback server-side and return a controlled
            # response that identifies the failing route.
            log.exception("Unhandled web exception on %s %s", request.method, request.path_qs)
            if request.path.startswith("/api/"):
                return web.json_response(
                    {"ok": False, "error": "The Racing Syndicate League web service hit an unexpected error.", "path": request.path},
                    status=503,
                )
            return web.Response(
                text=(
                    "Racing Syndicate League web service temporarily unavailable. "
                    f"Route: {request.path}"
                ),
                status=503,
                content_type="text/plain",
            )

    async def _page_response(self, filename: str, request: web.Request | None = None) -> web.Response:
        path = WEB_DIR / filename
        try:
            body = path.read_text(encoding="utf-8")
        except Exception as exc:
            log.exception("Unable to read web page %s", path)
            raise web.HTTPServiceUnavailable(
                text=f"Web page '{filename}' is temporarily unavailable."
            ) from exc

        branding = await self._branding_for_request(request) if request is not None else self._merge_branding({})
        body = self._apply_web_branding(body, branding)

        # Keep the account/profile control consistent across every web page.
        # The navigation itself is intentionally kept in each page so existing
        # page-specific layouts remain untouched; this adds only the right-side
        # authenticated account menu.
        profile_markup = r'''
<div class="rsl-profile-nav" id="rsl-profile-nav" hidden>
  <button class="rsl-profile-trigger" id="rsl-profile-trigger" type="button"
          aria-haspopup="true" aria-expanded="false">
    <span class="rsl-profile-avatar" id="rsl-profile-avatar">👤</span>
    <span class="rsl-profile-label" id="rsl-profile-label">Profile</span>
    <span class="rsl-profile-chevron">⌄</span>
  </button>
  <div class="rsl-profile-menu" id="rsl-profile-menu" hidden>
    <div class="rsl-profile-menu-head">
      <strong id="rsl-profile-menu-name">Profile</strong>
      <small id="rsl-profile-menu-sub">Discord account</small>
    </div>
    <a href="/player#preferences">⚙️ <span>My Settings</span></a>
    <a href="/player#profile-settings">👤 <span>My Profile</span></a>
    <a href="/clubs">🏎️ <span>My Club</span></a>
    <a href="/gauntlet/career">🏁 <span>My Gauntlet</span></a>
    <a href="/player#career">🏆 <span>My Tournaments</span></a>
    <a class="rsl-admin-tools-link" id="rsl-admin-tools-link" href="/admin" hidden>🛠️ <span>Admin Tools</span></a>
    <div class="rsl-profile-divider"></div>
    <a class="rsl-profile-logout" href="/logout">🔐 <span>Sign Out</span></a>
  </div>
</div>
<a class="rsl-login-button" id="rsl-login-button" href="/login" hidden>🔐 Login</a>
'''
        search_markup = r'''
<button class="rsl-search-trigger" id="rsl-search-trigger" type="button" aria-label="Search site" aria-expanded="false"><img src="/assets/icons/search.svg" alt=""><span>Search</span></button>
<div class="rsl-search-overlay" id="rsl-search-overlay" hidden>
  <div class="rsl-search-dialog" role="dialog" aria-modal="true" aria-labelledby="rsl-search-title">
    <div class="rsl-search-head"><strong id="rsl-search-title">Search Racing Syndicate League</strong><button type="button" class="rsl-search-close" id="rsl-search-close" aria-label="Close search">×</button></div>
    <div class="rsl-search-input-wrap"><img src="/assets/icons/search.svg" alt=""><input id="rsl-search-input" type="search" placeholder="Search the site…" autocomplete="off"></div>
    <div class="rsl-search-results" id="rsl-search-results"><p>Type to search pages, features and racing information.</p></div>
  </div>
</div>
'''

        language_markup = r'''
<div id="google_translate_element" class="rsl-google-translate" aria-hidden="true"></div>
<div class="rsl-language-switcher" id="rsl-language-switcher">
  <button class="rsl-language-trigger" id="rsl-language-trigger" type="button" aria-haspopup="true" aria-expanded="false">
    <span class="rsl-language-globe" aria-hidden="true">◎</span>
    <span id="rsl-language-label">English</span>
    <span class="rsl-language-chevron">⌃</span>
  </button>
  <div class="rsl-language-menu" id="rsl-language-menu" hidden>
    <button type="button" class="rsl-language-option is-active" data-code="en">English</button>
    <button type="button" class="rsl-language-option" data-code="zh-CN">中文（普通话）</button>
    <button type="button" class="rsl-language-option" data-code="es">Español</button>
    <button type="button" class="rsl-language-option" data-code="ar">العربية</button>
    <button type="button" class="rsl-language-option" data-code="pt">Português</button>
    <button type="button" class="rsl-language-option" data-code="ru">Русский</button>
    <button type="button" class="rsl-language-option" data-code="fr">Français</button>
    <button type="button" class="rsl-language-option" data-code="de">Deutsch</button>
    <button type="button" class="rsl-language-option" data-code="ms">Bahasa Melayu</button>
    <button type="button" class="rsl-language-option" data-code="hi">हिन्दी</button>
    <button type="button" class="rsl-language-option" data-code="ja">日本語</button>
    <button type="button" class="rsl-language-option" data-code="ko">한국어</button>
    <button type="button" class="rsl-language-option" data-code="it">Italiano</button>
    <button type="button" class="rsl-language-option" data-code="tr">Türkçe</button>
    <button type="button" class="rsl-language-option" data-code="nl">Nederlands</button>
    <button type="button" class="rsl-language-option" data-code="pl">Polski</button>
    <button type="button" class="rsl-language-option" data-code="th">ไทย</button>
    <button type="button" class="rsl-language-option" data-code="vi">Tiếng Việt</button>
    <button type="button" class="rsl-language-option" data-code="id">Bahasa Indonesia</button>
    <button type="button" class="rsl-language-option" data-code="uk">Українська</button>
  </div>
</div>
<script>
(function(){
  const codes={en:"English","zh-CN":"中文（普通话）",es:"Español",ar:"العربية",pt:"Português",ru:"Русский",fr:"Français",de:"Deutsch",ms:"Bahasa Melayu",hi:"हिन्दी",ja:"日本語",ko:"한국어",it:"Italiano",tr:"Türkçe",nl:"Nederlands",pl:"Polski",th:"ไทย",vi:"Tiếng Việt",id:"Bahasa Indonesia",uk:"Українська"};
  const readCookie=()=>{
    const match=document.cookie.match(/(?:^|; )googtrans=\/en\/([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "en";
  };
  const setCookie=(code)=>{
    document.cookie="googtrans=/en/"+code+";path=/;max-age=31536000;SameSite=Lax";
  };
  const clearCookie=()=>{
    document.cookie="googtrans=;path=/;expires=Thu, 01 Jan 1970 00:00:00 GMT;SameSite=Lax";
  };
  const syncAccountLanguage=async()=>{
    try{
      const response=await fetch("/api/language",{credentials:"same-origin"});
      if(!response.ok)return false;
      const data=await response.json();
      const code=codes[data.language]?data.language:"en";
      if(readCookie()!==code){
        if(code==="en")clearCookie();else setCookie(code);
        window.location.reload();
        return true;
      }
      return false;
    }catch(_){return false;}
  };
  const init=()=>{
    const switcher=document.getElementById("rsl-language-switcher");
    const footer=document.querySelector("footer");
    if(switcher&&footer) footer.appendChild(switcher);
    const trigger=document.getElementById("rsl-language-trigger");
    const menu=document.getElementById("rsl-language-menu");
    const label=document.getElementById("rsl-language-label");
    if(!trigger||!menu)return;
    const current=readCookie();
    if(label)label.textContent=codes[current]||"English";
    menu.querySelectorAll(".rsl-language-option").forEach(option=>{
      option.classList.toggle("is-active",option.dataset.code===current);
      option.addEventListener("click",async()=>{
        const code=option.dataset.code;
        try{
          const response=await fetch("/api/language",{
            method:"POST",
            credentials:"same-origin",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({language:code})
          });
          if(!response.ok)throw new Error("language save failed");
        }catch(_){}
        if(code==="en")clearCookie();else setCookie(code);
        localStorage.setItem("rsl-language",code);
        window.location.reload();
      });
    });
    const close=()=>{menu.hidden=true;trigger.setAttribute("aria-expanded","false");};
    trigger.addEventListener("click",e=>{e.stopPropagation();menu.hidden=!menu.hidden;trigger.setAttribute("aria-expanded",String(!menu.hidden));});
    document.addEventListener("click",e=>{if(!menu.contains(e.target)&&e.target!==trigger)close();});
    document.addEventListener("keydown",e=>{if(e.key==="Escape")close();});
    syncAccountLanguage();
  };
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();
</script>
<script>
window.rslGoogleTranslateInit=function(){
  if(window.google&&window.google.translate&&window.google.translate.TranslateElement){
    new window.google.translate.TranslateElement({
      pageLanguage:"en",
      includedLanguages:"en,zh-CN,es,ar,pt,ru,fr,de,ms,hi,ja,ko,it,tr,nl,pl,th,vi,id,uk",
      autoDisplay:false
    },"google_translate_element");
  }
};
</script>
<script src="https://translate.google.com/translate_a/element.js?cb=rslGoogleTranslateInit"></script>
'''

        # Add Calendar immediately before the Companion dropdown on every page.
        # Keep the navigation order stable: Clubs → Help → Calendar → Companion.
        # Replace the complete legacy Companion anchor; replacing only its opening
        # tag would leave the old href/attributes visible as plain text.
        companion_markup = r'''<details class="top-nav-dropdown companion-nav-dropdown">
<summary class="top-nav-dropdown-trigger companion-nav-trigger"><img class="nav-icon-img companion-nav-icon" src="/assets/icons/companion.svg" alt=""><span class="companion-nav-title"><small>Shohan's</small><strong>Companion</strong></span><span class="nav-chevron">⌄</span></summary>
<div class="top-nav-dropdown-menu companion-nav-info-menu">
  <a class="companion-info-link" href="https://alu.shohanlab.com/" target="_blank" rel="noopener noreferrer" aria-label="Open Asphalt United Companion by Shohan's Lab">
    <span class="companion-info-link-icon">↗</span>
    <span><strong>Click to View</strong><small>Open Asphalt United Companion by Shohan's Lab.</small></span>
  </a>
  <div class="companion-info-item"><span class="companion-info-icon">🚗</span><span><strong>Car Upgrade Calculator</strong><small>Plan your upgrades &amp; optimize your build.</small></span></div>
  <div class="companion-info-item"><span class="companion-info-icon">🔄</span><span><strong>Comparator</strong><small>Compare between cars.</small></span></div>
  <div class="companion-info-item"><span class="companion-info-icon">🎯</span><span><strong>Priority</strong><small>Manage your priorities.</small></span></div>
  <div class="companion-info-item"><span class="companion-info-icon">📅</span><span><strong>Season Calendar</strong><small>Stay on top of events, cups, &amp; seasons.</small></span></div>
  <div class="companion-info-item"><span class="companion-info-icon">🃏</span><span><strong>Hunt Game</strong><small>See how many times you have to play to get all those cards.</small></span></div>
  <div class="companion-info-item"><span class="companion-info-icon">🏁</span><span><strong>Simulation</strong><small>Simulate car win rates and matchups.</small></span></div>
  <div class="companion-info-item"><span class="companion-info-icon">🗺️</span><span><strong>Race Maps</strong><small>Full maps &amp; the track variants played on them.</small></span></div>
  <div class="companion-info-item"><span class="companion-info-icon">📊</span><span><strong>Rating Predictor</strong><small>Guess an opponent's configuration from their Gauntlet rating number.</small></span></div>
  <div class="companion-info-item"><span class="companion-info-icon">💰</span><span><strong>Cost Calculator</strong><small>Plan upgrades for your whole garage — credits, parts, &amp; garage value to a target star.</small></span></div>
  <div class="companion-info-item"><span class="companion-info-icon">🎟️</span><span><strong>Event Calculator</strong><small>Plan limited-time Spotlight events — stage-by-stage reward simulation.</small></span></div>
  <div class="companion-info-item"><span class="companion-info-icon">📝</span><span><strong>Notes &amp; Reminders</strong><small>Your own notes for events, cars, &amp; other games with reminders &amp; notifications.</small></span></div>
</div></details>'''
        legacy_companion = re.compile(r'<a class="companion-nav-link"[^>]*>.*?</a>', re.S)
        if legacy_companion.search(body):
            calendar_markup = '<a href="/calendar"><img class="nav-icon-img" src="/assets/icons/calendar.svg" alt=""><span>Calendar</span></a>'
            replacement = (calendar_markup if '<a href="/calendar"' not in body else '') + companion_markup
            body = legacy_companion.sub(replacement, body, count=1)
        elif '<a href="/calendar"' not in body and "</nav>" in body:
            calendar_markup = '<a href="/calendar"><img class="nav-icon-img" src="/assets/icons/calendar.svg" alt=""><span>Calendar</span></a>'
            body = body.replace("</nav>", calendar_markup + "</nav>", 1)

        if "</header>" in body and 'id="rsl-search-trigger"' not in body:
            body = body.replace("</header>", search_markup + "</header>", 1)

        if "</nav></header>" in body:
            body = body.replace("</nav></header>", "</nav>" + profile_markup + "</header>", 1)
        elif "</header>" in body:
            body = body.replace("</header>", profile_markup + "</header>", 1)

        search_script = r'''
<script>
(function(){
  const trigger=document.getElementById("rsl-search-trigger"), overlay=document.getElementById("rsl-search-overlay"), input=document.getElementById("rsl-search-input"), close=document.getElementById("rsl-search-close"), results=document.getElementById("rsl-search-results");
  if(!trigger||!overlay||!input||!close||!results)return;
  const hide=()=>{overlay.hidden=true;trigger.setAttribute("aria-expanded","false");};
  const show=()=>{overlay.hidden=false;trigger.setAttribute("aria-expanded","true");setTimeout(()=>input.focus(),20);};
  trigger.addEventListener("click",show); close.addEventListener("click",hide);
  overlay.addEventListener("click",e=>{if(e.target===overlay)hide();});
  document.addEventListener("keydown",e=>{if(e.key==="Escape")hide();if(e.key==="/"&&document.activeElement!==input){e.preventDefault();show();}});
  let timer; input.addEventListener("input",()=>{clearTimeout(timer);const q=input.value.trim();if(q.length<2){results.innerHTML="<p>Type at least 2 characters to search.</p>";return;}timer=setTimeout(async()=>{results.innerHTML="<p>Searching…</p>";try{const r=await fetch("/api/search?q="+encodeURIComponent(q),{credentials:"same-origin"});const d=await r.json();results.innerHTML=d.results.length?d.results.map(x=>'<a class="rsl-search-result" href="'+x.url+'"><strong>'+x.title+'</strong><span>'+x.snippet+'</span></a>').join(""):"<p>No matching pages found.</p>";}catch(_){results.innerHTML="<p>Search is temporarily unavailable.</p>";}},180);});
})();
</script>
'''

        if "</body>" in body:
            body = body.replace("</body>", language_markup + search_script + "</body>", 1)

        profile_script = r'''
<script>
(function () {
  const nav = document.getElementById("rsl-profile-nav");
  const login = document.getElementById("rsl-login-button");
  const trigger = document.getElementById("rsl-profile-trigger");
  const menu = document.getElementById("rsl-profile-menu");
  if (!nav || !login) return;

  const closeMenu = () => {
    if (!menu || !trigger) return;
    menu.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
  };

  fetch("/api/me", {credentials: "same-origin"})
    .then(async response => {
      if (!response.ok) throw new Error("not authenticated");
      return response.json();
    })
    .then(me => {
      const name = me.global_name || me.username || "Profile";
      const avatar = me.avatar && me.id
        ? "https://cdn.discordapp.com/avatars/" + encodeURIComponent(me.id) + "/" + encodeURIComponent(me.avatar) + ".png?size=64"
        : "";
      const label = document.getElementById("rsl-profile-label");
      const menuName = document.getElementById("rsl-profile-menu-name");
      const menuSub = document.getElementById("rsl-profile-menu-sub");
      const avatarBox = document.getElementById("rsl-profile-avatar");
      if (label) label.textContent = name;
      if (menuName) menuName.textContent = name;
      if (menuSub) menuSub.textContent = me.username ? "@" + me.username : "Discord account";
      if (avatarBox && avatar) avatarBox.innerHTML = '<img src="' + avatar + '" alt="">';
      const adminLink = document.getElementById("rsl-admin-tools-link");
      if (adminLink) adminLink.hidden = !me.admin;
      nav.hidden = false;
      login.hidden = true;
    })
    .catch(() => {
      nav.hidden = true;
      login.hidden = false;
      closeMenu();
    });

  trigger?.addEventListener("click", e => {
    e.stopPropagation();
    const open = !menu.hidden;
    menu.hidden = open;
    trigger.setAttribute("aria-expanded", String(!open));
  });
  menu?.addEventListener("click", e => e.stopPropagation());
  document.addEventListener("click", closeMenu);
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeMenu(); });
})();
</script>
'''
        if "</body>" in body:
            body = body.replace("</body>", profile_script + "</body>", 1)
        return web.Response(text=body, content_type="text/html")

    def _merge_branding(self, raw: dict[str, Any] | None) -> dict[str, Any]:
        raw = raw or {}
        merged = json.loads(json.dumps(DEFAULT_WEB_BRANDING))
        for section in ("identity", "colors", "images", "links", "navigation", "terminology"):
            values = raw.get(section)
            if isinstance(values, dict):
                merged[section].update({str(k): v for k, v in values.items()})
        return merged

    async def _branding_for_request(self, request: web.Request) -> dict[str, Any]:
        user = await self.require_user(request)
        memberships = {str(x) for x in getattr(user, "guild_ids", [])}
        candidates = [request.query.get("guild_id", "").strip(), request.cookies.get("rsl_guild_id", "").strip(), *memberships]
        chosen = next((gid for gid in candidates if gid in memberships and any(str(getattr(g, "id", "")) == gid for g in getattr(self.bot, "guilds", []))), None)
        if not chosen:
            return self._merge_branding({})
        settings = await self.bot.db.settings.find_one({"_id": chosen}) or {}
        raw = settings.get("web_branding") if isinstance(settings.get("web_branding"), dict) else {}
        return self._merge_branding(raw)

    def _apply_web_branding(self, body: str, branding: dict[str, Any]) -> str:
        identity, colors, images = branding["identity"], branding["colors"], branding["images"]
        links, nav, terms = branding["links"], branding["navigation"], branding["terminology"]
        name = html.escape(str(identity.get("name") or "Racing Syndicate League"))
        short = html.escape(str(identity.get("short_name") or "RSL"))
        title = html.escape(str(identity.get("site_title") or name))
        logo = html.escape(str(identity.get("logo_url") or "/assets/rsl-shield.svg"), quote=True)
        hero = html.escape(str(images.get("hero_url") or "/assets/hero.jpg"), quote=True)
        welcome = html.escape(str(images.get("welcome_url") or "/assets/hero.jpg"), quote=True)
        def esc(value: Any) -> str:
            return html.escape(str(value or ""), quote=True)
        body = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", body, count=1, flags=re.I | re.S)
        body = body.replace("/assets/rsl-shield.svg", logo).replace("/static/assets/rsl-mini-header.png?v=20260921-rslmini-png1", logo)
        body = body.replace("/assets/hero.jpg", hero)
        body = body.replace("Racing Syndicate League", name).replace("RSL", short)
        body = body.replace("https://discord.gg/fmFk8Ejf2H", esc(links.get("discord")))
        body = body.replace("https://cash.app/", esc(links.get("cashapp")))
        body = body.replace("https://alu.shohanlab.com/", esc(links.get("companion")))
        defaults = {"home":"Home","gauntlet":"Gauntlet","tournaments":"Tournaments","clubs":"Clubs","help":"Help","calendar":"Calendar","companion":"Companion"}
        for key, value in nav.items():
            if value:
                body = body.replace(f"<span>{defaults.get(key, key)}</span>", f"<span>{html.escape(str(value))}</span>")
        for key in ("gauntlet","tournaments","clubs"):
            value = terms.get(key)
            if value:
                body = body.replace(f">{defaults[key]}<", f">{html.escape(str(value))}<")
        css = f"""<style id="rsl-tenant-branding">
:root{{--brand-primary:{esc(colors.get('primary') or '#25dfff')};--brand-secondary:{esc(colors.get('secondary') or '#1878ff')};--brand-accent:{esc(colors.get('accent') or '#ffd22d')};--brand-bg:{esc(colors.get('background') or '#020817')};--brand-surface:{esc(colors.get('surface') or '#061226')};--brand-text:{esc(colors.get('text') or '#f5f7ff')};--brand-muted:{esc(colors.get('muted') or '#91a5c3')};--brand-hero:url('{hero}');--brand-welcome:url('{welcome}');}}
body{{background-color:var(--brand-bg);color:var(--brand-text)}}
.top-nav{{border-bottom-color:var(--brand-primary)!important}}
.top-nav nav a.active:after{{background:var(--brand-primary)!important}}
.hero-banner{{background-image:var(--brand-hero)!important}}
.welcome-panel:after{{background-image:linear-gradient(90deg,#06152f00,#06152f11),var(--brand-welcome)!important}}
.hero-action-gauntlet{{background:linear-gradient(90deg,var(--brand-secondary),var(--brand-primary))!important;border-color:var(--brand-primary)!important}}
.hero-action,.home-info-card,.home-help-card{{border-color:var(--brand-primary)!important}}
.rsl-profile-trigger,.rsl-profile-menu{{border-color:var(--brand-primary)!important}}
</style>"""
        if images.get("background_url"):
            css += f'<style id="rsl-tenant-background">body{{background-image:url("{esc(images["background_url"])}")!important;background-size:cover;background-attachment:fixed}}</style>'
        if identity.get("favicon_url"):
            css += f'<link rel="icon" href="{esc(identity["favicon_url"])}">'
        if identity.get("tagline"):
            css += f'<meta name="description" content="{html.escape(str(identity["tagline"]), quote=True)}">'
        return body.replace("</head>", css + "</head>", 1)

    async def _admin_guilds_data(self, user: Any) -> list[dict[str, Any]]:
        rows = []
        member_guild_ids = {str(x) for x in getattr(user, "guild_ids", [])}
        for guild in getattr(self.bot, "guilds", []):
            gid = str(getattr(guild, "id", ""))
            if gid not in member_guild_ids:
                continue
            allowed = user.user_id in self.auth.allowed_staff_ids
            member = guild.get_member(int(user.user_id))
            if member and (member.guild_permissions.administrator or member.guild_permissions.manage_guild):
                allowed = True
            if not allowed and member:
                settings = await self.bot.db.settings.find_one({"_id": gid}) or {}
                role_id = str(settings.get("admin_role_id", "")).strip()
                allowed = bool(role_id and any(str(role.id) == role_id for role in getattr(member, "roles", [])))
            if allowed:
                rows.append({"id":gid,"name":str(getattr(guild,"name",gid)),"member_count":int(getattr(guild,"member_count",0) or 0)})
        return rows

    async def admin_page(self, request: web.Request) -> web.StreamResponse:
        user = await self.require_user(request)
        if not await self._admin_guilds_data(user):
            raise web.HTTPForbidden(text="Administrator access is required for this server.")
        return await self._page_response("admin.html", request)

    async def admin_guilds(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        rows = await self._admin_guilds_data(user)
        if not rows:
            raise web.HTTPForbidden(text="Administrator access is required for this server.")
        return web.json_response({"guilds":rows})

    async def admin_branding(self, request: web.Request) -> web.Response:
        _, guild_id, guild = await self.require_admin(request)
        settings = await self.bot.db.settings.find_one({"_id":guild_id}) or {}
        branding = self._merge_branding(settings.get("web_branding"))
        branding["_guild"] = {"id":guild_id,"name":str(getattr(guild,"name",guild_id))}
        return web.json_response({"branding":branding})

    async def save_admin_branding(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        try:
            payload = await request.json()
        except Exception as exc:
            raise web.HTTPBadRequest(text="Invalid JSON body.") from exc
        incoming = payload.get("branding", payload)
        if not isinstance(incoming, dict):
            raise web.HTTPBadRequest(text="Branding must be an object.")
        clean = self._merge_branding(incoming)
        for key in BRANDING_COLOR_KEYS:
            value = str(clean["colors"].get(key, "")).strip()
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                raise web.HTTPBadRequest(text=f"Invalid {key} color.")
            clean["colors"][key] = value
        for section, keys in (("identity",("name","short_name","site_title","tagline","favicon_url","logo_url","mobile_logo_url")),("images",BRANDING_IMAGE_KEYS),("links",BRANDING_LINK_KEYS),("navigation",tuple(DEFAULT_WEB_BRANDING["navigation"])),("terminology",tuple(DEFAULT_WEB_BRANDING["terminology"]))):
            for key in keys:
                value = str(clean[section].get(key,"")).strip()
                if len(value)>1000:
                    raise web.HTTPBadRequest(text=f"{section}.{key} is too long.")
                if section in {"links","images"} and value and not (value.startswith("https://") or value.startswith("http://") or value.startswith("/")):
                    raise web.HTTPBadRequest(text=f"{section}.{key} must be an http(s) URL or site-relative path.")
                clean[section][key]=value
        await self.bot.db.settings.update_one({"_id":guild_id},{"$set":{"web_branding":clean}},upsert=True)
        await self._audit(guild_id,user.user_id,"Web white-label branding updated")
        return web.json_response({"ok":True,"branding":clean,"guild_id":guild_id})

    async def select_admin_guild(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        payload = await request.json()
        gid = str(payload.get("guild_id","")).strip()
        rows = await self._admin_guilds_data(user)
        if gid not in {row["id"] for row in rows}:
            raise web.HTTPForbidden(text="You do not have administrator access to that server.")
        response = web.json_response({"ok":True,"guild_id":gid})
        response.set_cookie("rsl_guild_id",gid,max_age=2592000,path="/",secure=request.secure,httponly=False,samesite="Lax")
        return response

    async def upload_brand_asset(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        if request.content_length and request.content_length > 8*1024*1024:
            raise web.HTTPRequestEntityTooLarge(max_size=8*1024*1024, actual_size=request.content_length)
        reader = await request.multipart()
        field = await reader.next()
        if field is None or field.name != "file":
            raise web.HTTPBadRequest(text="Send an image in the 'file' field.")
        filename = Path(field.filename or "brand-image").name[:120]
        content_type = str(field.headers.get("Content-Type","") or "")
        if content_type not in {"image/png","image/jpeg","image/webp","image/gif","image/svg+xml","image/x-icon"}:
            raise web.HTTPBadRequest(text="Supported image types: PNG, JPEG, WEBP, GIF, SVG and ICO.")
        data = await field.read()
        if not data or len(data)>8*1024*1024:
            raise web.HTTPRequestEntityTooLarge(max_size=8*1024*1024, actual_size=len(data or b""))
        asset_id = hashlib.sha256(f"{guild_id}:{filename}:{time.time()}".encode()+data).hexdigest()[:32]
        await self.bot.db.web_brand_assets.insert_one({"_id":asset_id,"guild_id":guild_id,"filename":filename,"content_type":content_type,"data":data,"created_at":time.time(),"created_by":str(user.user_id)})
        url=f"/assets/tenant/{guild_id}/{asset_id}"
        await self._audit(guild_id,user.user_id,f"Web brand asset uploaded: {filename}")
        return web.json_response({"ok":True,"asset_id":asset_id,"url":url,"filename":filename,"content_type":content_type})

    async def serve_brand_asset(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        guild_id = str(request.match_info["guild_id"])
        if guild_id not in {str(x) for x in getattr(user,"guild_ids",[])}:
            raise web.HTTPForbidden(text="You are not a member of this server.")
        asset_id = str(request.match_info["asset_id"])
        asset = await self.bot.db.web_brand_assets.find_one({"_id":asset_id,"guild_id":guild_id})
        if not asset:
            raise web.HTTPNotFound(text="Brand asset not found.")
        return web.Response(body=asset.get("data") or b"",content_type=str(asset.get("content_type") or "application/octet-stream"),headers={"Cache-Control":"public, max-age=3600"})

    async def admin_diagnostics(self, request: web.Request) -> web.Response:
        _, guild_id, guild = await self.require_admin(request)
        checks=[{"name":"Discord connection","ok":guild is not None},{"name":"MongoDB","ok":False}]
        try:
            await self.bot.db.command("ping"); checks[-1]["ok"]=True
        except Exception as exc:
            checks[-1]["detail"]=str(exc)[:200]
        settings = await self.bot.db.settings.find_one({"_id":guild_id}) or {}
        checks.append({"name":"Branding configuration","ok":bool(self._merge_branding(settings.get("web_branding"))["identity"]["name"])})
        return web.json_response({"ok":all(x["ok"] for x in checks),"checks":checks,"guild":{"id":guild_id,"name":guild.name,"members":getattr(guild,"member_count",0)}})

    async def admin_audit(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_admin(request)
        rows=[]
        cursor=self.bot.db.system_events.find({"guild_id":guild_id}).sort("_id",-1).limit(50)
        async for row in cursor:
            rows.append({"id":str(row.get("_id","")),"source":str(row.get("source","")),"user_id":str(row.get("user_id","")),"action":str(row.get("action",""))})
        return web.json_response({"events":rows})

    async def admin_sync(self, request: web.Request) -> web.Response:
        user, guild_id, guild = await self.require_admin(request)
        tree=getattr(self.bot,"tree",None)
        if tree is None:
            raise web.HTTPServiceUnavailable(text="Discord command tree is unavailable.")
        try:
            synced=await tree.sync(guild=guild)
        except Exception as exc:
            log.exception("Web admin command sync failed for guild %s",guild_id)
            raise web.HTTPBadGateway(text=f"Discord command sync failed: {exc}") from exc
        await self._audit(guild_id,user.user_id,f"Web force sync: {len(synced)} commands")
        return web.json_response({"ok":True,"synced":len(synced)})

    async def admin_backup(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        settings=await self.bot.db.settings.find_one({"_id":guild_id}) or {}
        backup={"exported_at":datetime.now(timezone.utc).isoformat(),"guild_id":guild_id,"settings":{k:v for k,v in settings.items() if k!="_id"},"web_branding":self._merge_branding(settings.get("web_branding"))}
        await self._audit(guild_id,user.user_id,"Web configuration backup exported")
        return web.json_response(backup,headers={"Content-Disposition":f'attachment; filename="guild-{guild_id}-web-config.json"'})

    def _configure_routes(self) -> None:
        self.app.router.add_get("/", self.index)
        self.app.router.add_get("/help", self.help_page)
        self.app.router.add_get("/players", self.players_page)
        self.app.router.add_get("/setup", self.setup_page)
        self.app.router.add_get("/news-admin", self.news_admin_page)
        self.app.router.add_get("/admin", self.admin_page)
        self.app.router.add_get("/player", self.player_page)
        self.app.router.add_get("/gauntlet/registration", self.gauntlet_registration_page)
        self.app.router.add_get("/gauntlet/defense", self.gauntlet_defense_page)
        self.app.router.add_get("/gauntlet/matches", self.gauntlet_matches_page)
        self.app.router.add_get("/gauntlet/leaderboard", self.gauntlet_leaderboard_page)
        self.app.router.add_get("/gauntlet/references", self.gauntlet_references_page)
        self.app.router.add_get("/gauntlet/career", self.gauntlet_career_page)
        self.app.router.add_get("/tournaments", self.tournaments_page)
        self.app.router.add_get("/calendar", self.calendar_page)
        self.app.router.add_get("/tournaments/registration", self.tournament_registration_page)
        self.app.router.add_get("/tournaments/matches", self.tournament_matches_page)
        self.app.router.add_get("/tournaments/results", self.tournament_results_page)
        self.app.router.add_get("/tournaments/clubs", self.tournament_clubs_page)
        self.app.router.add_get("/clubs", self.clubs_page)
        self.app.router.add_get("/login", self.login)
        self.app.router.add_get("/auth/callback", self.callback)
        self.app.router.add_get("/logout", self.logout)
        self.app.router.add_get("/healthz", self.healthz)
        self.app.router.add_get("/api/me", self.me)
        self.app.router.add_get("/api/admin/guilds", self.admin_guilds)
        self.app.router.add_get("/api/admin/branding", self.admin_branding)
        self.app.router.add_put("/api/admin/branding", self.save_admin_branding)
        self.app.router.add_post("/api/admin/select-guild", self.select_admin_guild)
        self.app.router.add_post("/api/admin/upload-asset", self.upload_brand_asset)
        self.app.router.add_get("/assets/tenant/{guild_id}/{asset_id}", self.serve_brand_asset)
        self.app.router.add_get("/api/admin/diagnostics", self.admin_diagnostics)
        self.app.router.add_get("/api/admin/audit", self.admin_audit)
        self.app.router.add_post("/api/admin/sync", self.admin_sync)
        self.app.router.add_get("/api/admin/backup", self.admin_backup)
        self.app.router.add_get("/api/search", self.site_search)
        self.app.router.add_get("/api/discord-stats", self.discord_stats)
        self.app.router.add_get("/api/language", self.get_language)
        self.app.router.add_post("/api/language", self.set_language)
        self.app.router.add_get("/api/notifications", self.notification_preferences)
        self.app.router.add_put("/api/notifications/category", self.update_notification_category)
        self.app.router.add_put("/api/notifications/event", self.update_notification_event)
        self.app.router.add_put("/api/notifications/timing", self.update_notification_timing)
        self.app.router.add_get("/api/status", self.status)
        self.app.router.add_get("/api/news", self.news)
        self.app.router.add_post("/api/news", self.create_news)
        self.app.router.add_put("/api/news/{news_id}", self.update_news)
        self.app.router.add_delete("/api/news/{news_id}", self.delete_news)
        self.app.router.add_get("/api/guilds", self.guilds)
        self.app.router.add_get("/api/player/me", self.player_me)
        self.app.router.add_get("/api/tournaments", self.tournaments)
        self.app.router.add_get("/api/calendar", self.calendar)
        self.app.router.add_get("/api/tournaments/{tournament_id}", self.tournament_detail)
        self.app.router.add_get("/api/clubs", self.clubs)
        self.app.router.add_post("/api/clubs", self.create_club)
        self.app.router.add_post("/api/clubs/update", self.update_club)
        self.app.router.add_post("/api/clubs/join", self.join_club)
        self.app.router.add_post("/api/clubs/member", self.manage_club_member)
        self.app.router.add_post("/api/tournaments", self.create_tournament)
        self.app.router.add_post("/api/tournaments/register", self.register_tournament)
        self.app.router.add_post("/api/tournaments/checkin", self.tournament_checkin)
        self.app.router.add_post("/api/tournaments/clubs/lineup", self.tournament_club_lineup)
        self.app.router.add_post("/api/tournaments/result", self.tournament_match_result)
        self.app.router.add_post("/api/tournaments/result/verify", self.tournament_verify_result)
        self.app.router.add_post("/api/tournaments/start", self.tournament_start)
        self.app.router.add_get("/api/player/defense", self.player_defense)
        self.app.router.add_post("/api/player/defense", self.player_defense_action)
        self.app.router.add_put("/api/player/preferences", self.player_preferences)
        self.app.router.add_put("/api/player/profile", self.player_profile)
        self.app.router.add_put("/api/player/asphalt", self.player_asphalt)
        self.app.router.add_post("/api/player/register", self.player_register)
        self.app.router.add_get("/api/setup/options", self.setup_options)
        self.app.router.add_get("/api/setup/settings", self.setup_settings)
        self.app.router.add_put("/api/setup/settings", self.save_setup_settings)
        self.app.router.add_get("/api/season", self.season)
        self.app.router.add_put("/api/season", self.save_season)
        self.app.router.add_get("/api/players", self.player_list)
        self.app.router.add_get("/api/leaderboard", self.leaderboard)
        self.app.router.add_get("/api/gauntlet/leaderboard", self.gauntlet_leaderboard)
        self.app.router.add_get("/api/gauntlet/references", self.gauntlet_references)
        self.app.router.add_post("/api/gauntlet/references", self.create_gauntlet_reference)
        self.app.router.add_get("/api/gauntlet/matches", self.gauntlet_matches)
        self.app.router.add_post("/api/gauntlet/matches/submit", self.gauntlet_submit_match)
        self.app.router.add_get("/api/competition/snapshot", self.competition_snapshot)
        self.app.router.add_get("/api/competition/recent-matches", self.competition_recent_matches)
        self.app.router.add_get("/api/player/career", self.player_career)
        self.app.router.add_get("/api/players/{user_id}", self.player_detail)
        # Serve every checked-in dashboard image through one predictable route.
        # The previous allow-list only covered the newer SVGs, so older JPG/WEBP
        # artwork could exist in the repository but still return a 404 in production.
        self.app.router.add_get("/assets/icons/{filename}", self.asset_icon)
        self.app.router.add_get("/assets/{filename}", self.asset)
        self.app.router.add_static("/static/", WEB_DIR, show_index=False)

    async def start(self) -> None:
        """Start the aiohttp web server on the configured Discloud host/port."""
        if self.runner is not None:
            return
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()
        log.info("Web control center listening on %s:%s", self.host, self.port)

    async def stop(self) -> None:
        """Stop the aiohttp web server and release its listening socket."""
        if self.runner is None:
            return
        try:
            await self.runner.cleanup()
        finally:
            self.site = None
            self.runner = None

    async def gauntlet_registration_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("gauntlet-registration.html", request)

    async def gauntlet_defense_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("gauntlet-defense.html", request)

    async def gauntlet_matches_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("gauntlet-matches.html", request)

    async def gauntlet_career_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("gauntlet-career.html", request)

    async def tournament_registration_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("tournament-registration.html", request)

    async def tournament_matches_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("tournament-matches.html", request)

    async def tournament_results_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("tournament-results.html", request)

    async def tournament_clubs_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("tournament-clubs.html", request)

    async def gauntlet_leaderboard_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("gauntlet-leaderboard.html", request)

    async def gauntlet_references_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("gauntlet-references.html", request)

    async def gauntlet_references(self, request: web.Request) -> web.Response:
        """Return references with the signed-in driver's best known run and car rating."""
        user=await self.require_user(request)
        guild_id=str(user.guild_ids[0]) if user.guild_ids else ""
        if not guild_id: raise web.HTTPForbidden(text="No server available.")
        profile=await self.bot.db.drivers.find_one({"_id":f"{guild_id}_{user.user_id}"}) or {}
        best_times=profile.get("best_times") or profile.get("track_records") or {}
        refs=[]
        async for item in self.bot.db.gauntlet_references.find({"guild_id":guild_id}).sort("created_at",-1):
            course=str(item.get("course","")); mine=best_times.get(course) if isinstance(best_times,dict) else None
            if isinstance(mine,dict): my_time=mine.get("lap_time") or mine.get("lap_time_str") or mine.get("time"); my_rank=mine.get("car_rank"); my_car=mine.get("car")
            else: my_time,my_rank,my_car=(mine if mine else None),None,None
            refs.append({"id":str(item.get("_id")),"course":course,"title":str(item.get("title","")),"driver":str(item.get("driver","")),"time":str(item.get("time","")),"car":str(item.get("car","")),"car_rank":int(item.get("car_rank",item.get("car_performance",0)) or 0),"video_url":str(item.get("video_url","")),"description":str(item.get("description","")),"official":bool(item.get("official",False)),"my_best_time":str(my_time or ""),"my_car":str(my_car or ""),"my_car_rank":int(my_rank or 0)})
        member=self.bot.get_guild(int(guild_id)).get_member(int(user.user_id)) if self.bot.get_guild(int(guild_id)) else None
        return web.json_response({"courses":list(ALU_TRACKS),"references":refs,"is_staff":bool(member and (member.guild_permissions.manage_guild or member.guild_permissions.administrator))})

    async def create_gauntlet_reference(self, request: web.Request) -> web.Response:
        user,guild_id,_=await self.require_admin(request); payload=await request.json()
        course=str(payload.get("course","")).strip(); title=str(payload.get("title","")).strip()[:120]; video_url=str(payload.get("video_url","")).strip()[:500]
        if course not in ALU_TRACKS or not title or not video_url: raise web.HTTPBadRequest(text="Course, title and video URL are required.")
        from bson import ObjectId
        try: car_rank=int(payload.get("car_rank",0) or 0)
        except (TypeError,ValueError): car_rank=0
        doc={"_id":ObjectId(),"guild_id":str(guild_id),"course":course,"title":title,"driver":str(payload.get("driver","")).strip()[:100],"time":str(payload.get("time","")).strip()[:30],"car":str(payload.get("car","")).strip()[:100],"car_rank":max(0,car_rank),"video_url":video_url,"description":str(payload.get("description","")).strip()[:1000],"official":bool(payload.get("official",False)),"created_by":str(user.user_id),"created_at":time.time()}
        await self.bot.db.gauntlet_references.insert_one(doc); await self._audit(str(guild_id),str(user.user_id),"Gauntlet reference added")
        return web.json_response({"ok":True,"id":str(doc["_id"])})

    async def gauntlet_matches(self, request: web.Request) -> web.Response:
        user,guild_id,_=await self.require_guild_member(request); uid=str(user.user_id); active=[]; recent=[]
        async for item in self.bot.db.active_challenges.find({"guild_id":str(guild_id),"$or":[{"challenger_id":uid},{"opponent_id":uid}],"status":{"$in":["active","processing"]}}).sort("created_at",-1).limit(10):
            oppid=str(item.get("opponent_id") if str(item.get("challenger_id"))==uid else item.get("challenger_id")); opp=await self.bot.db.drivers.find_one({"_id":f"{guild_id}_{oppid}"}) or {}
            active.append({"id":str(item.get("_id","")),"status":str(item.get("status","active")),"role":"challenger" if str(item.get("challenger_id"))==uid else "defender","opponent_id":oppid,"opponent":str(opp.get("game_id") or opp.get("username") or oppid),"courses":item.get("defense_courses") or [],"created_at":item.get("created_at") or item.get("started_at") or time.time()})
        cursor=self.bot.db.matches.find({"guild_id":str(guild_id),"reverted":{"$ne":True},"$or":[{"challenger_id":uid},{"opponent_id":uid}]}).sort("timestamp",-1).limit(20)
        async for match in cursor:
            challenger=str(match.get("challenger_id","")); opponent=str(match.get("opponent_id","")); other=opponent if challenger==uid else challenger
            won=str(match.get("w_id",""))==uid; lost=str(match.get("l_id",""))==uid
            if not(won or lost): continue
            opp=await self.bot.db.drivers.find_one({"_id":f"{guild_id}_{other}"}) or {}
            recent.append({"id":str(match.get("_id","")),"opponent":str(opp.get("game_id") or opp.get("username") or other),"result":"WIN" if won else "LOSS","courses":int(match.get("courses_beat",0) or 0),"timestamp":match.get("timestamp") or 0})
        return web.json_response({"active":active,"recent":recent})

    async def gauntlet_submit_match(self, request: web.Request) -> web.Response:
        """Submit five attack runs for the signed-in driver's active challenge."""
        user,guild_id,_=await self.require_guild_member(request)
        payload=await request.json()
        from ..core.core import parse_lap_time, process_match_result, claim_active_challenge, release_active_challenge
        uid=str(user.user_id); active=await claim_active_challenge(str(guild_id),uid)
        if not active: raise web.HTTPConflict(text="No active challenge is available to submit.")
        try:
            rows=payload.get("courses"); proof=str(payload.get("proof","")).strip()
            if not isinstance(rows,list) or len(rows)!=5: raise web.HTTPBadRequest(text="Exactly five course results are required.")
            if not proof.lower().startswith(("http://","https://")): raise web.HTTPBadRequest(text="Proof must be an image URL.")
            attack=[]; seen=set()
            for n,row in enumerate(rows,1):
                if not isinstance(row,dict): raise web.HTTPBadRequest(text=f"Course {n} is invalid.")
                car=str(row.get("car","")).strip(); lap=str(row.get("lap_time","")).strip()
                try: rank=int(row.get("car_rank",0))
                except (TypeError,ValueError): rank=0
                ms=parse_lap_time(lap)
                if not car or car.casefold() in seen or rank<=0 or ms<=0: raise web.HTTPBadRequest(text=f"Course {n} has an invalid car, car rating, or lap time.")
                seen.add(car.casefold()); attack.append({"lap_time_str":lap,"ms":ms,"car":car,"car_rank":rank})
            defense=active.get("defense_courses") or []
            result=await process_match_result(str(guild_id),uid,str(active["opponent_id"]),defense,attack,proof,active.get("defender_proof_url"),None,settlement_id=f"{active['_id']}:match")
            if not result: raise web.HTTPConflict(text="The match could not be settled.")
            await self.bot.db.active_challenges.update_one({"_id":active["_id"],"guild_id":str(guild_id),"challenger_id":uid,"status":"processing"},{"$set":{"status":"completed","completed_at":time.time(),"match_id":result["_id"]},"$unset":{"processing_at":""}})
            return web.json_response({"ok":True,"match_id":str(result["_id"]),"result":result.get("outcome_desc","Match submitted.")})
        except Exception:
            await release_active_challenge(active["_id"])
            raise

    async def gauntlet_leaderboard(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        guild_id = str(request.query.get("guild_id") or (user.guild_ids[0] if user.guild_ids else ""))
        if guild_id not in {str(x) for x in user.guild_ids}:
            raise web.HTTPForbidden(text="You are not a member of that server.")
        requested_season = request.query.get("season")
        if requested_season:
            try:
                season_number = int(requested_season)
            except ValueError:
                raise web.HTTPBadRequest(text="Invalid season.")
            archive = await self.bot.db.season_history.find_one({"_id": f"{guild_id}_{season_number}"})
            if not archive:
                raise web.HTTPNotFound(text="Archived season not found.")
            return web.json_response({
                "season": season_number,
                "standings": archive.get("standings", []),
                "player_count": int(archive.get("player_count", len(archive.get("standings", []))) or 0),
                "closed_at": archive.get("closed_at"),
            })
        state = await self.bot.db.season_state.find_one({"_id": f"guild_{guild_id}"}) or {}
        season_number = int(state.get("season_number", 1) or 1)
        drivers = {}
        async for driver in self.bot.db.drivers.find({
            "guild_id": guild_id,
            "season_registered": True,
            "season_number": season_number,
        }):
            uid = str(driver.get("user_id") or "")
            if not uid:
                continue
            drivers[uid] = {
                "user_id": uid,
                "name": str(driver.get("game_id") or driver.get("username") or uid),
                "elo": int(driver.get("elo", 1000) or 1000),
                "garage_pi": int(driver.get("garage_pi", 0) or 0),
                "played": 0,
                "wins": 0,
            }

        start_at = float(state.get("starts_at", 0) or 0)
        end_at = float(state.get("ends_at", 0) or 0)
        if start_at and end_at and end_at > start_at:
            cursor = self.bot.db.matches.find({
                "guild_id": guild_id,
                "timestamp": {"$gte": start_at, "$lt": end_at},
                "reverted": {"$ne": True},
            }, {"w_id": 1, "l_id": 1, "challenger_id": 1, "opponent_id": 1})
            async for match in cursor:
                for key in ("w_id", "l_id"):
                    uid = str(match.get(key) or "")
                    if uid in drivers:
                        drivers[uid]["played"] += 1
                        if key == "w_id":
                            drivers[uid]["wins"] += 1

        rows = list(drivers.values())

        def division_for_pi(pi):
            from ..core.core import get_division_for_pi
            return get_division_for_pi(pi).get("name", "Unranked")

        for row in rows:
            row["division"] = division_for_pi(row["garage_pi"])

        rows.sort(key=lambda x: (-x["elo"], x["name"].casefold()))
        divisions = {}
        for row in rows:
            divisions.setdefault(row["division"], []).append(row)

        archives = []
        async for archive in self.bot.db.season_history.find({"guild_id": guild_id}).sort("season_number", -1).limit(20):
            archives.append({
                "season": int(archive.get("season_number", 0) or 0),
                "player_count": int(archive.get("player_count", len(archive.get("standings", []))) or 0),
                "closed_at": archive.get("closed_at"),
            })

        return web.json_response({
            "season": season_number,
            "active": bool(state.get("season_active", False)),
            "starts_at": start_at,
            "ends_at": end_at,
            "divisions": {key: value for key, value in divisions.items()},
            "all": rows,
            "top_overall": rows[:5],
            "most_active": sorted(rows, key=lambda x: (-x["played"], -x["wins"], -x["elo"], x["name"].casefold()))[:5],
            "most_wins": sorted(rows, key=lambda x: (-x["wins"], -x["played"], -x["elo"], x["name"].casefold()))[:5],
            "past_seasons": archives,
        })

    async def clubs_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("clubs.html", request)

    async def clubs(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        guild_ids = {str(x) for x in user.guild_ids}
        rows = []
        async for club in self.bot.db.clubs.find({"guild_id": {"$in": list(guild_ids)}}).sort("name_ci", 1):
            club["id"] = str(club.pop("_id"))
            members = []
            async for member in self.bot.db.club_members.find({"club_id": club["id"]}).sort("joined_at", 1):
                member.pop("_id", None)
                prefs = await self.bot.db.web_preferences.find_one({"_id": f"{club['guild_id']}_{member.get('user_id', '')}"}) or {}
                connection = prefs.get("asphalt_connection") or {}
                member["asphalt_verified"] = connection.get("status") == "verified"
                member["asphalt_game_name"] = connection.get("game_name", "")
                member["asphalt_game_id"] = connection.get("game_id", "")
                members.append(member)
            club["members"] = members
            club["member_count"] = len(members)
            club["mine"] = any(str(m.get("user_id")) == str(user.user_id) for m in members)
            club["leader"] = str(club.get("leader_id")) == str(user.user_id)
            club["tournament_count"] = await self.bot.db.tournament_club_registrations.count_documents({"club_id": club["id"]})
            club["tournament_pending_count"] = await self.bot.db.tournament_club_registrations.count_documents({"club_id": club["id"], "status": "pending"})
            club["tournament_accepted_count"] = await self.bot.db.tournament_club_registrations.count_documents({"club_id": club["id"], "status": {"$in": ["accepted", "checked_in"]}})

            # Build the club's tournament W/L from verified, completed team matches.
            # Byes are intentionally excluded so they do not inflate a club's record.
            wins = 0
            losses = 0
            recent_results = []
            club_names = {}
            async for other_club in self.bot.db.clubs.find({"guild_id": club["guild_id"]}, {"name": 1}):
                club_names[str(other_club.get("_id"))] = str(other_club.get("name") or other_club.get("_id"))
            async for tournament in self.bot.db.tournaments.find({
                "guild_id": club["guild_id"],
                "team_size": {"$gt": 1},
            }, {"bracket": 1}):
                bracket = tournament.get("bracket") or {}
                groups = bracket.get("rounds") or bracket.get("winners") or []
                for group in groups:
                    for match in group.get("matches", []):
                        slots = [str(x) for x in (match.get("player_slots") or []) if x]
                        if len(slots) != 2 or club["id"] not in slots:
                            continue
                        if match.get("status") != "completed" or match.get("result_status") != "verified":
                            continue
                        winner = str(match.get("winner_id", ""))
                        if winner == club["id"]:
                            wins += 1
                            result = "WIN"
                        elif winner in slots:
                            losses += 1
                            result = "LOSS"
                        else:
                            continue
                        opponent_id = next((slot for slot in slots if slot != club["id"]), "")
                        opponent_name = opponent_id
                        opponent_name = club_names.get(opponent_id, opponent_id)
                        recent_results.append({
                            "result": result,
                            "opponent": opponent_name,
                            "tournament_name": str(tournament.get("name") or "Team Tournament"),
                            "date_label": str(match.get("completed_at") or match.get("updated_at") or tournament.get("updated_at") or "")[:10],
                        })
            recent_results.sort(key=lambda x: x.get("date_label", ""), reverse=True)
            club["recent_tournament_results"] = recent_results[:5]
            club["tournament_wins"] = wins
            club["tournament_losses"] = losses
            club["tournament_record"] = f"{wins}-{losses}"
            rows.append(club)
        return web.json_response({"clubs": rows})

    async def create_club(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        payload = await request.json()
        guild_id = str(payload.get("guild_id", "")).strip()
        if guild_id not in {str(x) for x in user.guild_ids}:
            raise web.HTTPForbidden(text="You are not a member of that server.")
        name = str(payload.get("name", "")).strip()
        if not name or len(name) > 40:
            raise web.HTTPBadRequest(text="Club name must be 1-40 characters.")
        if await self.bot.db.clubs.find_one({"guild_id": guild_id, "name_ci": name.casefold()}):
            raise web.HTTPConflict(text="That club name is already taken.")
        if await self.bot.db.club_members.find_one({"guild_id": guild_id, "user_id": str(user.user_id)}):
            raise web.HTTPConflict(text="You are already in a club in this server.")
        now = datetime.now(timezone.utc).isoformat()
        discord_link = str(payload.get("discord", "")).strip()
        if discord_link and not discord_link.lower().startswith(("http://", "https://")):
            raise web.HTTPBadRequest(text="Discord link must begin with http:// or https://.")
        raw_links = payload.get("links", [])
        if not isinstance(raw_links, list):
            raise web.HTTPBadRequest(text="Club links must be a list.")
        clean_links = []
        for link in raw_links[:5]:
            value = str(link or "").strip()
            if not value:
                continue
            if not value.lower().startswith(("http://", "https://")):
                raise web.HTTPBadRequest(text="Club links must begin with http:// or https://.")
            if len(value) > 300:
                raise web.HTTPBadRequest(text="Club links must be 300 characters or fewer.")
            clean_links.append(value)
        doc = {"guild_id": guild_id, "name": name, "name_ci": name.casefold(), "about": str(payload.get("about", payload.get("about_us", ""))).strip()[:500], "discord": discord_link[:300], "links": clean_links, "image": "", "leader_id": str(user.user_id), "member_count": 1, "created_at": now, "updated_at": now}
        try:
            result = await self.bot.db.clubs.insert_one(doc)
        except Exception as exc:
            if exc.__class__.__name__ == "DuplicateKeyError":
                raise web.HTTPConflict(text="That club name is already taken.")
            raise
        try:
            await self.bot.db.club_members.insert_one({"club_id": str(result.inserted_id), "guild_id": guild_id, "user_id": str(user.user_id), "username": str(user.global_name or user.username or user.user_id), "role": "leader", "joined_at": now})
        except Exception:
            # Compensate if the membership write fails so a club can never be left orphaned.
            await self.bot.db.clubs.delete_one({"_id": result.inserted_id})
            raise
        return web.json_response({"ok": True, "club_id": str(result.inserted_id), "message": "Club created."})

    async def update_club(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        payload = await request.json()
        from bson import ObjectId
        try:
            oid = ObjectId(str(payload.get("club_id", "")))
        except Exception:
            raise web.HTTPBadRequest(text="Invalid club ID.")
        club = await self.bot.db.clubs.find_one({"_id": oid})
        if not club or str(club.get("guild_id")) not in {str(x) for x in user.guild_ids}:
            raise web.HTTPNotFound(text="Club not found.")
        if str(club.get("leader_id")) != str(user.user_id):
            raise web.HTTPForbidden(text="Only the club leader can edit the club.")
        updates = {}
        if "name" in payload:
            name = str(payload.get("name", "")).strip()
            if not name or len(name) > 40:
                raise web.HTTPBadRequest(text="Club name must be 1-40 characters.")
            duplicate = await self.bot.db.clubs.find_one({"_id": {"$ne": oid}, "guild_id": club["guild_id"], "name_ci": name.casefold()})
            if duplicate:
                raise web.HTTPConflict(text="That club name is already taken.")
            updates.update(name=name, name_ci=name.casefold())
        if "about" in payload or "about_us" in payload:
            updates["about"] = str(payload.get("about", payload.get("about_us", ""))).strip()[:500]
        if "discord" in payload:
            discord_link = str(payload.get("discord", "")).strip()
            if discord_link and not discord_link.lower().startswith(("http://", "https://")):
                raise web.HTTPBadRequest(text="Discord link must begin with http:// or https://.")
            updates["discord"] = discord_link[:300]
        if "links" in payload:
            links = payload.get("links", [])
            if not isinstance(links, list):
                raise web.HTTPBadRequest(text="Club links must be a list.")
            clean_links = []
            for link in links[:5]:
                value = str(link or "").strip()
                if not value:
                    continue
                if not value.lower().startswith(("http://", "https://")):
                    raise web.HTTPBadRequest(text="Club links must begin with http:// or https://.")
                if len(value) > 300:
                    raise web.HTTPBadRequest(text="Club links must be 300 characters or fewer.")
                clean_links.append(value)
            updates["links"] = clean_links
        if "image" in payload:
            image = str(payload.get("image", "")).strip()
            if image and not image.startswith("data:image/"):
                raise web.HTTPBadRequest(text="Club image must be an uploaded image.")
            if len(image) > 3_000_000:
                raise web.HTTPBadRequest(text="Club image is too large.")
            updates["image"] = image
        if updates:
            updates["updated_at"] = datetime.now(timezone.utc).isoformat()
            await self.bot.db.clubs.update_one({"_id": oid}, {"$set": updates})
        return web.json_response({"ok": True, "message": "Club profile updated."})

    async def join_club(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        payload = await request.json()
        from bson import ObjectId
        try:
            oid = ObjectId(str(payload.get("club_id", "")))
        except Exception:
            raise web.HTTPBadRequest(text="Invalid club ID.")
        club = await self.bot.db.clubs.find_one({"_id": oid})
        if not club or str(club.get("guild_id")) not in {str(x) for x in user.guild_ids}:
            raise web.HTTPNotFound(text="Club not found.")
        member_filter = {"guild_id": club["guild_id"], "user_id": str(user.user_id)}
        if await self.bot.db.club_members.find_one(member_filter):
            raise web.HTTPConflict(text="You are already in a club in this server.")
        # Reserve a membership slot atomically. The unique membership index then
        # protects the user-level race, while member_count protects the 20-member cap.
        reservation = await self.bot.db.clubs.update_one(
            {"_id": oid, "$or": [{"member_count": {"$lt": 20}}, {"member_count": {"$exists": False}}]},
            {"$inc": {"member_count": 1}},
        )
        if not reservation.modified_count:
            raise web.HTTPConflict(text="That club is full.")
        now = datetime.now(timezone.utc).isoformat()
        try:
            await self.bot.db.club_members.insert_one({"club_id": str(oid), "guild_id": club["guild_id"], "user_id": str(user.user_id), "username": str(user.global_name or user.username or user.user_id), "role": "member", "joined_at": now})
        except Exception as exc:
            await self.bot.db.clubs.update_one({"_id": oid, "member_count": {"$gt": 0}}, {"$inc": {"member_count": -1}})
            if exc.__class__.__name__ == "DuplicateKeyError":
                raise web.HTTPConflict(text="You are already in a club in this server.")
            raise
        return web.json_response({"ok": True, "message": "You joined the club."})

    async def manage_club_member(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        payload = await request.json()
        from bson import ObjectId
        try:
            oid = ObjectId(str(payload.get("club_id", "")))
        except Exception:
            raise web.HTTPBadRequest(text="Invalid club ID.")
        club = await self.bot.db.clubs.find_one({"_id": oid})
        if not club or str(club.get("leader_id")) != str(user.user_id):
            raise web.HTTPForbidden(text="Only the club leader can manage members.")
        target = str(payload.get("user_id", "")).strip()
        if target == str(user.user_id):
            raise web.HTTPBadRequest(text="The club leader cannot manage their own membership.")
        member = await self.bot.db.club_members.find_one({"club_id": str(oid), "user_id": target})
        if not member:
            raise web.HTTPNotFound(text="Club member not found.")
        action = str(payload.get("action", "")).casefold()
        if action == "promote":
            value = "officer"
        elif action == "demote":
            value = "member"
        elif action == "kick":
            removed = await self.bot.db.club_members.delete_one({"_id": member["_id"]})
            if removed.deleted_count:
                await self.bot.db.clubs.update_one({"_id": oid, "member_count": {"$gt": 0}}, {"$inc": {"member_count": -1}})
            return web.json_response({"ok": True, "message": "Member removed from the club."})
        else:
            raise web.HTTPBadRequest(text="Unsupported member action.")
        await self.bot.db.club_members.update_one({"_id": member["_id"]}, {"$set": {"role": value}})
        return web.json_response({"ok": True, "message": "Member role updated."})

    async def notification_preferences(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        record = await self.bot.db.notification_preferences.find_one({"_id": str(user.user_id)}) or {}
        return web.json_response({
            "gauntlet_notifications": bool(record.get("gauntlet_notifications", False)),
            "tournament_notifications": bool(record.get("tournament_notifications", False)),
            "gauntlet_lead_days": float(record.get("gauntlet_lead_days", 1) or 1),
            "tournament_lead_days": float(record.get("tournament_lead_days", 1) or 1),
            "event_lead_days": {str(k): float(v) for k, v in (record.get("event_lead_days") or {}).items()},
            "subscribed_event_ids": [str(x) for x in (record.get("subscribed_event_ids") or [])],
            "muted_event_ids": [str(x) for x in (record.get("muted_event_ids") or [])],
        })

    async def update_notification_category(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        payload = await request.json()
        category = str(payload.get("category", "")).strip().lower()
        if category not in {"gauntlet", "tournament"}:
            raise web.HTTPBadRequest(text="Unsupported notification category.")
        enabled = bool(payload.get("enabled", False))
        field = f"{category}_notifications"
        await self.bot.db.notification_preferences.update_one(
            {"_id": str(user.user_id)},
            {"$set": {field: enabled, "updated_at": time.time()}},
            upsert=True,
        )
        return web.json_response({"ok": True, "category": category, "enabled": enabled})

    async def update_notification_timing(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        payload = await request.json()
        scope = str(payload.get("scope", "")).strip().lower()
        lead_days = payload.get("lead_days", 1)
        try:
            lead_days = float(lead_days)
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="Notification timing must be a number of days.")
        if not 0 <= lead_days <= 365:
            raise web.HTTPBadRequest(text="Notification timing must be between 0 and 30 days.")
        if scope not in {"gauntlet", "tournament"}:
            raise web.HTTPBadRequest(text="Unsupported notification category.")
        await self.bot.db.notification_preferences.update_one(
            {"_id": str(user.user_id)},
            {"$set": {f"{scope}_lead_days": lead_days, "updated_at": time.time()}},
            upsert=True,
        )
        return web.json_response({"ok": True, "scope": scope, "lead_days": lead_days})

    async def update_notification_event(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        payload = await request.json()
        event_id = str(payload.get("event_id", "")).strip()[:180]
        enabled = bool(payload.get("enabled", False))
        if not event_id:
            raise web.HTTPBadRequest(text="Event ID is required.")
        # Event subscriptions are opt-in overrides. A user can keep an entire
        # category off and still subscribe to one calendar event.
        lead_days = payload.get("lead_days")
        set_fields = {"updated_at": time.time()}
        if lead_days is not None:
            try:
                lead_days = float(lead_days)
            except (TypeError, ValueError):
                raise web.HTTPBadRequest(text="Event notification timing must be a number of days.")
            if not 0 <= lead_days <= 365:
                raise web.HTTPBadRequest(text="Event notification timing must be between 0 and 30 days.")
            set_fields[f"event_lead_days.{event_id}"] = lead_days
        if enabled:
            update = {
                "$addToSet": {"subscribed_event_ids": event_id},
                "$pull": {"muted_event_ids": event_id},
                "$set": set_fields,
            }
        else:
            update = {
                "$pull": {"subscribed_event_ids": event_id},
                "$addToSet": {"muted_event_ids": event_id},
                "$set": set_fields,
            }
        await self.bot.db.notification_preferences.update_one(
            {"_id": str(user.user_id)}, update, upsert=True
        )
        return web.json_response({"ok": True, "event_id": event_id, "enabled": enabled})

    async def calendar_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("calendar.html", request)

    async def calendar(self, request: web.Request) -> web.Response:
        """Return live Gauntlet season and tournament dates for the calendar UI."""
        user = await self.require_user(request)
        guild_ids = [str(x) for x in user.guild_ids]
        events = []
        seasons = []
        for guild_id in guild_ids:
            guild = self.bot.get_guild(int(guild_id)) if guild_id.isdigit() else None
            guild_name = getattr(guild, "name", guild_id) or guild_id
            state = await self.bot.db.season_state.find_one({"_id": f"guild_{guild_id}"}) or {}
            season_number = int(state.get("season_number", 1) or 1)
            start_at = float(state.get("starts_at", 0) or 0)
            end_at = float(state.get("ends_at", 0) or 0)
            if start_at:
                seasons.append({
                    "guild_id": guild_id,
                    "guild_name": guild_name,
                    "season": season_number,
                    "starts_at": start_at,
                    "ends_at": end_at,
                    "active": bool(state.get("season_active", False)),
                })
                events.append({
                    "id": f"season-start-{guild_id}-{season_number}",
                    "type": "gauntlet",
                    "kind": "start",
                    "title": f"Gauntlet Season {season_number} Starts",
                    "guild_id": guild_id,
                    "guild_name": guild_name,
                    "start": start_at,
                    "end": start_at,
                    "season": season_number,
                    "status": "active" if state.get("season_active") else "scheduled",
                })
            if end_at:
                events.append({
                    "id": f"season-end-{guild_id}-{season_number}",
                    "type": "gauntlet",
                    "kind": "end",
                    "title": f"Gauntlet Season {season_number} Ends",
                    "guild_id": guild_id,
                    "guild_name": guild_name,
                    "start": end_at,
                    "end": end_at,
                    "season": season_number,
                    "status": "active" if state.get("season_active") else "scheduled",
                })
            async for item in self.bot.db.tournaments.find({"guild_id": guild_id}).sort("start_time", 1):
                tid = str(item.get("_id"))
                start_raw = item.get("start_time")
                end_raw = item.get("end_time") or item.get("completed_at")
                registration_raw = item.get("registration_deadline")
                def iso_ts(value):
                    if not value:
                        return None
                    try:
                        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
                    except Exception:
                        return None
                start_ts = iso_ts(start_raw)
                end_ts = iso_ts(end_raw)
                reg_ts = iso_ts(registration_raw)
                base = {
                    "id": tid,
                    "type": "tournament",
                    "title": str(item.get("name", "Tournament")),
                    "guild_id": guild_id,
                    "guild_name": guild_name,
                    "season": None,
                    "status": str(item.get("status", "registration_open")),
                }
                if start_ts:
                    events.append({**base, "kind": "start", "start": start_ts, "end": start_ts})
                if end_ts:
                    events.append({**base, "id": tid + "-end", "kind": "end", "start": end_ts, "end": end_ts})
                if reg_ts:
                    events.append({**base, "id": tid + "-registration", "kind": "registration", "title": str(item.get("name", "Tournament")) + " Registration Closes", "start": reg_ts, "end": reg_ts})
        events.sort(key=lambda x: (float(x.get("start") or 0), str(x.get("title", ""))))
        return web.json_response({"events": events, "seasons": seasons, "server_time": time.time()})

    async def tournaments_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("tournaments.html", request)

    async def tournaments(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        guild_ids = set(str(x) for x in user.guild_ids)
        rows = []
        async for item in self.bot.db.tournaments.find({"guild_id": {"$in": list(guild_ids)}}).sort("start_time", 1):
            item["id"] = str(item.get("_id"))
            item.pop("_id", None)
            if int(item.get("team_size", 1)) > 1:
                count = await self.bot.db.tournament_club_registrations.count_documents(
                    {"tournament_id": item["id"], "status": {"$in": ["pending", "accepted", "checked_in"]}}
                )
            else:
                count = await self.bot.db.tournament_registrations.count_documents(
                    {"tournament_id": item["id"], "status": {"$in": ["pending", "accepted", "checked_in"]}}
                )
            item["registration_count"] = count
            item["format_label"] = {"single_elimination": "Single Elimination", "round_robin": "Round Robin"}.get(
                item.get("format"), str(item.get("format", "Tournament")).replace("_", " ").title()
            )
            item["eligibility_label"] = "Gauntlet registered only" if item.get("gauntlet_only") else "Open to players"
            if item.get("start_time"):
                try:
                    item["start_time_label"] = datetime.fromisoformat(item["start_time"]).astimezone().strftime("%b %d, %Y • %I:%M %p")
                except Exception:
                    item["start_time_label"] = "TBD"
            else:
                item["start_time_label"] = "TBD"
            rows.append(item)
        return web.json_response({"tournaments": rows})

    async def tournament_detail(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        from bson import ObjectId
        tournament_id = request.match_info.get("tournament_id", "")
        try:
            oid = ObjectId(tournament_id)
        except Exception:
            raise web.HTTPBadRequest(text="Invalid tournament ID.")
        item = await self.bot.db.tournaments.find_one({"_id": oid})
        if not item or str(item.get("guild_id")) not in set(str(x) for x in user.guild_ids):
            raise web.HTTPNotFound(text="Tournament not found.")
        item["id"] = tournament_id
        item.pop("_id", None)
        registrations = []
        async for row in self.bot.db.tournament_registrations.find(
            {"tournament_id": tournament_id, "status": {"$in": ["pending", "accepted", "checked_in"]}}
        ).sort("registered_at", 1):
            row.pop("_id", None)
            registrations.append(row)
        for row in registrations:
            prefs = await self.bot.db.web_preferences.find_one({"_id": f"{item['guild_id']}_{row.get('user_id', '')}"}) or {}
            connection = prefs.get("asphalt_connection") or {}
            row["asphalt_verified"] = connection.get("status") == "verified"
            row["asphalt_game_name"] = connection.get("game_name", "")
            row["asphalt_game_id"] = connection.get("game_id", "")
        item["registrations"] = registrations
        if int(item.get("team_size", 1)) > 1:
            clubs = []
            async for reg in self.bot.db.tournament_club_registrations.find({"tournament_id": tournament_id}).sort("registered_at", 1):
                club = await self.bot.db.clubs.find_one({"_id": ObjectId(reg["club_id"])})
                if not club:
                    continue
                members = []
                async for member in self.bot.db.club_members.find({"club_id": reg["club_id"]}).sort("joined_at", 1):
                    member.pop("_id", None)
                    prefs = await self.bot.db.web_preferences.find_one({"_id": f"{reg.get('guild_id', item.get('guild_id', ''))}_{member.get('user_id', '')}"}) or {}
                    connection = prefs.get("asphalt_connection") or {}
                    member["asphalt_verified"] = connection.get("status") == "verified"
                    member["asphalt_game_name"] = connection.get("game_name", "")
                    member["asphalt_game_id"] = connection.get("game_id", "")
                    members.append(member)
                clubs.append({"id": reg["club_id"], "name": club.get("name", "Club"), "image": club.get("image", ""), "about": club.get("about", ""), "status": reg.get("status", "pending"), "lineup": reg.get("lineup", []), "members": members, "registered_by": reg.get("registered_by"), "leader_id": club.get("leader_id")})
            item["clubs"] = clubs
            item["teams"] = []
        else:
            item["clubs"] = []
            item["teams"] = []
        return web.json_response(item)

    async def create_tournament(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        try:
            payload = await request.json()
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        name = str(payload.get("name", "")).strip()
        if not name:
            raise web.HTTPBadRequest(text="Tournament name is required.")
        max_players = int(payload.get("max_players", 32))
        if max_players < 2 or max_players > 256:
            raise web.HTTPBadRequest(text="Maximum players must be between 2 and 256.")
        fmt = str(payload.get("format", "single_elimination")).strip().casefold()
        team_size = int(payload.get("team_size", 1))
        if team_size not in {1, 2, 3, 4}:
            raise web.HTTPBadRequest(text="Team size must be 1v1, 2v2, 3v3, or 4v4.")
        if fmt not in {"single_elimination", "double_elimination", "round_robin"}:
            raise web.HTTPBadRequest(text="Unsupported tournament format.")
        from ALU_Gauntlet.core.tournament import generate_tournament_bracket
        bracket = generate_tournament_bracket(fmt, max_players)
        now = datetime.now(timezone.utc).isoformat()
        registration_deadline = str(payload.get("registration_deadline", "")).strip() or None
        start_time = str(payload.get("start_time", "")).strip() or None
        end_time = str(payload.get("end_time", "")).strip() or None
        if start_time and end_time:
            try:
                if datetime.fromisoformat(end_time).astimezone() <= datetime.fromisoformat(start_time).astimezone():
                    raise web.HTTPBadRequest(text="Tournament end time must be after the start time.")
            except ValueError:
                raise web.HTTPBadRequest(text="Invalid tournament start or end time.")
        tournament = {
            "guild_id": guild_id,
            "name": name,
            "description": str(payload.get("description", "")).strip()[:500],
            "format": fmt,
            "max_players": max_players,
            "team_size": team_size,
            "bracket": bracket,
            "bracket_version": 1,
            "gauntlet_only": bool(payload.get("gauntlet_only", False)),
            "registration_deadline": registration_deadline,            "start_time": start_time,            "end_time": end_time,
            "status": "registration_open",
            "created_by": str(user.user_id),
            "created_at": now,
            "updated_at": now,
        }
        result = await self.bot.db.tournaments.insert_one(tournament)
        return web.json_response({"ok": True, "tournament_id": str(result.inserted_id)})

    async def register_tournament(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        try:
            payload = await request.json()
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        tournament_id = str(payload.get("tournament_id", "")).strip()
        if not tournament_id:
            raise web.HTTPBadRequest(text="tournament_id is required.")
        from bson import ObjectId
        try:
            oid = ObjectId(tournament_id)
        except Exception:
            raise web.HTTPBadRequest(text="Invalid tournament ID.")
        tournament = await self.bot.db.tournaments.find_one({"_id": oid})
        if not tournament or str(tournament.get("guild_id")) not in set(str(x) for x in user.guild_ids):
            raise web.HTTPNotFound(text="Tournament not found.")
        if tournament.get("status") not in {"registration_open", "open"}:
            raise web.HTTPConflict(text="Tournament registration is closed.")
        team_size = int(tournament.get("team_size", 1))
        if team_size > 1:
            club_id = str(payload.get("club_id", "")).strip()
            from bson import ObjectId
            try:
                club_oid = ObjectId(club_id)
            except Exception:
                raise web.HTTPBadRequest(text="A valid club_id is required for team tournaments.")
            club = await self.bot.db.clubs.find_one({"_id": club_oid, "guild_id": str(tournament["guild_id"])})
            if not club:
                raise web.HTTPNotFound(text="Club not found in this server.")
            membership = await self.bot.db.club_members.find_one({"club_id": club_id, "user_id": str(user.user_id)})
            if not membership:
                raise web.HTTPForbidden(text="You must be a member of the club to register it.")
            if str(club.get("leader_id")) != str(user.user_id):
                raise web.HTTPForbidden(text="Only the club leader can enter a club in a tournament.")
            count = await self.bot.db.tournament_club_registrations.count_documents(
                {"tournament_id": tournament_id, "status": {"$in": ["pending", "accepted", "checked_in"]}}
            )
            if count >= int(tournament.get("max_players", 32)):
                raise web.HTTPConflict(text="This tournament is full.")
            existing = await self.bot.db.tournament_club_registrations.find_one(
                {"tournament_id": tournament_id, "club_id": club_id, "status": {"$in": ["pending", "accepted", "checked_in"]}}
            )
            if existing:
                raise web.HTTPConflict(text="This club is already registered for the tournament.")
            try:
                await self.bot.db.tournament_club_registrations.insert_one({
                    "tournament_id": tournament_id, "guild_id": str(tournament["guild_id"]),
                    "club_id": club_id, "club_name": club.get("name", "Club"),
                    "team_size": team_size, "status": "pending",
                    "registered_by": str(user.user_id),
                    "registered_at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as exc:
                if exc.__class__.__name__ == "DuplicateKeyError":
                    raise web.HTTPConflict(text="This club is already registered for the tournament.")
                raise
            return web.json_response({"ok": True, "message": "Club registration submitted for staff review."})
        count = await self.bot.db.tournament_registrations.count_documents(
            {"tournament_id": tournament_id, "status": {"$in": ["pending", "accepted"]}}
        )
        if count >= int(tournament.get("max_players", 32)):
            raise web.HTTPConflict(text="This tournament is full.")
        if tournament.get("gauntlet_only"):
            profile = await self.bot.db.drivers.find_one({"_id": f'{tournament["guild_id"]}_{user.user_id}'})
            current_season = await get_current_season_number(str(tournament["guild_id"]))
            if not profile or not profile.get("season_registered") or int(profile.get("season_number", 0) or 0) != int(current_season):
                raise web.HTTPForbidden(text="This tournament is limited to drivers registered for the current Gauntlet season.")
        existing = await self.bot.db.tournament_registrations.find_one(
            {"tournament_id": tournament_id, "user_id": str(user.user_id), "status": {"$in": ["pending", "accepted"]}}
        )
        if existing:
            raise web.HTTPConflict(text="You are already registered for this tournament.")
        try:
            await self.bot.db.tournament_registrations.insert_one({
                "tournament_id": tournament_id,
            "guild_id": str(tournament["guild_id"]),
            "user_id": str(user.user_id),
            "username": str(user.global_name or user.username or user.user_id),
            "status": "pending",
            "registered_at": datetime.now(timezone.utc).isoformat(),
        })
        except Exception as exc:
            if exc.__class__.__name__ == "DuplicateKeyError":
                raise web.HTTPConflict(text="You are already registered for this tournament.")
            raise
        return web.json_response({"ok": True, "message": "Tournament registration submitted for staff review."})

    async def tournament_club_lineup(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        from bson import ObjectId
        payload = await request.json()
        tournament_id = str(payload.get("tournament_id", "")).strip()
        club_id = str(payload.get("club_id", "")).strip()
        try:
            ObjectId(tournament_id)
            ObjectId(club_id)
        except Exception:
            raise web.HTTPBadRequest(text="Invalid tournament or club ID.")
        tournament = await self.bot.db.tournaments.find_one({"_id": ObjectId(tournament_id)})
        club = await self.bot.db.clubs.find_one({"_id": ObjectId(club_id)})
        if not tournament or not club or str(tournament.get("guild_id")) not in {str(x) for x in user.guild_ids} or str(club.get("guild_id")) != str(tournament.get("guild_id")):
            raise web.HTTPNotFound(text="Tournament or club not found.")
        if str(club.get("leader_id")) != str(user.user_id):
            raise web.HTTPForbidden(text="Only the club leader can set the tournament lineup.")
        if tournament.get("status") not in {"registration_open", "open"}:
            raise web.HTTPConflict(text="Tournament lineups are locked once the tournament starts.")
        reg = await self.bot.db.tournament_club_registrations.find_one({"tournament_id": tournament_id, "club_id": club_id})
        if not reg:
            raise web.HTTPNotFound(text="This club is not registered for the tournament.")
        size = int(tournament.get("team_size", 1))
        lineup = [str(x).strip() for x in (payload.get("lineup") or []) if str(x).strip()]
        if len(lineup) != size or len(set(lineup)) != size:
            raise web.HTTPBadRequest(text="Select exactly " + str(size) + " unique drivers for the lineup.")
        member_rows = await self.bot.db.club_members.find({"club_id": club_id}).to_list(length=20)
        members = {str(x["user_id"]) for x in member_rows}
        if not set(lineup).issubset(members):
            raise web.HTTPBadRequest(text="Every lineup driver must be a current club member.")
        await self.bot.db.tournament_club_registrations.update_one({"_id": reg["_id"]}, {"$set": {"lineup": lineup, "updated_at": datetime.now(timezone.utc).isoformat()}})
        return web.json_response({"ok": True, "message": str(size) + "v" + str(size) + " tournament lineup saved.", "lineup": lineup})

    async def _claim_tournament_action(self, tournament_id, match_id, action):
        """Claim a short-lived MongoDB lock shared by web tournament actions."""
        from datetime import datetime, timezone, timedelta
        from pymongo.errors import DuplicateKeyError
        now = datetime.now(timezone.utc)
        doc = {"tournament_id": str(tournament_id), "match_id": str(match_id), "action": str(action),
               "claimed_at": now, "expires_at": now + timedelta(seconds=60)}
        try:
            await self.bot.db.tournament_action_locks.insert_one(doc)
            return True
        except DuplicateKeyError:
            replaced = await self.bot.db.tournament_action_locks.find_one_and_replace(
                {"tournament_id": str(tournament_id), "match_id": str(match_id), "expires_at": {"$lt": now}}, doc
            )
            return replaced is not None

    async def _release_tournament_action(self, tournament_id, match_id):
        await self.bot.db.tournament_action_locks.delete_one(
            {"tournament_id": str(tournament_id), "match_id": str(match_id)}
        )

    async def tournament_match_result(self, request: web.Request) -> web.Response:
        """Submit a participant result for staff verification."""
        user = await self.require_user(request)
        from bson import ObjectId
        payload = await request.json()
        try:
            oid = ObjectId(str(payload.get("tournament_id", "")))
        except Exception:
            raise web.HTTPBadRequest(text="Invalid tournament ID.")
        t = await self.bot.db.tournaments.find_one({"_id": oid})
        if not t or str(t.get("guild_id")) not in set(str(x) for x in user.guild_ids):
            raise web.HTTPNotFound(text="Tournament not found.")
        if t.get("status") != "live":
            raise web.HTTPConflict(text="Tournament is not live.")
        match_id = str(payload.get("match_id", "")).strip()
        winner_id = str(payload.get("winner_id", "")).strip()
        proof_url = str(payload.get("proof_url", "")).strip()
        notes = str(payload.get("notes", "")).strip()[:500]
        bracket = t.get("bracket") or {}
        matches = [m for group in (bracket.get("rounds") or bracket.get("winners") or []) for m in group.get("matches", [])]
        match = next((m for m in matches if str(m.get("id")) == match_id), None)
        if not match:
            raise web.HTTPNotFound(text="Match not found.")
        slots = [str(x) for x in (match.get("player_slots") or []) if x]
        if winner_id not in slots:
            raise web.HTTPBadRequest(text="Winner must be one of the entrants in this match.")
        team_size = int(t.get("team_size", 1))
        participant_ok = False
        if team_size > 1:
            reg = await self.bot.db.tournament_club_registrations.find_one(
                {"tournament_id": str(oid), "club_id": {"$in": slots}, "lineup": str(user.user_id), "status": {"$in": ["accepted", "checked_in"]}}
            )
            participant_ok = bool(reg)
        else:
            participant_ok = str(user.user_id) in slots
        if not participant_ok and not user.staff:
            raise web.HTTPForbidden(text="Only a participant in this match can submit its result.")
        if match.get("result_status") == "pending":
            raise web.HTTPConflict(text="This match already has a result waiting for staff verification.")
        if match.get("status") != "ready":
            raise web.HTTPConflict(text="This match is not ready for a result submission.")
        if match.get("status") == "completed":
            raise web.HTTPConflict(text="This match is already completed.")
        if proof_url and not proof_url.lower().startswith(("http://", "https://")):
            raise web.HTTPBadRequest(text="Proof must be a valid URL.")
        if not await self._claim_tournament_action(str(oid), match_id, "submit"):
            raise web.HTTPConflict(text="Another result submission is already being processed for this match.")
        try:
            match.update({"result_status":"pending","submitted_by":str(user.user_id),"submitted_at":datetime.now(timezone.utc).isoformat(),"winner_id":winner_id,"proof_url":proof_url,"result_notes":notes})
            await self.bot.db.tournaments.update_one({"_id": oid},{"$set":{"bracket":bracket,"updated_at":datetime.now(timezone.utc).isoformat()}})
        finally:
            await self._release_tournament_action(str(oid), match_id)
        cfg = await self.bot.db.settings.find_one({"_id": str(t.get("guild_id"))}) or {}
        channel_id = cfg.get("match_results_channel_id")
        channel = self.bot.get_channel(int(channel_id)) if channel_id else None
        if channel is not None:
            try:
                await channel.send("🏁 **Tournament Result Pending Verification**\n**"+str(t.get("name","Tournament"))+"** • "+match_id+"\nWinner: <@"+winner_id+">\nSubmitted by: <@"+str(user.user_id)+">"+(("\nProof: "+proof_url) if proof_url else "")+"\nStaff: use the Tournament Center to verify this result.")
            except Exception:
                log.exception("Unable to post tournament result notice")
        return web.json_response({"ok": True, "message": "Result submitted for staff verification."})

    async def tournament_verify_result(self, request: web.Request) -> web.Response:
        """Staff verification endpoint that advances a single-elimination bracket atomically."""
        user, guild_id, _ = await self.require_admin(request)
        from bson import ObjectId
        payload = await request.json()
        try:
            oid = ObjectId(str(payload.get("tournament_id", "")))
        except Exception:
            raise web.HTTPBadRequest(text="Invalid tournament ID.")
        t = await self.bot.db.tournaments.find_one({"_id": oid, "guild_id": guild_id})
        if not t:
            raise web.HTTPNotFound(text="Tournament not found.")
        if t.get("status") != "live":
            raise web.HTTPConflict(text="Tournament is not live.")
        bracket = t.get("bracket") or {}
        match_id = str(payload.get("match_id", "")).strip()
        action = str(payload.get("action", "approve")).strip().casefold()
        if action not in {"approve", "reject"}:
            raise web.HTTPBadRequest(text="Action must be approve or reject.")
        groups = bracket.get("rounds") or bracket.get("winners") or []
        match = next((m for group in groups for m in group.get("matches", []) if str(m.get("id")) == match_id), None)
        if not match:
            raise web.HTTPNotFound(text="Match not found.")
        if match.get("result_status") != "pending":
            raise web.HTTPConflict(text="This match does not have a pending result.")
        if not await self._claim_tournament_action(str(oid), str(match_id), "verify"):
            raise web.HTTPConflict(text="Another staff action is already processing this match.")
        try:
            if action == "reject":
                for key in ("result_status", "winner_id", "submitted_by", "submitted_at", "proof_url", "result_notes"):
                    match.pop(key, None)
                match["status"] = "ready"
                message = "Result rejected. The match is ready for another submission."
            else:
                winner_id = str(match.get("winner_id", ""))
                slots = [str(x) for x in (match.get("player_slots") or []) if x]
                if winner_id not in slots:
                    raise web.HTTPConflict(text="Pending result has no valid winner.")
                match["result_status"] = "verified"
                match["verified_by"] = str(user.user_id)
                match["verified_at"] = datetime.now(timezone.utc).isoformat()
                match["status"] = "completed"
                target = match.get("winner_to")
                if target:
                    target_match = next(
                        (nxt for group in groups for nxt in group.get("matches", []) if str(nxt.get("id")) == str(target)),
                        None,
                    )
                    if target_match is None:
                        raise web.HTTPConflict(text="Bracket advancement target is invalid.")
                    ns = list(target_match.get("player_slots") or [None, None])
                    while len(ns) < 2:
                        ns.append(None)
                    if winner_id in [str(x) for x in ns if x is not None]:
                        raise web.HTTPConflict(text="Winner has already advanced to the target match.")
                    if all(ns):
                        raise web.HTTPConflict(text="Bracket advancement target is already occupied.")
                    empty_index = ns.index(None)
                    ns[empty_index] = winner_id
                    target_match["player_slots"] = ns
                    if all(ns):
                        target_match["status"] = "ready"
                elif str(match.get("bracket", "winners")) == "winners" and (match.get("round") or 0) == len(groups):
                    t["status"] = "completed"
                    t["champion_id"] = winner_id
                    t["completed_at"] = datetime.now(timezone.utc).isoformat()
                message = "Result verified and winner advanced."
            await self.bot.db.tournaments.update_one(
                {"_id": oid},
                {"$set": {
                    "bracket": bracket,
                    "status": t.get("status", "live"),
                    "champion_id": t.get("champion_id"),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
        finally:
            await self._release_tournament_action(str(oid), str(match_id))

        cfg = await self.bot.db.settings.find_one({"_id": guild_id}) or {}
        channel_id = cfg.get("match_results_channel_id")
        channel = self.bot.get_channel(int(channel_id)) if channel_id else None
        if channel is not None:
            try:
                await channel.send(
                    "🏆 **Tournament Result " + ("Approved" if action != "reject" else "Rejected") +
                    "** • " + str(t.get("name", "Tournament")) + " • " + match_id
                )
            except Exception:
                log.exception("Unable to post tournament verification notice")
        return web.json_response({
            "ok": True,
            "message": message,
            "bracket": bracket,
            "champion_id": t.get("champion_id"),
        })

    async def tournament_checkin(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        from bson import ObjectId
        try:
            oid = ObjectId(str((await request.json()).get("tournament_id", "")))
        except Exception:
            raise web.HTTPBadRequest(text="Invalid tournament ID.")
        t = await self.bot.db.tournaments.find_one({"_id": oid})
        if not t or str(t.get("guild_id")) not in set(str(x) for x in user.guild_ids):
            raise web.HTTPNotFound(text="Tournament not found.")
        if t.get("status") not in {"registration_open", "open"}:
            raise web.HTTPConflict(text="Check-in is closed once the tournament is live or completed.")
        tid = str(oid)
        if int(t.get("team_size", 1)) > 1:
            checkin_payload = await request.json()
            requested_club_id = str(checkin_payload.get("club_id", "")).strip()
            reg_query = {"tournament_id": tid, "status": {"$in": ["pending", "accepted", "checked_in"]}}
            if requested_club_id:
                if not ObjectId.is_valid(requested_club_id):
                    raise web.HTTPBadRequest(text="Invalid club ID.")
                reg_query["club_id"] = requested_club_id
            else:
                # The frontend can omit club_id; resolve the caller's own club safely.
                owned_clubs = [str(x["_id"]) async for x in self.bot.db.clubs.find({"guild_id": str(t["guild_id"]), "leader_id": str(user.user_id)}, {"_id": 1})]
                if not owned_clubs:
                    raise web.HTTPForbidden(text="Only a club leader can check in a team.")
                reg_query["club_id"] = {"$in": owned_clubs}
            reg = await self.bot.db.tournament_club_registrations.find_one(reg_query)
            if not reg:
                raise web.HTTPConflict(text="Your club must be registered before checking in.")
            club = await self.bot.db.clubs.find_one({"_id": ObjectId(reg["club_id"])}) if ObjectId.is_valid(str(reg["club_id"])) else None
            if not club or str(club.get("leader_id")) != str(user.user_id):
                raise web.HTTPForbidden(text="Only the club leader can check in the club.")
            lineup = reg.get("lineup") or []
            if len(lineup) != int(t.get("team_size", 1)):
                raise web.HTTPConflict(text="Save a complete tournament lineup before checking in.")
            await self.bot.db.tournament_club_registrations.update_one(
                {"_id": reg["_id"]},
                {"$set": {"status": "checked_in", "checked_in_at": datetime.now(timezone.utc).isoformat()}},
            )
        else:
            result = await self.bot.db.tournament_registrations.update_one(
                {"tournament_id": tid, "user_id": str(user.user_id), "status": {"$in": ["pending", "accepted"]}},
                {"$set": {"status": "checked_in", "checked_in_at": datetime.now(timezone.utc).isoformat()}},
            )
            if not result.modified_count:
                raise web.HTTPConflict(text="You must be registered before checking in.")
        return web.json_response({"ok": True, "message": "You are checked in."})

    async def tournament_start(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        from bson import ObjectId
        from ALU_Gauntlet.core.tournament import generate_tournament_bracket
        try:
            oid = ObjectId(str((await request.json()).get("tournament_id", "")))
        except Exception:
            raise web.HTTPBadRequest(text="Invalid tournament ID.")
        t = await self.bot.db.tournaments.find_one({"_id": oid, "guild_id": guild_id})
        if not t:
            raise web.HTTPNotFound(text="Tournament not found.")
        if t.get("status") not in {"registration_open", "open"}:
            raise web.HTTPConflict(text="Only a tournament still in registration can be started.")
        if t.get("format") != "single_elimination":
            raise web.HTTPConflict(text="This tournament format does not yet have a complete live state-transition workflow.")
        players = []
        if int(t.get("team_size", 1)) > 1:
            async for row in self.bot.db.tournament_club_registrations.find(
                {"tournament_id": str(oid), "status": {"$in": ["accepted", "checked_in"]}}
            ).sort("registered_at", 1):
                lineup = row.get("lineup") or []
                if len(lineup) != int(t.get("team_size", 1)):
                    raise web.HTTPConflict(text="Every registered club must save a complete tournament lineup before the tournament starts.")
                players.append(str(row["club_id"]))
        else:
            async for row in self.bot.db.tournament_registrations.find(
                {"tournament_id": str(oid), "status": {"$in": ["accepted", "checked_in"]}}
            ).sort("registered_at", 1):
                players.append(str(row["user_id"]))
        if len(players) < 2:
            raise web.HTTPConflict(text="At least 2 accepted entrants are required to start.")
        if t.get("format") in {"single_elimination", "double_elimination"} and len(players) > int(t.get("max_players", 32)):
            raise web.HTTPConflict(text="Too many entrants for this tournament.")
        bracket = generate_tournament_bracket(t["format"], int(t["max_players"]))
        if t["format"] == "single_elimination":
            slots = players + [None] * (int(t["max_players"]) - len(players))
            matches = bracket["rounds"][0]["matches"]
            for i, match in enumerate(matches):
                match["player_slots"] = [slots[i * 2], slots[i * 2 + 1]]
                match["status"] = "ready" if all(match["player_slots"]) else "bye" if any(match["player_slots"]) else "waiting"
            # Resolve byes immediately so a tournament with fewer entrants than
            # the configured bracket size can still advance normally.
            changed = True
            while changed:
                changed = False
                for group in bracket.get("rounds", []):
                    for match in group.get("matches", []):
                        slots_now = [x for x in (match.get("player_slots") or []) if x]
                        if match.get("status") == "bye" and len(slots_now) == 1:
                            winner = str(slots_now[0])
                            match["winner_id"] = winner
                            match["status"] = "completed"
                            match["result_status"] = "verified"
                            target = match.get("winner_to")
                            if target:
                                for next_group in bracket.get("rounds", []):
                                    for nxt in next_group.get("matches", []):
                                        if nxt.get("id") == target:
                                            next_slots = nxt.setdefault("player_slots", [None, None])
                                            if winner not in next_slots:
                                                next_slots[0 if next_slots[0] is None else 1] = winner
                                            if all(next_slots):
                                                nxt["status"] = "ready"
                                            elif any(next_slots):
                                                nxt["status"] = "bye"
                                            changed = True
                                            break
                        elif match.get("status") == "bye" and not slots_now:
                            match["status"] = "waiting"
        started_at = datetime.now(timezone.utc).isoformat()
        transition = await self.bot.db.tournaments.update_one(
            {"_id": oid, "status": {"$in": ["registration_open", "open"]}},
            {"$set": {"status": "live", "started_at": started_at, "bracket": bracket, "started_by": str(user.user_id), "updated_at": started_at}},
        )
        if not transition.modified_count:
            raise web.HTTPConflict(text="Tournament start was already completed by another staff action.")
        return web.json_response({"ok": True, "message": "Tournament started.", "bracket": bracket})

    async def asset_icon(self, request):
        filename = request.match_info["filename"]
        if "/" in filename or not filename.endswith(".svg"):
            raise web.HTTPNotFound()
        path = WEB_DIR / "assets" / "icons" / filename
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    async def asset(self, request: web.Request) -> web.Response:
        """Serve dashboard artwork with the correct image MIME type."""
        filename = request.match_info.get("filename", "")
        if not filename or "/" in filename or "\\" in filename:
            raise web.HTTPNotFound(text="Asset not found.")
        path = WEB_DIR / "assets" / filename
        if not path.is_file() or path.suffix.lower() not in {".svg", ".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            raise web.HTTPNotFound(text="Asset not found.")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if not content_type.startswith("image/"):
            raise web.HTTPNotFound(text="Asset not found.")
        return web.FileResponse(
            path,
            headers={
                "Content-Type": content_type,
                "Cache-Control": "no-store, max-age=0",
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def require_user(self, request: web.Request) -> Any:
        if not self.auth.configured:
            raise web.HTTPServiceUnavailable(text="Web authentication is not configured. Set DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET.")
        user = await self.auth.get_session(request)
        if user is None:
            raise web.HTTPFound("/login")
        return user

    async def require_guild_member(self, request: web.Request) -> tuple[Any, str, Any]:
        user = await self.require_user(request)
        guild_id = request.query.get("guild_id", "").strip()
        if not guild_id:
            raise web.HTTPBadRequest(text="guild_id is required.")
        if guild_id not in user.guild_ids:
            raise web.HTTPForbidden(text="You are not a member of this Discord server.")
        guild = next((g for g in getattr(self.bot, "guilds", []) if str(getattr(g, "id", "")) == guild_id), None)
        if guild is None:
            raise web.HTTPNotFound(text="The bot is not connected to this Discord server.")
        return user, guild_id, guild

    async def require_admin(self, request: web.Request) -> tuple[Any, str, Any]:
        user, guild_id, guild = await self.require_guild_member(request)

        # Re-check permissions against the live Discord member instead of
        # trusting a cached OAuth session for up to 30 days. This prevents a
        # removed admin role/permission from retaining web staff access.
        if user.user_id in self.auth.allowed_staff_ids:
            return user, guild_id, guild

        member = guild.get_member(int(user.user_id))
        if member is None:
            try:
                member = await guild.fetch_member(int(user.user_id))
            except Exception:
                member = None

        live_admin = bool(
            member
            and (
                member.guild_permissions.administrator
                or member.guild_permissions.manage_guild
            )
        )
        if not live_admin and member is not None:
            settings = await self.bot.db.settings.find_one({"_id": guild_id}) or {}
            admin_role_id = str(settings.get("admin_role_id", "")).strip()
            live_admin = bool(
                admin_role_id
                and any(str(role.id) == admin_role_id for role in getattr(member, "roles", []))
            )

        if not live_admin:
            raise web.HTTPForbidden(text="Administrator access is required for this server.")
        return user, guild_id, guild

    async def require_staff(self, request: web.Request) -> Any:
        user = await self.require_user(request)
        if not user.staff:
            raise web.HTTPForbidden(text="Staff access is required.")
        return user

    async def index(self, request: web.Request) -> web.StreamResponse:
        # The homepage is the most important production route. If a stale or
        # malformed web session ever causes an unexpected authentication error,
        # recover to the login page instead of exposing aiohttp's generic 500.
        try:
            await self.require_user(request)
        except web.HTTPException:
            raise
        except Exception:
            log.exception("Unexpected web authentication failure on /")
            response = web.HTTPFound("/login")
            response.del_cookie(SESSION_COOKIE, path="/")
            return response
        try:
            return await self._page_response("index.html", request)
        except Exception:
            log.exception("Unable to serve the web dashboard")
            raise web.HTTPServiceUnavailable(text="The Racing Syndicate League web dashboard is temporarily unavailable.")

    async def players_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_admin(request)
        return await self._page_response("players.html", request)
    async def setup_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_admin(request)
        return await self._page_response("setup.html", request)

    async def news_admin_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_admin(request)
        return await self._page_response("news-admin.html", request)

    async def player_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("player.html", request)

    async def site_search(self, request: web.Request) -> web.Response:
        await self.require_user(request)
        query = request.query.get("q", "").strip()
        if len(query) < 2:
            return web.json_response({"results": []})
        terms = [x.lower() for x in re.findall(r"[\w]+", query) if len(x) > 1][:8]
        pages = [
            ("Home", "/", "index.html"), ("Help Center", "/help", "help.html"),
            ("Player", "/player", "player.html"), ("Calendar", "/calendar", "calendar.html"),
            ("Clubs", "/clubs", "clubs.html"), ("Tournaments", "/tournaments", "tournaments.html"),
            ("Tournament Registration", "/tournaments/registration", "tournament-registration.html"),
            ("Tournament Matches", "/tournaments/matches", "tournament-matches.html"),
            ("Tournament Results", "/tournaments/results", "tournament-results.html"),
            ("Club Tournaments", "/tournaments/clubs", "tournament-clubs.html"),
            ("Gauntlet Registration", "/gauntlet/registration", "gauntlet-registration.html"),
            ("Gauntlet Defense", "/gauntlet/defense", "gauntlet-defense.html"),
            ("Gauntlet Challenges & Matches", "/gauntlet/matches", "gauntlet-matches.html"),
            ("Gauntlet Leaderboards", "/gauntlet/leaderboard", "gauntlet-leaderboard.html"),
            ("Gauntlet References", "/gauntlet/references", "gauntlet-references.html"),
            ("My Gauntlet Career", "/gauntlet/career", "gauntlet-career.html"),
        ]
        results = []
        for title, path, filename in pages:
            try:
                raw = (WEB_DIR / filename).read_text(encoding="utf-8")
            except OSError:
                continue
            text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
            text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", text))
            text = re.sub(r"\\s+", " ", text).strip()
            haystack = (title + " " + text).lower()
            if all(term in haystack for term in terms):
                pos = min((haystack.find(term) for term in terms if haystack.find(term) >= 0), default=0)
                start = max(0, pos - 90)
                snippet = text[start:start + 220]
                if start > 0:
                    snippet = "…" + snippet
                if start + 220 < len(text):
                    snippet += "…"
                results.append({"title": title, "url": path, "snippet": snippet})
        return web.json_response({"query": query, "results": results[:12]})

    async def discord_stats(self, request: web.Request) -> web.Response:
        """Return public Discord server counts for the homepage community banner."""
        await self.require_user(request)
        guilds = list(getattr(self.bot, "guilds", []) or [])
        if not guilds:
            return web.json_response({"online_members": 0, "server_members": 0, "available": False})
        # Prefer the largest connected guild, which is normally the main RSL community.
        guild = max(guilds, key=lambda g: int(getattr(g, "member_count", 0) or 0))
        members = list(getattr(guild, "members", []) or [])
        online = 0
        for member in members:
            try:
                if getattr(member, "bot", False):
                    continue
                status = getattr(member, "status", None)
                if str(status) not in {"offline", "invisible"}:
                    online += 1
            except Exception:
                continue
        total = int(getattr(guild, "member_count", 0) or len(members))
        return web.json_response({
            "online_members": online,
            "server_members": total,
            "server_name": str(getattr(guild, "name", "") or ""),
            "available": True,
        })

    async def healthz(self, request: web.Request) -> web.Response:
        ready = bool(getattr(self.bot, "is_ready", lambda: False)())
        db = getattr(self.bot, "db", None)
        db_ok = False
        if db is not None:
            try:
                await db.command("ping")
                db_ok = True
            except Exception:
                db_ok = False
        page_files = {
            name: (WEB_DIR / name).is_file()
            for name in ("index.html", "player.html", "players.html", "setup.html", "app.css", "app.js")
        }
        web_files_ok = all(page_files.values())
        return web.json_response({
            "ok": ready and db_ok and web_files_ok,
            "bot_ready": ready,
            "db_ok": db_ok,
            "web_files_ok": web_files_ok,
            "web_files": page_files,
        })

    async def login(self, request: web.Request) -> web.StreamResponse:
        if not self.auth.configured:
            return web.Response(status=503, text="Web authentication is not configured.", content_type="text/plain")
        user = await self.auth.get_session(request)
        if user:
            raise web.HTTPFound("/")
        state = await self.auth.create_state()
        return web.Response(
            text=f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sign In • Racing Syndicate League</title><link rel="stylesheet" href="/static/app.css?v=20260918-2"></head><body class="alu-dashboard"><main style="min-height:100vh;display:grid;place-items:center;padding:32px"><section class="glass-panel" style="max-width:620px;width:100%;padding:42px;text-align:center"><div class="bottom-logo">RACING <b>SYNDICATE</b> <strong>LEAGUE</strong></div><h1>Sign In to Racing Syndicate League</h1><p class="server-sub">Use your Discord account to access your player profile, registration, matches and staff controls. Your secure web session will be remembered for up to 30 days and refreshed while you use the site.</p><a class="qa qa-purple" href="{self.auth.login_url(state)}">Continue with Discord →</a></section></main></body></html>""",
            content_type="text/html",
        )

    async def callback(self, request: web.Request) -> web.StreamResponse:
        if not self.auth.configured:
            raise web.HTTPServiceUnavailable(text="Web authentication is not configured.")
        state = request.query.get("state", "")
        code = request.query.get("code", "")
        if not state or not await self.auth.consume_state(state):
            raise web.HTTPBadRequest(text="Invalid or expired OAuth state.")
        if not code:
            raise web.HTTPUnauthorized(text=request.query.get("error", "Authorization was cancelled."))
        stage = "token exchange"
        try:
            tokens = await self.auth.exchange_code(code)
            if not isinstance(tokens, dict):
                raise web.HTTPServiceUnavailable(text="Discord returned an invalid OAuth token response.")
            access_token = tokens.get("access_token")
            if not access_token:
                raise web.HTTPServiceUnavailable(text="Discord did not return an access token.")
            stage = "Discord account lookup"
            user = await self.auth.build_user(access_token)
            stage = "web session creation"
            session = await self.auth.create_session(user)
        except web.HTTPException:
            raise
        except Exception as exc:
            log.exception("Discord OAuth callback failed during %s", stage)
            return web.Response(
                status=503,
                text=f"Discord sign-in failed during {stage}. {type(exc).__name__}: {exc}",
                content_type="text/plain",
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )
        response = web.HTTPFound("/")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        self.auth.set_session_cookie(response, session)
        return response

    async def logout(self, request: web.Request) -> web.StreamResponse:
        try:
            await self.auth.destroy_session(request)
        except Exception:
            log.exception("Unable to remove web session during logout")
        response = web.HTTPFound("/login")
        response.del_cookie(SESSION_COOKIE, path="/")
        return response

    async def me(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        admin = bool(user.user_id in self.auth.allowed_staff_ids)
        if not admin:
            for gid in [str(x) for x in getattr(user, "guild_ids", [])]:
                guild = next((g for g in getattr(self.bot, "guilds", []) if str(getattr(g, "id", "")) == gid), None)
                if guild is None:
                    continue
                member = guild.get_member(int(user.user_id))
                if member and (member.guild_permissions.administrator or member.guild_permissions.manage_guild):
                    admin = True
                    break
                if member:
                    settings = await self.bot.db.settings.find_one({"_id": gid}) or {}
                    role_id = str(settings.get("admin_role_id", "")).strip()
                    if role_id and any(str(role.id) == role_id for role in getattr(member, "roles", [])):
                        admin = True
                        break
        return web.json_response({"id": user.user_id, "username": user.username, "global_name": user.global_name, "avatar": user.avatar, "staff": user.staff, "admin": admin})


    async def get_language(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        record = await self.bot.db.web_user_preferences.find_one({"_id": str(user.user_id)}) or {}
        language = str(record.get("language", "en")).strip() or "en"
        return web.json_response({"language": language})

    async def set_language(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        try:
            payload = await request.json()
        except Exception as exc:
            raise web.HTTPBadRequest(text="Invalid language request.") from exc
        language = str(payload.get("language", "en")).strip()
        allowed = {"en", "zh-CN", "es", "ar", "pt", "ru", "fr", "de", "ms", "hi", "ja", "ko", "it", "tr", "nl", "pl", "th", "vi", "id", "uk"}
        if language not in allowed:
            raise web.HTTPBadRequest(text="Unsupported language.")
        await self.bot.db.web_user_preferences.update_one(
            {"_id": str(user.user_id)},
            {"$set": {"language": language, "updated_at": time.time()}},
            upsert=True,
        )
        return web.json_response({"ok": True, "language": language})

    async def news(self, request: web.Request) -> web.Response:
        """Return news scoped to the signed-in user; staff may manage drafts for one server."""
        requested_guild = request.query.get("guild_id", "").strip()
        include_drafts = False
        if requested_guild:
            user, guild_id, _ = await self.require_admin(request)
            guild_ids = {guild_id}
            include_drafts = True
        else:
            user = await self.require_user(request)
            guild_ids = {str(x) for x in user.guild_ids}
        query = {"guild_id": {"$in": list(guild_ids)}}
        if not include_drafts:
            query["published"] = True
        cursor = self.bot.db.news_posts.find(query).sort("updated_at", -1).limit(100 if include_drafts else 12)
        rows = []
        async for row in cursor:
            row["id"] = str(row.pop("_id"))
            rows.append({k: row.get(k) for k in ("id","guild_id","title","category","excerpt","body","author_name","published_at","updated_at")})
        return web.json_response({"news": rows})

    async def _news_rows(self, guild_id: str) -> list[dict[str, Any]]:
        rows = []
        async for row in self.bot.db.news_posts.find({"guild_id": guild_id}).sort("updated_at", -1).limit(100):
            row["id"] = str(row.pop("_id"))
            rows.append({k: row.get(k) for k in ("id","guild_id","title","category","excerpt","body","author_id","author_name","published","published_at","created_at","updated_at")})
        return rows

    async def create_news(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        payload = await request.json()
        title = str(payload.get("title","")).strip()[:120]
        body = str(payload.get("body","")).strip()[:10000]
        if not title or not body:
            raise web.HTTPBadRequest(text="Title and article body are required.")
        now = datetime.now(timezone.utc).isoformat()
        published = bool(payload.get("published", True))
        doc = {
            "guild_id": guild_id, "title": title,
            "category": str(payload.get("category","Announcement")).strip()[:40] or "Announcement",
            "excerpt": str(payload.get("excerpt","")).strip()[:300],
            "body": body, "author_id": str(user.user_id),
            "author_name": str(user.global_name or user.username or "Staff"),
            "published": published, "published_at": now if published else None,
            "created_at": now, "updated_at": now,
        }
        result = await self.bot.db.news_posts.insert_one(doc)
        doc["id"] = str(result.inserted_id)
        await self._audit(guild_id, str(user.user_id), f"News {'published' if published else 'drafted'}: {title}")
        return web.json_response({"ok": True, "news": doc}, status=201)

    async def update_news(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        from bson import ObjectId
        try: oid = ObjectId(str(request.match_info["news_id"]))
        except Exception: raise web.HTTPBadRequest(text="Invalid news article ID.")
        existing = await self.bot.db.news_posts.find_one({"_id": oid, "guild_id": guild_id})
        if not existing: raise web.HTTPNotFound(text="News article not found.")
        payload = await request.json()
        updates = {}
        for key, limit in (("title",120),("category",40),("excerpt",300),("body",10000)):
            if key in payload: updates[key] = str(payload.get(key,"")).strip()[:limit]
        if ("title" in updates and not updates["title"]) or ("body" in updates and not updates["body"]):
            raise web.HTTPBadRequest(text="Title and article body cannot be empty.")
        if "published" in payload:
            updates["published"] = bool(payload["published"])
            updates["published_at"] = (datetime.now(timezone.utc).isoformat() if updates["published"] and not existing.get("published_at") else existing.get("published_at") if updates["published"] else None)
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self.bot.db.news_posts.update_one({"_id": oid, "guild_id": guild_id}, {"$set": updates})
        await self._audit(guild_id, str(user.user_id), f"News updated: {existing.get('title', str(oid))}")
        row = await self.bot.db.news_posts.find_one({"_id": oid, "guild_id": guild_id})
        row["id"] = str(row.pop("_id"))
        return web.json_response({"ok": True, "news": row})

    async def delete_news(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        from bson import ObjectId
        try: oid = ObjectId(str(request.match_info["news_id"]))
        except Exception: raise web.HTTPBadRequest(text="Invalid news article ID.")
        row = await self.bot.db.news_posts.find_one({"_id": oid, "guild_id": guild_id})
        if not row: raise web.HTTPNotFound(text="News article not found.")
        await self.bot.db.news_posts.delete_one({"_id": oid, "guild_id": guild_id})
        await self._audit(guild_id, str(user.user_id), f"News deleted: {row.get('title', str(oid))}")
        return web.json_response({"ok": True})
    async def status(self, request: web.Request) -> web.Response:
        await self.require_user(request)
        ready = bool(getattr(self.bot, "is_ready", lambda: False)())
        guilds = list(getattr(self.bot, "guilds", []) or [])
        latency = getattr(self.bot, "latency", None)
        return web.json_response({"bot": {"online": ready, "latency_ms": round(latency * 1000, 1) if latency is not None else None, "guild_count": len(guilds)}})

    async def guilds(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        bot_guilds = {str(getattr(g, "id", "")): g for g in getattr(self.bot, "guilds", [])}
        allowed = set(user.guild_ids) & set(bot_guilds)
        result = [{"id": gid, "name": str(getattr(bot_guilds[gid], "name", gid)), "admin": gid in user.admin_guild_ids or user.user_id in self.auth.allowed_staff_ids} for gid in sorted(allowed)]
        result.sort(key=lambda item: item["name"].casefold())
        return web.json_response({"guilds": result})

    async def player_me(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        player = await self.players.get_player(guild_id, user.user_id)
        preferences = await self.bot.db.web_preferences.find_one({"_id": f"{guild_id}_{user.user_id}"}) or {}
        return web.json_response({
            "player": player,
            "user": {"id": user.user_id, "username": user.username, "global_name": user.global_name},
            "preferences": {key: preferences.get(key) for key in ("timezone", "web_notifications", "dm_notifications", "game_name", "about", "location", "platform", "driver_type", "links", "asphalt_connection")},
        })

    async def player_defense(self, request: web.Request) -> web.Response:
        """Return the player's current/pending five-course defense state."""
        user, guild_id, _ = await self.require_guild_member(request)
        profile = await self.players.get_player(guild_id, user.user_id) or {}
        locked = profile.get("defense_locked") or {}
        pending = profile.get("defense_review_payload") or {}
        tracks = profile.get("pending_tracks") or profile.get("season_defense_tracks") or []
        courses = locked.get("courses") or []
        return web.json_response({
            "locked": courses,
            "pending": pending.get("courses") or [],
            "pending_review": bool(profile.get("defense_review_pending")),
            "pending_is_change": bool(profile.get("pending_is_change") or pending.get("is_change")),
            "tracks": tracks,
            "cooldown_remaining": max(0, int(86400 - (time.time() - float(profile.get("last_defense_change", 0))))) if profile.get("last_defense_change") else 0,
        })

    async def player_defense_action(self, request: web.Request) -> web.Response:
        """Generate or stage a five-course defense using the same driver records as Discord."""
        user, guild_id, _ = await self.require_guild_member(request)
        try:
            payload = await request.json()
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        action = str(payload.get("action", "generate")).strip().casefold()
        driver_id = f"{guild_id}_{user.user_id}"
        profile = await self.bot.db.drivers.find_one({"_id": driver_id})
        if not profile:
            raise web.HTTPConflict(text="Register your driver for the current season before setting a defense.")
        if profile.get("defense_review_pending"):
            raise web.HTTPConflict(text="Your defense submission is already pending staff review.")
        if action == "submit":
            courses_in = payload.get("courses")
            if not isinstance(courses_in, list) or len(courses_in) != 5:
                raise web.HTTPBadRequest(text="Exactly five defense course results are required.")
            pending_tracks = profile.get("pending_tracks") or profile.get("season_defense_tracks") or []
            if len(pending_tracks) != 5:
                raise web.HTTPConflict(text="Generate your five defense courses first.")
            if bool(payload.get("is_change")) != bool(profile.get("pending_is_change")):
                raise web.HTTPBadRequest(text="Defense submission state is out of date. Refresh and try again.")
            from ..core.core import parse_lap_time
            parsed, seen = [], set()
            for i, item in enumerate(courses_in):
                if not isinstance(item, dict):
                    raise web.HTTPBadRequest(text=f"Course {i + 1} is invalid.")
                car = str(item.get("car", "")).strip()
                lap_time = str(item.get("lap_time", "")).strip()
                proof_url = str(item.get("proof_url", "")).strip()
                try:
                    car_rank = int(item.get("car_rank"))
                except (TypeError, ValueError):
                    raise web.HTTPBadRequest(text=f"Course {i + 1}: car performance must be a whole number.")
                ms = parse_lap_time(lap_time)
                if ms <= 0:
                    raise web.HTTPBadRequest(text=f"Course {i + 1}: lap time must use MM:SS.MS format.")
                if not car or car.casefold() in seen:
                    raise web.HTTPBadRequest(text="All five cars are required and must be different.")
                if car_rank <= 0:
                    raise web.HTTPBadRequest(text=f"Course {i + 1}: car performance must be positive.")
                if not proof_url.lower().startswith(("http://", "https://")):
                    raise web.HTTPBadRequest(text=f"Course {i + 1}: proof must be a valid image URL.")
                seen.add(car.casefold())
                parsed.append({"track": str(pending_tracks[i]), "car": car, "car_rank": car_rank, "lap_time": lap_time, "ms": ms, "proof_url": proof_url})
            cfg = await self.bot.db.settings.find_one({"_id": guild_id}) or {}
            channel_id = cfg.get("review_channel_id")
            channel = self.bot.get_channel(int(channel_id)) if channel_id else None
            if channel is None:
                raise web.HTTPServiceUnavailable(text="Staff review channel is not configured.")
            submitted_at = time.time()
            submission_id = hashlib.sha256(f"{guild_id}:{user.user_id}:{submitted_at}".encode()).hexdigest()[:24]
            is_change = bool(profile.get("pending_is_change"))
            payload_doc = {"courses": parsed, "proof_url": parsed[0]["proof_url"], "is_change": is_change, "submitted_at": submitted_at, "submission_id": submission_id}
            claim = await self.bot.db.drivers.update_one({"_id": driver_id, "defense_review_pending": {"$ne": True}}, {"$set": {"defense_review_pending": True, "defense_review_payload": payload_doc}})
            if getattr(claim, "modified_count", 0) != 1:
                raise web.HTTPConflict(text="Your defense submission is already pending staff review.")
            embeds = [discord.Embed(title="🛡️ Gauntlet Defense Change Request" if is_change else "🛡️ New Gauntlet Defense Placement Verification", description="A web submission is awaiting staff verification.", color=3447003)]
            embeds[0].add_field(name="Driver", value=f"<@{user.user_id}>", inline=False)
            embeds[0].set_footer(text=f"ALU Defense Submission: {submission_id}")
            for i, course in enumerate(parsed, 1):
                emb = discord.Embed(title=f"🏁 Course {i}: {course['track']}", description=f"🚗 **Car:** {course['car']}\n📈 **Car Performance:** {course['car_rank']}\n⏱️ **Lap Time:** {course['lap_time']}", color=3447003)
                emb.set_image(url=course["proof_url"])
                embeds.append(emb)
            try:
                from ..cogs.defense import DefenseView
                review_view = DefenseView(
                    str(user.user_id),
                    str(guild_id),
                    parsed,
                    parsed[0]["proof_url"],
                    is_change=is_change,
                )
                message = await channel.send(embeds=embeds, view=review_view)
            except Exception:
                await self.bot.db.drivers.update_one({"_id": driver_id, "defense_review_payload.submission_id": submission_id}, {"$unset": {"defense_review_pending": "", "defense_review_payload": ""}})
                raise web.HTTPServiceUnavailable(text="Staff review message could not be delivered; your submission was rolled back.")
            await self.bot.db.drivers.update_one({"_id": driver_id, "defense_review_payload.submission_id": submission_id}, {"$set": {"defense_review_payload.review_channel_id": int(channel.id), "defense_review_payload.review_message_id": int(message.id), "defense_review_payload.delivery_status": "delivered"}})
            return web.json_response({"ok": True, "message": "Defense submitted for staff review.", "submission_id": submission_id})

        existing = profile.get("defense_locked") or {}
        if action == "change":
            if not has_5_course_defense(profile):
                raise web.HTTPConflict(text="You do not have a valid five-course defense yet. Create your first defense instead.")
            last_change = profile.get("last_defense_change")
            if last_change and time.time() - float(last_change) < 86400:
                remaining = int(86400 - (time.time() - float(last_change)))
                raise web.HTTPConflict(text=f"Defense changes are on cooldown for another {remaining // 3600}h {(remaining % 3600) // 60}m.")
            tracks = [c.get("track") for c in existing.get("courses", []) if c.get("track")]
            if len(tracks) != 5:
                tracks = profile.get("season_defense_tracks") or []
        else:
            tracks = profile.get("season_defense_tracks") or []
        if len(tracks) != 5:
            tracks = random.sample(ALU_TRACKS, 5)
        await self.bot.db.drivers.update_one(
            {"_id": driver_id},
            {"$set": {"season_defense_tracks": tracks, "pending_tracks": tracks, "pending_is_change": action == "change"}}
        )
        return web.json_response({"ok": True, "action": action, "tracks": tracks, "message": "Five defense courses generated. Enter your results and proof, then submit for staff review."})

    async def player_register(self, request: web.Request) -> web.Response:
        """Submit a web registration through the same canonical Discord workflow."""
        user, guild_id, guild = await self.require_guild_member(request)
        try:
            payload = await request.json()
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        game_id = str(payload.get("game_id", "")).strip()
        proof_url = str(payload.get("proof_url", "")).strip()
        control_raw = str(payload.get("control", "")).strip().casefold()
        if not game_id or len(game_id) > 100:
            raise web.HTTPBadRequest(text="Game ID is required and must be 100 characters or fewer.")
        try:
            garage_pi = int(payload.get("garage_pi"))
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="Garage PI must be a positive whole number.")
        if garage_pi <= 0:
            raise web.HTTPBadRequest(text="Garage PI must be a positive whole number.")
        if not proof_url.lower().startswith(("http://", "https://")):
            raise web.HTTPBadRequest(text="Proof must be a direct image URL beginning with http:// or https://.")
        if "touch" in control_raw:
            control_value, control_name = "touchdrive", "TouchDrive Auto Pilot"
        elif "manual" in control_raw or "tilt" in control_raw or "tap" in control_raw:
            control_value, control_name = "manual", "Manual Tilt / Tap Controls"
        else:
            raise web.HTTPBadRequest(text="Controls must be TouchDrive or Manual.")

        cfg = await self.bot.db.settings.find_one({"_id": guild_id}) or {}
        registration_channel_id = cfg.get("registration_channel_id")
        if not registration_channel_id:
            raise web.HTTPServiceUnavailable(text="Registration is not configured for this server.")

        class _WebUser:
            def __init__(self, user):
                self.id = int(user.user_id)
                self.mention = f"<@{self.id}>"

        class _WebResponse:
            def __init__(self, owner):
                self.owner = owner
                self.done = False
            def is_done(self):
                return self.done
            async def send_message(self, content=None, **kwargs):
                self.done = True
                self.owner.message = str(content or "")

        class _WebFollowup:
            def __init__(self, owner):
                self.owner = owner
            async def send(self, content=None, **kwargs):
                self.owner.message = str(content or "")

        class _WebInteraction:
            def __init__(self):
                self.guild_id = int(guild_id)
                self.channel_id = int(registration_channel_id)
                self.user = _WebUser(user)
                self.message = ""
                self.response = _WebResponse(self)
                self.followup = _WebFollowup(self)

        class _ControlType:
            name = control_name
            value = control_value

        class _Proof:
            content_type = "image/*"
            url = proof_url

        interaction = _WebInteraction()
        await submit_registration_application(interaction, game_id, garage_pi, _Proof(), _ControlType())
        if interaction.message.startswith(("❌", "⚠️", "⏳")):
            if interaction.message.startswith("⏳"):
                raise web.HTTPConflict(text=interaction.message)
            if interaction.message.startswith("⚠️"):
                raise web.HTTPConflict(text=interaction.message)
            raise web.HTTPBadRequest(text=interaction.message)
        return web.json_response({"ok": True, "message": interaction.message})

    async def player_profile(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        try:
            payload = await request.json()
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        game_name = str(payload.get("game_name", "")).strip()[:100]
        about = str(payload.get("about", "")).strip()[:500]
        location = str(payload.get("location", "")).strip()[:100]
        platform = str(payload.get("platform", "")).strip()[:40]
        driver_type = str(payload.get("driver_type", "")).strip()[:30]
        allowed_platforms = {"Android", "Nintendo", "macOS", "Steam", "Epic Games", "Windows", "Apple iOS", "Xbox", "Playstation"}
        allowed_driver_types = {"Manual Driver", "Touch Driver"}
        if platform and platform not in allowed_platforms:
            raise web.HTTPBadRequest(text="Invalid platform.")
        if driver_type and driver_type not in allowed_driver_types:
            raise web.HTTPBadRequest(text="Invalid driver type.")
        timezone = str(payload.get("timezone", "UTC")).strip()
        if timezone not in {value for _, value in TIMEZONE_LABELS}:
            raise web.HTTPBadRequest(text="Invalid timezone.")
        links = payload.get("links", [])
        if not isinstance(links, list):
            raise web.HTTPBadRequest(text="Links must be a list.")
        clean_links = []
        for link in links[:5]:
            value = str(link or "").strip()
            if not value:
                continue
            if not value.lower().startswith(("http://", "https://")):
                raise web.HTTPBadRequest(text="Profile links must begin with http:// or https://.")
            if len(value) > 300:
                raise web.HTTPBadRequest(text="Profile links must be 300 characters or fewer.")
            clean_links.append(value)
        preference_id = f"{guild_id}_{user.user_id}"
        await self.bot.db.web_preferences.update_one(
            {"_id": preference_id},
            {"$set": {"guild_id": guild_id, "user_id": user.user_id, "game_name": game_name, "about": about, "location": location, "platform": platform, "driver_type": driver_type, "timezone": timezone, "links": clean_links}},
            upsert=True,
        )
        await self.bot.db.drivers.update_one(
            {"_id": preference_id},
            {"$set": {"game_name": game_name, "updated_at": time.time()}},
        )
        return web.json_response({"ok": True, "message": "Profile updated.", "profile": {"discord_name": user.global_name or user.username or "Driver", "game_name": game_name, "game_id": (await self.players.get_player(guild_id, user.user_id) or {}).get("game_id", ""), "about": about, "location": location, "timezone": timezone, "links": clean_links}})

    async def player_asphalt(self, request: web.Request) -> web.Response:
        """Link a player's Asphalt Legends identity to their Discord/web account."""
        user, guild_id, _ = await self.require_guild_member(request)
        try:
            payload = await request.json()
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        game_id = str(payload.get("game_id", "")).strip()[:100]
        game_name = str(payload.get("game_name", "")).strip()[:100]
        if not game_id or not game_name:
            raise web.HTTPBadRequest(text="Asphalt Game Name and Game ID are required.")
        existing = await self.bot.db.web_preferences.find_one({"_id": f"{guild_id}_{user.user_id}"}) or {}
        connection = existing.get("asphalt_connection") or {}
        if connection.get("status") == "verified" and connection.get("game_id") != game_id:
            raise web.HTTPConflict(text="Your Asphalt account is already verified. Ask staff to change the linked account.")
        duplicate = await self.bot.db.web_preferences.find_one({"guild_id": guild_id, "asphalt_connection.game_id": game_id, "_id": {"$ne": f"{guild_id}_{user.user_id}"}})
        if duplicate and (duplicate.get("asphalt_connection") or {}).get("status") == "verified":
            raise web.HTTPConflict(text="That Asphalt Game ID is already linked to another Discord account.")
        now = datetime.now(timezone.utc).isoformat()
        connection = {"game_id": game_id, "game_name": game_name, "status": "pending", "submitted_at": connection.get("submitted_at") or now, "updated_at": now, "verified_at": connection.get("verified_at"), "verified_by": connection.get("verified_by")}
        key = f"{guild_id}_{user.user_id}"
        previous_prefs = existing
        try:
            await self.bot.db.web_preferences.update_one({"_id": key}, {"$set": {"guild_id": guild_id, "user_id": user.user_id, "asphalt_connection": connection}}, upsert=True)
            await self.bot.db.drivers.update_one({"_id": key}, {"$set": {
                "guild_id": guild_id,
                "user_id": user.user_id,
                "asphalt_verified": False,
                "asphalt_game_id": None,
                "asphalt_game_name": None,
                "asphalt_verified_by": None,
                "asphalt_verified_at": None,
            }}, upsert=True)
        except Exception:
            try:
                if previous_prefs:
                    await self.bot.db.web_preferences.replace_one({"_id": key}, previous_prefs, upsert=True)
                else:
                    await self.bot.db.web_preferences.delete_one({"_id": key})
            except Exception:
                log.exception("Failed to compensate partial Asphalt submission for %s", key)
            raise
        cfg = await self.bot.db.settings.find_one({"_id": guild_id}) or {}
        channel = self.bot.get_channel(int(cfg["review_channel_id"])) if cfg.get("review_channel_id") else None
        if channel:
            await channel.send(f"🏎️ Asphalt Account Link Pending Verification\nDiscord: <@{user.user_id}>\nGame Name: **{game_name}**\nGame ID: **{game_id}**\n\nStaff can verify with /asphalt verify.")
        return web.json_response({"ok": True, "message": "Asphalt account submitted for staff verification.", "connection": connection})

    async def player_preferences(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        try:
            payload = await request.json()
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        allowed = {"web_notifications", "dm_notifications", "timezone"}
        updates = {key: payload[key] for key in allowed if key in payload}
        if "web_notifications" in updates:
            updates["web_notifications"] = bool(updates["web_notifications"])
        if "dm_notifications" in updates:
            updates["dm_notifications"] = bool(updates["dm_notifications"])
        if "timezone" in updates and updates["timezone"] not in {value for _, value in TIMEZONE_LABELS}:
            raise web.HTTPBadRequest(text="Invalid timezone.")
        if updates:
            await self.bot.db.web_preferences.update_one({"_id": f"{guild_id}_{user.user_id}"}, {"$set": {**updates, "guild_id": guild_id, "user_id": user.user_id}}, upsert=True)
        return web.json_response({"ok": True, "preferences": updates})

    async def setup_options(self, request: web.Request) -> web.Response:
        _, _, guild = await self.require_admin(request)
        channels = [{"id": str(c.id), "name": c.name, "type": str(getattr(c, "type", "text"))} for c in guild.text_channels]
        roles = [{"id": str(role.id), "name": role.name} for role in guild.roles if not role.is_default() and not role.managed]
        return web.json_response({"channels": channels, "roles": roles, "timezones": [{"label": label, "value": value} for label, value in TIMEZONE_LABELS]})

    async def setup_settings(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_admin(request)
        settings = await self.bot.db.settings.find_one({"_id": guild_id}) or {}
        return web.json_response({"settings": {key: settings.get(key) for key, _ in SETUP_CHANNELS + SETUP_ROLES} | {"timezone": settings.get("timezone", "UTC")}})

    async def save_setup_settings(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        try:
            payload = await request.json()
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        allowed = {key for key, _ in SETUP_CHANNELS + SETUP_ROLES} | {"timezone"}
        clean = {key: str(payload[key]).strip() for key in allowed if payload.get(key)}
        if clean.get("timezone") not in {None, *(value for _, value in TIMEZONE_LABELS)}:
            raise web.HTTPBadRequest(text="Invalid timezone.")
        if not clean:
            raise web.HTTPBadRequest(text="Nothing to save.")
        guild = next(g for g in self.bot.guilds if str(g.id) == guild_id)
        for key in SETUP_CHANNELS:
            value = clean.get(key[0])
            if value:
                try:
                    valid = guild.get_channel(int(value))
                except (TypeError, ValueError):
                    valid = None
                if valid is None:
                    raise web.HTTPBadRequest(text=f"Invalid channel for {key[1]}.")
        for key in SETUP_ROLES:
            value = clean.get(key[0])
            if value:
                try:
                    valid = guild.get_role(int(value))
                except (TypeError, ValueError):
                    valid = None
                if valid is None:
                    raise web.HTTPBadRequest(text=f"Invalid role for {key[1]}.")
        await self.bot.db.settings.update_one({"_id": guild_id}, {"$set": clean}, upsert=True)
        await self._audit(guild_id, user.user_id, "Web setup updated")
        return web.json_response({"ok": True, "settings": clean})

    async def season(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_guild_member(request)
        state = await self.bot.db.season_state.find_one({"_id": f"guild_{guild_id}"}) or {}
        return web.json_response({"season": state})

    async def save_season(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        try:
            payload = await request.json()
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        if "automatic_season_end" in payload:
            value = bool(payload["automatic_season_end"])
            await self.bot.db.settings.update_one({"_id": guild_id}, {"$set": {"automatic_season_end": value}}, upsert=True)
            await self._audit(guild_id, user.user_id, f"Web season automation {'enabled' if value else 'disabled'}")
        return web.json_response({"ok": True})

    async def _audit(self, guild_id: str, user_id: str, action: str) -> None:
        await self.bot.db.system_events.insert_one({"guild_id": guild_id, "source": "web", "user_id": user_id, "action": action})

    async def leaderboard(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_guild_member(request)
        try:
            limit = max(1, min(100, int(request.query.get("limit", "50"))))
        except ValueError:
            raise web.HTTPBadRequest(text="limit must be an integer.")
        rows = await self.players.list_players(guild_id, limit=limit)
        for player in rows:
            uid = str(player.get("user_id", ""))
            prefs = await self.bot.db.web_preferences.find_one({"_id": f"{guild_id}_{uid}"}) or {}
            connection = prefs.get("asphalt_connection") or {}
            player["game_name"] = prefs.get("game_name", "") or connection.get("game_name", "")
            player["asphalt_verified"] = connection.get("status") == "verified"
        return web.json_response({"players": rows})

    async def competition_snapshot(self, request: web.Request) -> web.Response:
        """Return the signed-in driver's live competitive snapshot for the selected guild."""
        user, guild_id, _ = await self.require_guild_member(request)
        player = await self.players.get_player(guild_id, str(user.user_id))
        if player is None:
            return web.json_response({"registered": False, "guild_id": guild_id})
        elo = int(player.get("elo", 1000) or 1000)
        season = await get_current_season_number(str(guild_id))
        player_season = int(player.get("season_number", 0) or 0)
        season_active = bool(player.get("season_registered")) and player_season == season
        if season_active:
            higher = await self.bot.db.drivers.count_documents({
                "guild_id": str(guild_id),
                "season_registered": True,
                "season_number": season,
                "elo": {"$gt": elo},
            })
            rank = higher + 1
        else:
            rank = None
        played = int(player.get("career_played", 0) or 0)
        wins = int(player.get("career_wins", 0) or 0)
        prefs = await self.bot.db.web_preferences.find_one({"_id": f"{guild_id}_{user.user_id}"}) or {}
        connection = prefs.get("asphalt_connection") or {}
        return web.json_response({"registered": season_active, "profile_exists": True, "rank": rank, "elo": elo, "garage_pi": int(player.get("garage_pi", 0) or 0), "career_wins": wins, "career_losses": max(0, played - wins), "streak": int(player.get("streak", 0) or 0), "defense_locked": bool(player.get("defense_locked", False)), "season_number": season, "player_season_number": player_season, "asphalt_verified": connection.get("status") == "verified"})

    async def competition_recent_matches(self, request: web.Request) -> web.Response:
        """Return the signed-in driver's recent verified Gauntlet match results."""
        user, guild_id, _ = await self.require_guild_member(request)
        cursor = self.bot.db.matches.find({
            "guild_id": str(guild_id),
            "reverted": {"$ne": True},
            "$or": [{"challenger_id": str(user.user_id)}, {"opponent_id": str(user.user_id)}],
        }).sort("timestamp", -1).limit(8)
        rows = []
        async for match in cursor:
            challenger_id = str(match.get("challenger_id", ""))
            opponent_id = str(match.get("opponent_id", ""))
            opponent = opponent_id if challenger_id == str(user.user_id) else challenger_id
            opponent_profile = await self.bot.db.drivers.find_one({"_id": f"{guild_id}_{opponent}"}) or {}
            opponent_name = str(opponent_profile.get("game_id") or opponent_profile.get("username") or opponent)
            won = str(match.get("w_id", "")) == str(user.user_id)
            lost = str(match.get("l_id", "")) == str(user.user_id)
            if not won and not lost:
                continue
            timestamp = match.get("timestamp")
            try:
                date_value = int(timestamp)
            except (TypeError, ValueError):
                try:
                    date_value = int(datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).timestamp())
                except Exception:
                    date_value = int(time.time())
            rows.append({
                "match_id": str(match.get("_id", "")),
                "opponent_id": opponent,
                "opponent": opponent_name,
                "result": "WIN" if won else "LOSS",
                "courses": int(match.get("courses_beat", 0) or 0),
                "date": date_value,
            })
        return web.json_response({"matches": rows})

    async def player_career(self, request: web.Request) -> web.Response:
        """Return the signed-in driver's tournament and Gauntlet career history."""
        user, guild_id, _ = await self.require_guild_member(request)
        uid = str(user.user_id)
        driver_id = f"{guild_id}_{uid}"
        driver = await self.bot.db.drivers.find_one({"_id": driver_id}) or {}
        season = await get_current_season_number(str(guild_id))
        elo = int(driver.get("elo", 1000) or 1000)

        higher = await self.bot.db.drivers.count_documents({
            "guild_id": str(guild_id), "elo": {"$gt": elo}
        })
        career_rank = higher + 1

        registrations = []
        async for reg in self.bot.db.tournament_registrations.find({
            "guild_id": str(guild_id), "user_id": uid
        }).sort("registered_at", -1):
            tid = str(reg.get("tournament_id", ""))
            try:
                from bson import ObjectId
                tournament = await self.bot.db.tournaments.find_one({"_id": ObjectId(tid)})
            except Exception:
                tournament = None
            if not tournament:
                continue
            bracket = tournament.get("bracket") or {}
            groups = bracket.get("rounds") or bracket.get("winners") or []
            wins = losses = played = 0
            placement = None
            for group in groups:
                for match in group.get("matches", []):
                    slots = [str(x) for x in (match.get("player_slots") or []) if x]
                    if uid not in slots:
                        continue
                    status = str(match.get("status", ""))
                    winner = str(match.get("winner_id", ""))
                    if status == "completed" and winner:
                        played += 1
                        if winner == uid:
                            wins += 1
                        else:
                            losses += 1
            if str(tournament.get("status")) == "completed" and losses and not wins:
                placement = "Eliminated"
            registrations.append({
                "id": tid,
                "name": str(tournament.get("name", "Tournament")),
                "format": str(tournament.get("format", "tournament")).replace("_", " ").title(),
                "status": str(tournament.get("status", "unknown")).replace("_", " ").title(),
                "registered_at": str(reg.get("registered_at", "")),
                "played": played, "wins": wins, "losses": losses,
                "record": f"{wins}-{losses}", "placement": placement or ("Active" if str(tournament.get("status")) != "completed" else "Completed"),
                "start_time": str(tournament.get("start_time", "")),
            })

        gauntlet = {
            "season": season,
            "registered": bool(driver.get("season_registered")) and int(driver.get("season_number", 0) or 0) == season,
            "rank": career_rank,
            "elo": elo,
            "wins": int(driver.get("career_wins", 0) or 0),
            "played": int(driver.get("career_played", 0) or 0),
            "streak": int(driver.get("streak", 0) or 0),
        }
        gauntlet["losses"] = max(0, gauntlet["played"] - gauntlet["wins"])
        return web.json_response({
            "player": {"username": str(driver.get("username") or user.global_name or user.username or "Driver")},
            "career": gauntlet,
            "tournaments": registrations[:25],
        })

    async def player_list(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_admin(request)
        try:
            limit = max(1, min(100, int(request.query.get("limit", "50"))))
        except ValueError:
            raise web.HTTPBadRequest(text="limit must be an integer.")
        players = await self.players.list_players(guild_id, search=request.query.get("search", ""), limit=limit)
        for player in players:
            uid = str(player.get("user_id", ""))
            prefs = await self.bot.db.web_preferences.find_one({"_id": f"{guild_id}_{uid}"}) or {}
            connection = prefs.get("asphalt_connection") or {}
            player["asphalt_connection"] = {
                "game_id": connection.get("game_id", ""),
                "game_name": connection.get("game_name", ""),
                "status": connection.get("status", "not_linked"),
            }
            player["asphalt_verified"] = connection.get("status") == "verified"
        return web.json_response({"players": players})

    async def player_detail(self, request: web.Request) -> web.Response:
        """Return a guild member's public profile for the player directory."""
        _, guild_id, _ = await self.require_guild_member(request)
        user_id = str(request.match_info["user_id"]).strip()
        player = await self.players.get_player(guild_id, user_id)
        if player is None:
            raise web.HTTPNotFound(text="Player not found.")
        prefs = await self.bot.db.web_preferences.find_one({"_id": f"{guild_id}_{user_id}"}) or {}
        connection = prefs.get("asphalt_connection") or {}
        player["asphalt_connection"] = {
            "game_id": connection.get("game_id", ""),
            "game_name": connection.get("game_name", ""),
            "status": connection.get("status", "not_linked"),
        }
        player["asphalt_verified"] = connection.get("status") == "verified"
        return web.json_response({"player": player})

    async def help_page(self, request: web.Request) -> web.Response:
        """Render the public Help Center page."""
        return await self._page_response("help.html", request)
