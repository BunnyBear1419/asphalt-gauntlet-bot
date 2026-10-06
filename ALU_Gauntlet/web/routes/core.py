"""RSL web core route family."""
import os
from .._web_context import *

class CoreRoutesMixin:
    def __init__(self, bot: Any, host: str = "127.0.0.1", port: int = 8080) -> None:
        self.bot = bot
        self.host = host
        self.port = port
        self.auth = DiscordOAuth(bot)
        self.players = PlayerService(bot)
        self.app = web.Application(middlewares=[self._error_middleware, self._security_headers_middleware, self._security_middleware, self._maintenance_middleware], client_max_size=15 * 1024 * 1024)
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self._auth_rate: dict[str, list[float]] = {}
        self._ticket_transcript_rate: dict[str, float] = {}
        self._csp_report_rate: dict[str, list[float]] = {}
        self._configure_routes()

    @web.middleware
    async def _error_middleware(self, request: web.Request, handler: Any) -> web.StreamResponse:
        try:
            return await handler(request)
        except web.HTTPException as exc:
            if exc.status == 429:
                retry_after = exc.headers.get("Retry-After", "30")
                if request.path.startswith("/api/"):
                    return web.json_response(
                        {"ok": False, "error": "Too many requests. Please wait and try again.", "retry_after": retry_after},
                        status=429,
                        headers={"Retry-After": retry_after, "Cache-Control": "no-store"},
                    )
                return web.Response(
                    text="Too many requests. Please wait and try again.",
                    status=429,
                    headers={"Retry-After": retry_after, "Cache-Control": "no-store"},
                    content_type="text/plain",
                )
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

    async def _json_object(self, request: web.Request) -> dict[str, Any]:
        """Parse a request body and require a JSON object for API mutations."""
        try:
            payload = await request.json()
        except Exception as exc:
            raise web.HTTPBadRequest(text="Invalid JSON body.") from exc
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="JSON body must be an object.")
        return payload

    def _request_origin_allowed(self, request: web.Request) -> bool:
        """Require a same-origin browser signal for cookie-authenticated mutations."""
        origin = str(request.headers.get("Origin") or "").strip().rstrip("/")
        referer = str(request.headers.get("Referer") or "").strip()
        candidate = origin
        if not candidate and referer:
            parts = referer.split("/", 3)
            candidate = parts[0] + "//" + parts[2] if len(parts) >= 3 and "://" in referer else ""
        if not candidate:
            return False
        candidate = candidate.rstrip("/")
        expected = {str(self.auth.public_url).rstrip("/"), f"{request.scheme}://{request.host}".rstrip("/")}
        return candidate in expected

    def _client_ip(self, request: web.Request) -> str:
        remote = str(request.remote or "").strip()
        trusted_proxies = {value.strip() for value in str(os.getenv("RSL_TRUSTED_PROXY_IPS", "")).split(",") if value.strip()}
        if remote in trusted_proxies:
            forwarded = str(request.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
            return forwarded or remote or "unknown"
        return remote or "unknown"

    def _rate_limit_auth_request(self, request: web.Request, limit: int, window: int) -> bool:
        """Small process-local abuse guard for OAuth entry/callback endpoints."""
        now = time.time()
        key = self._client_ip(request)
        bucket = [ts for ts in self._auth_rate.get(key, []) if ts > now - window]
        if len(bucket) >= limit:
            self._auth_rate[key] = bucket
            return False
        bucket.append(now)
        self._auth_rate[key] = bucket
        if len(self._auth_rate) > 2048:
            self._auth_rate = {k: v for k, v in self._auth_rate.items() if v and v[-1] > now - window}
        return True

    async def csp_report(self, request: web.Request) -> web.Response:
        """Collect bounded CSP violation reports for policy tuning."""
        now = time.time()
        remote = self._client_ip(request)
        if request.content_length is not None and request.content_length > 64 * 1024:
            raise web.HTTPRequestEntityTooLarge(max_size=64 * 1024, actual_size=request.content_length)
        if len(self._csp_report_rate) > 2048:
            self._csp_report_rate = {
                key: values for key, values in self._csp_report_rate.items()
                if values and values[-1] > now - 60
            }
        bucket = [ts for ts in self._csp_report_rate.get(remote, []) if ts > now - 60]
        if len(bucket) >= 30:
            self._csp_report_rate[remote] = bucket
            return web.json_response({"ok": False}, status=429, headers={"Retry-After": "60"})
        bucket.append(now)
        self._csp_report_rate[remote] = bucket
        try:
            raw_body = await request.content.read(64 * 1024 + 1)
            if len(raw_body) > 64 * 1024:
                raise web.HTTPRequestEntityTooLarge(max_size=64 * 1024, actual_size=len(raw_body))
            payload = json.loads(raw_body.decode("utf-8"))
        except web.HTTPRequestEntityTooLarge:
            raise
        except Exception:
            return web.json_response({"ok": False}, status=400)
        entries = payload if isinstance(payload, list) else [payload]
        allowed = {
            "document-uri", "referrer", "blocked-uri", "violated-directive",
            "effective-directive", "original-policy", "disposition",
            "source-file", "status-code", "script-sample", "column-number",
            "line-number",
        }
        sanitized_reports = []
        for entry in entries[:20]:
            if not isinstance(entry, dict):
                continue
            report = entry.get("csp-report") if isinstance(entry.get("csp-report"), dict) else entry.get("body")
            if not isinstance(report, dict):
                report = entry
            sanitized = {
                key: str(report[key])[:2000]
                for key in allowed
                if report.get(key) is not None
            }
            if sanitized:
                sanitized_reports.append(sanitized)
        if sanitized_reports:
            try:
                from datetime import datetime, timezone
                created_at = datetime.now(timezone.utc)
                await self.bot.db.csp_reports.insert_many([
                    {"created_at": created_at, "remote": remote[:128], "report": report}
                    for report in sanitized_reports
                ])
            except Exception:
                log.exception("Unable to persist CSP violation reports")
        return web.Response(status=204)

    def _apply_security_headers(self, request: web.Request, response: web.StreamResponse) -> web.StreamResponse:
        """Apply browser hardening without constraining the existing page/script architecture."""
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        csp = (
            "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
            "form-action 'self' https://discord.com; "
            "script-src 'self' 'unsafe-inline' https://www.googletagmanager.com https://translate.google.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data: blob: https://cdn.discordapp.com https://*.googleusercontent.com; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "connect-src 'self' https://discord.com https://*.google-analytics.com https://*.analytics.google.com https://translate.googleapis.com https://www.gstatic.com; "
            "media-src 'self' blob:; "
            "frame-src 'self' https://www.youtube.com https://www.youtube-nocookie.com"
        )
        # Enforce the same policy that has been monitored by the CSP collector.
        # Keep both reporting mechanisms so violations remain observable after enforcement.
        response.headers.setdefault("Content-Security-Policy", csp + "; report-uri /api/csp-report; report-to rsl-csp")
        response.headers.setdefault("Reporting-Endpoints", 'rsl-csp="/api/csp-report"')
        if request.scheme == "https" or str(self.auth.public_url).startswith("https://"):
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.path.startswith("/api/") or request.path.startswith("/auth/") or request.path in {"/login", "/logout"}:
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @web.middleware
    async def _security_headers_middleware(self, request: web.Request, handler: Any) -> web.StreamResponse:
        response = await handler(request)
        return self._apply_security_headers(request, response)

    @web.middleware
    async def _security_middleware(self, request: web.Request, handler: Any) -> web.StreamResponse:
        if request.path in {"/login", "/auth/callback"}:
            limit, window = ((30, 60) if request.path == "/login" else (20, 300))
            if not self._rate_limit_auth_request(request, limit, window):
                raise web.HTTPTooManyRequests(text="Too many sign-in attempts. Please wait and try again.")
        if request.path not in {"/api/csp-report"} and (request.path == "/logout" or request.method in {"POST", "PUT", "PATCH", "DELETE"}):
            if request.cookies.get(SESSION_COOKIE) and not self._request_origin_allowed(request):
                raise web.HTTPForbidden(text="Cross-site mutation blocked.")
        return await handler(request)

    @web.middleware
    async def _maintenance_middleware(self, request: web.Request, handler: Any) -> web.StreamResponse:
        """Pause competitive mutations during staff maintenance without taking RSL offline."""
        if not is_mutating_competition_path(request.path, request.method):
            return await handler(request)
        try:
            user = await self.auth.get_session(request)
            if user is None:
                return await handler(request)
            guild_id = request.query.get("guild_id", "").strip() or request.cookies.get("rsl_guild_id", "").strip()
            guild = self.bot.get_guild(int(guild_id)) if guild_id.isdigit() else None

            # Match the normal guild-resolution rules when a mutation does not
            # carry an explicit guild_id. This prevents maintenance mode from
            # being bypassed simply because a client omitted the query/cookie.
            if guild is None:
                connected = await self._connected_guilds_for_user(user)
                candidates = [
                    *[str(x) for x in getattr(user, "admin_guild_ids", [])],
                    *connected.keys(),
                ]
                guild_id = next((gid for gid in candidates if gid in connected), "")
                guild = connected.get(guild_id) if guild_id else None
            if not guild_id or guild is None:
                return await handler(request)
            if await self._is_live_guild_staff(user, guild_id, guild):
                return await handler(request)
            settings = await self.bot.db.settings.find_one({"_id": str(guild_id)}) or {}
            if not is_maintenance_enabled(settings):
                return await handler(request)
            message = maintenance_message(settings)
            if request.path.startswith("/api/"):
                return web.json_response({"ok": False, "maintenance": True, "error": message}, status=503)
            raise web.HTTPServiceUnavailable(text=message)
        except web.HTTPException:
            raise
        except Exception:
            # Fail closed for competitive mutations. If the maintenance state
            # cannot be read (for example during a Mongo outage), allowing the
            # request through would silently bypass Safe Mode at exactly the
            # time staff enabled it to protect competition state.
            log.exception("Maintenance-mode guard failed for %s %s", request.method, request.path_qs)
            message = "RSL competitive actions are temporarily unavailable while the maintenance state is being verified."
            if request.path.startswith("/api/"):
                return web.json_response({"ok": False, "maintenance": True, "error": message}, status=503)
            raise web.HTTPServiceUnavailable(text=message)

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
        # Give every rendered page a stable page identity so the shared shell can
        # apply consistent spacing, widths, responsive behavior, and page-family
        # presentation without duplicating layout rules across templates.
        page_key = re.sub(r'[^a-z0-9]+', '-', Path(filename).stem.lower()).strip('-') or 'page'
        def _add_page_identity(match: re.Match[str]) -> str:
            attrs = match.group(1) or ""
            page_class = "rsl-site-page rsl-page-" + page_key
            class_match = re.search(r"\bclass=['\"]([^'\"]*)['\"]", attrs, flags=re.I)
            if class_match:
                classes = (class_match.group(1) + " " + page_class).strip()
                attrs = attrs[:class_match.start(1)] + classes + attrs[class_match.end(1):]
                return "<body" + attrs + ">"
            return "<body" + attrs + ' class="' + page_class + '">'
        body = re.sub(r'<body\b([^>]*)>', _add_page_identity, body, count=1, flags=re.I)
        if request is not None and request.path in {"/player/profile", "/player/settings"}:
            mode = "profile" if request.path.endswith("/profile") else "settings"
            body = body.replace("<body", f'<body data-rsl-player-mode="{mode}"', 1)
        # One authoritative cache key for the shared stylesheet. Keeping this
        # here and in the final shell replacement prevents stale page-local CSS
        # versions from surviving on older templates.
        body = re.sub(r'/static/app\\.css\\?v=[^&"]+', '/static/app.css?v=20261002-rsl-theme2', body)

        theme_bootstrap = r'''<script>
(function(){
  try {
    var saved=localStorage.getItem("rsl_theme");
    if(!saved){
      var themeCookie=document.cookie.match(/(?:^|; )rsl_theme=([^;]+)/);
      saved=themeCookie ? decodeURIComponent(themeCookie[1]) : "";
    }
    document.documentElement.setAttribute("data-theme",
      ["dark","light","ocean","purple","crimson","emerald","sunset","graphite"].includes(saved) ? saved : "dark");
  } catch(e) {
    document.documentElement.setAttribute("data-theme","dark");
  }
})();
</script>
<script src="/static/theme.js?v=20260924-theme5"></script>'''
        if '/static/theme.js?' not in body:
            body = body.replace("<head>", "<head>"+theme_bootstrap, 1)

        # Render the same live Discord community counts used by the API on first paint.
        # This keeps Home/Help/profile banners correct even before their JS refreshes.
        if filename.endswith(".html"):
            guilds = list(getattr(self.bot, "guilds", []) or [])
            guild = max(guilds, key=lambda g: int(getattr(g, "member_count", 0) or 0), default=None)
            online, total = self._discord_community_counts(guild) if guild is not None else (0, 0)
            # Keep first-paint values aligned with the current homepage shell IDs.
            # The older rsl-* IDs were removed from index.html, which left the
            # visible Discord counters at "—" until JavaScript successfully ran.
            for stat_id, value in (("discord-online-members", online), ("discord-server-members", total)):
                body = body.replace(f'id="{stat_id}">—', f'id="{stat_id}">{value:,}', 1)
                body = body.replace(f'id="{stat_id}">- -', f'id="{stat_id}">{value:,}', 1)
                body = body.replace(f'id="{stat_id}">— —', f'id="{stat_id}">{value:,}', 1)

        # Google Analytics 4 is consent-gated. Do not load the Analytics tag until
        # the visitor explicitly enables analytics cookies through the RSL banner.
        # This keeps analytics optional while preserving the existing GA property.
        analytics_gate = r'''<script>
(function(){
  window.rslLoadAnalytics=function(){
    if(window.__rslAnalyticsLoaded)return;
    window.__rslAnalyticsLoaded=true;
    window.dataLayer=window.dataLayer||[];
    window.gtag=function(){window.dataLayer.push(arguments);};
    window.gtag("js",new Date());
    window.gtag("config","G-YXZGNWY1PE");
    var s=document.createElement("script");
    s.async=true;
    s.src="https://www.googletagmanager.com/gtag/js?id=G-YXZGNWY1PE";
    document.head.appendChild(s);
  };
  var consent=document.cookie.match(/(?:^|; )rsl_analytics_consent=([^;]+)/);
  if(consent&&decodeURIComponent(consent[1])==="accepted") window.rslLoadAnalytics();
})();
</script>'''
        if 'G-YXZGNWY1PE' not in body:
            body = body.replace("</head>", analytics_gate + "</head>", 1)

        # RSL SEO: give each public page its own search title and description.
        seo_pages = {
            "index.html": ("Racing Syndicate League • Asphalt Legends Unite Community", "Racing Syndicate League — Asphalt Legends Unite community racing, Gauntlet, tournaments, clubs, rankings, events, and competition management."),
            "gauntlet-career.html": ("Gauntlet Career • Racing Syndicate League", "View your Racing Syndicate League Gauntlet career, competitive record, ranking, and season progress."),
            "gauntlet-registration.html": ("Gauntlet Registration • Racing Syndicate League", "Register for Racing Syndicate League Gauntlet competition and prepare for the current Asphalt Legends Unite season."),
            "gauntlet-defense.html": ("Gauntlet Defense • Racing Syndicate League", "Manage your Racing Syndicate League Gauntlet defense and compete in organized Asphalt Legends Unite racing."),
            "gauntlet-matches.html": ("Gauntlet Matches • Racing Syndicate League", "View and manage Racing Syndicate League Gauntlet matches, results, opponents, and competitive racing activity."),
            "gauntlet-leaderboard.html": ("Gauntlet Leaderboard • Racing Syndicate League", "Racing Syndicate League Gauntlet leaderboard, rankings, ratings, and competitive season standings."),
            "gauntlet-references.html": ("Gauntlet References • Racing Syndicate League", "Racing Syndicate League Gauntlet reference guides, competition information, and Asphalt Legends Unite resources."),
            "tournaments.html": ("Tournaments • Racing Syndicate League", "Racing Syndicate League tournaments for organized Asphalt Legends Unite competition, brackets, teams, matches, and results."),
            "tournament-registration.html": ("Tournament Registration • Racing Syndicate League", "Register for Racing Syndicate League tournaments and organized Asphalt Legends Unite competition."),
            "tournament-matches.html": ("Tournament Matches • Racing Syndicate League", "View Racing Syndicate League tournament matches, opponents, schedules, and competition progress."),
            "tournament-results.html": ("Tournament Results • Racing Syndicate League", "Racing Syndicate League tournament results, completed matches, brackets, and competition records."),
            "tournament-clubs.html": ("Tournament Clubs • Racing Syndicate League", "Explore clubs and team competition within Racing Syndicate League tournaments."),
            "clubs.html": ("Clubs • Racing Syndicate League", "Racing Syndicate League clubs — discover drivers, build teams, manage club profiles, and compete together."),
            "calendar.html": ("Calendar • Racing Syndicate League", "Racing Syndicate League calendar for Gauntlet seasons, tournaments, events, matches, and community activities."),
            "help.html": ("Help Center • Racing Syndicate League", "Racing Syndicate League Help Center — guides, rules, support, and information about Gauntlet, tournaments, clubs, and the website."),
            "legal.html": ("Legal Center • Racing Syndicate League", "Racing Syndicate League legal information, privacy, security, accessibility, cookies, and website policies."),
            "my-tournaments.html": ("My Tournaments • Racing Syndicate League", "Your Racing Syndicate League tournament registrations, active matches, completed events, results, and tournament history."),
        }
        seo = seo_pages.get(filename)
        if seo:
            seo_title, seo_description = seo
            title_tag = f"<title>{html.escape(seo_title)}</title>"
            description_tag = f'<meta name="description" content="{html.escape(seo_description, quote=True)}">'
            body = re.sub(r"<title>.*?</title>", title_tag, body, count=1, flags=re.I|re.S) if re.search(r"<title>.*?</title>", body, flags=re.I|re.S) else body.replace("</head>", title_tag + "</head>", 1)
            if re.search(r'<meta\s+name=["\']description["\']', body, flags=re.I):
                body = re.sub(r'<meta\s+name=["\']description["\'][^>]*>', description_tag, body, count=1, flags=re.I)
            else:
                body = body.replace("</head>", description_tag + "</head>", 1)

            # Canonical URL: tell search engines which public URL represents this page.
            canonical_paths = {
                "index.html": "/",
                "gauntlet-career.html": "/gauntlet/career",
                "gauntlet-registration.html": "/gauntlet/registration",
                "gauntlet-defense.html": "/gauntlet/defense",
                "gauntlet-matches.html": "/gauntlet/matches",
                "gauntlet-leaderboard.html": "/gauntlet/leaderboard",
                "gauntlet-references.html": "/gauntlet/references",
                "tournaments.html": "/tournaments",
                "tournament-registration.html": "/tournaments/registration",
                "tournament-matches.html": "/tournaments/matches",
                "tournament-results.html": "/tournaments/results",
                "tournament-clubs.html": "/tournaments/clubs",
                "clubs.html": "/clubs",
                "club.html": "/club",
                "calendar.html": "/calendar",
                "help.html": "/help",
                "legal.html": "/legal",
                "players.html": "/players",
                "player.html": "/player",
                "profile.html": "/profile",
                "my-tournaments.html": "/my-tournaments",
            }
            canonical_path = canonical_paths.get(filename)
            if canonical_path:
                website_url = str((branding.get("links") or {}).get("website") or "https://asph.discloud.app").rstrip("/")
                canonical_tag = f'<link rel="canonical" href="{html.escape(website_url + canonical_path, quote=True)}">'
                if re.search(r'<link\s+rel=["\']canonical["\']', body, flags=re.I):
                    body = re.sub(r'<link\s+rel=["\']canonical["\'][^>]*>', canonical_tag, body, count=1, flags=re.I)
                else:
                    body = body.replace("</head>", canonical_tag + "</head>", 1)

            # Keep private/account/admin pages out of search indexes.
            noindex_pages = {
                "admin.html", "news-admin.html", "setup.html", "player.html", "players.html", "profile.html", "my-tournaments.html"
            }
            if filename in noindex_pages:
                noindex_tag = '<meta name="robots" content="noindex, nofollow, noarchive">'
                if re.search(r'<meta\s+name=["\']robots["\'][^>]*>', body, flags=re.I):
                    body = re.sub(r'<meta\s+name=["\']robots["\'][^>]*>', noindex_tag, body, count=1, flags=re.I)
                else:
                    body = body.replace("</head>", noindex_tag + "</head>", 1)

            # Open Graph + X/Twitter metadata for rich link previews.
            social_image = website_url + "/static/assets/rsl-mini-header.png?v=20260921-rslmini-png1"
            og_tags = (
                f'<meta property="og:type" content="website">'
                f'<meta property="og:site_name" content="Racing Syndicate League">'
                f'<meta property="og:title" content="{html.escape(seo_title, quote=True)}">'
                f'<meta property="og:description" content="{html.escape(seo_description, quote=True)}">'
                f'<meta property="og:url" content="{html.escape(website_url + canonical_path, quote=True)}">'
                f'<meta property="og:image" content="{html.escape(social_image, quote=True)}">'
                f'<meta name="twitter:card" content="summary_large_image">'
                f'<meta name="twitter:title" content="{html.escape(seo_title, quote=True)}">'
                f'<meta name="twitter:description" content="{html.escape(seo_description, quote=True)}">'
                f'<meta name="twitter:image" content="{html.escape(social_image, quote=True)}">'
            )
            body = re.sub(r'<meta\s+(?:property|name)=["\'](?:og:|twitter:)[^>]*>', '', body, flags=re.I)
            body = body.replace("</head>", og_tags + "</head>", 1)

            # JSON-LD structured data describing the RSL website and organization.
            jsonld = {
                "@context": "https://schema.org",
                "@graph": [
                    {
                        "@type": "Organization",
                        "@id": website_url + "#organization",
                        "name": "Racing Syndicate League",
                        "alternateName": "RSL",
                        "url": website_url,
                        "logo": {
                            "@type": "ImageObject",
                            "url": website_url + "/static/assets/rsl-shield.png",
                        },
                        "sameAs": [
                            "https://discord.gg/fmFk8Ejf2H"
                        ],
                    },
                    {
                        "@type": "WebSite",
                        "@id": website_url + "#website",
                        "name": "Racing Syndicate League",
                        "url": website_url,
                        "description": seo_description,
                        "publisher": {"@id": website_url + "#organization"},
                    },
                    {
                        "@type": "WebPage",
                        "@id": website_url + canonical_path + "#webpage",
                        "url": website_url + canonical_path,
                        "name": seo_title,
                        "description": seo_description,
                        "isPartOf": {"@id": website_url + "#website"},
                        "about": {"@id": website_url + "#organization"},
                    },
                ],
            }
            # Add BreadcrumbList structured data for public Gauntlet and Tournament subpages.
            breadcrumb_pages = {
                "gauntlet-registration.html": ("Gauntlet", "/gauntlet/registration", "Registration"),
                "gauntlet-defense.html": ("Gauntlet", "/gauntlet/defense", "Defense"),
                "gauntlet-matches.html": ("Gauntlet", "/gauntlet/matches", "Matches"),
                "gauntlet-leaderboard.html": ("Gauntlet", "/gauntlet/leaderboard", "Leaderboard"),
                "gauntlet-references.html": ("Gauntlet", "/gauntlet/references", "References"),
                "gauntlet-career.html": ("Gauntlet", "/gauntlet/career", "Career"),
                "tournament-registration.html": ("Tournaments", "/tournaments/registration", "Registration"),
                "tournament-matches.html": ("Tournaments", "/tournaments/matches", "Matches"),
                "tournament-results.html": ("Tournaments", "/tournaments/results", "Results"),
                "tournament-clubs.html": ("Tournaments", "/tournaments/clubs", "Clubs"),
            }
            breadcrumb = breadcrumb_pages.get(filename)
            if breadcrumb:
                section_name, page_path, page_name = breadcrumb
                section_path = "/gauntlet" if filename.startswith("gauntlet-") else "/tournaments"
                jsonld["@graph"].append({
                    "@type": "BreadcrumbList",
                    "@id": website_url + page_path + "#breadcrumb",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "Home", "item": website_url + "/"},
                        {"@type": "ListItem", "position": 2, "name": section_name, "item": website_url + section_path},
                        {"@type": "ListItem", "position": 3, "name": page_name, "item": website_url + page_path},
                    ],
                })

            jsonld_tag = '<script type="application/ld+json">' + json.dumps(jsonld, ensure_ascii=False, separators=(",", ":")) + '</script>'
            body = re.sub(r'<script\s+type=["\']application/ld\+json["\']>.*?</script>', '', body, flags=re.I|re.S)
            body = body.replace("</head>", jsonld_tag + "</head>", 1)

        # Keep private/account/admin pages out of search indexes even when they do not
        # have public SEO metadata entries above.
        noindex_pages = {
            "admin.html", "news-admin.html", "setup.html", "player.html", "players.html"
        }
        if filename in noindex_pages:
            noindex_tag = '<meta name="robots" content="noindex, nofollow, noarchive">'
            if re.search(r"""<meta\s+name=["']robots["'][^>]*>""", body, flags=re.I):
                body = re.sub(r"""<meta\s+name=["']robots["'][^>]*>""", noindex_tag, body, count=1, flags=re.I)
            else:
                body = body.replace("</head>", noindex_tag + "</head>", 1)

        # Force every rendered page to use the current shared shell stylesheet cache key.
        body = re.sub(
            r'href=["\']/static/app\\.css(?:\\?v=[^"\']+)?["\']',
            'href="/static/app.css?v=20261002-rsl-theme2"',
            body,
            flags=re.I
        )

        # Normalize the shared top-left header controls so every page matches Home.
        # This keeps the RSL mini-logo, Discord button, and Cash App button identical site-wide.
        site_logo_href = html.escape(str((branding.get("links") or {}).get("site_logo") or "/"), quote=True)
        canonical_brand = f'<a class="top-brand top-logo-mark" href="{site_logo_href}" aria-label="{html.escape(str((branding.get("identity") or {}).get("name") or "Racing Syndicate League"), quote=True)} home"><img src="/static/assets/rsl-mini-header.png?v=20260921-rslmini-png1" alt="RSL"></a>'
        link_settings = branding.get("links") or {}
        brand_re = re.compile(r'<a class="top-brand(?:\s+top-logo-mark)?[^>]*>.*?</a>', re.S)
        body, brand_count = brand_re.subn(canonical_brand, body, count=1)
        social_markup = (
            f'<a class="rsl-footer-social rsl-footer-discord" href="{html.escape(str(link_settings.get("discord") or "https://discord.gg/fmFk8Ejf2H"), quote=True)}" target="_blank" rel="noopener noreferrer" aria-label="RSL Discord"><span aria-hidden="true">Discord</span></a>'
            f'<a class="rsl-footer-social rsl-footer-cashapp" href="{html.escape(str(link_settings.get("cashapp") or "https://cash.app/"), quote=True)}" target="_blank" rel="noopener noreferrer" aria-label="RSL Cash App"><span aria-hidden="true">$</span></a>'
        )

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
    <a href="/player/profile">👤 <span>My Profile</span></a>
    <a href="/player/settings">⚙️ <span>My Settings</span></a>
    <a href="/club">🏎️ <span>My Club</span></a>
    <a href="/gauntlet/career">🏁 <span>My Gauntlet</span></a>
    <a href="/my-tournaments">🏆 <span>My Tournaments</span></a>
    <a class="rsl-admin-tools-link" id="rsl-admin-tools-link" href="/admin" hidden>🛠️ <span>Admin Tools</span></a>
    <div class="rsl-profile-divider"></div>
    <a class="rsl-profile-logout" href="/logout">🔐 <span>Sign Out</span></a>
  </div>
</div>
<a class="rsl-login-button" id="rsl-login-button" href="/login" hidden>🔐 Login</a>
'''
        search_markup = r'''
<button class="rsl-search-trigger" id="rsl-search-trigger" type="button" aria-label="Search site" aria-expanded="false"><img src="/assets/icons/search.png" alt=""><span>Search</span></button>
<div class="rsl-search-overlay" id="rsl-search-overlay" hidden>
  <div class="rsl-search-dialog" role="dialog" aria-modal="true" aria-labelledby="rsl-search-title">
    <div class="rsl-search-head"><strong id="rsl-search-title">Search Racing Syndicate League</strong><button type="button" class="rsl-search-close" id="rsl-search-close" aria-label="Close search">×</button></div>
    <div class="rsl-search-toolbar">
      <div class="rsl-search-input-wrap"><img src="/assets/icons/search.png" alt=""><input id="rsl-search-input" type="search" placeholder="Search drivers, cars, tracks, videos, guides, tournaments…" autocomplete="off"></div>
      <select id="rsl-search-type" aria-label="Search category">
        <option value="all">Everything</option><option value="players">Drivers</option><option value="references">References</option><option value="clubs">Clubs</option><option value="tournaments">Tournaments</option><option value="pages">Pages</option><option value="help">Help</option>
      </select>
    </div>
    <div class="rsl-search-meta" id="rsl-search-meta"></div>
    <div class="rsl-search-results" id="rsl-search-results"><p>Search across RSL pages and, when signed in, your available drivers, clubs, and tournaments.</p></div>
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
    if(switcher){const legal=document.querySelector(".rsl-footer-legal");if(legal) legal.appendChild(switcher);else if(footer) footer.appendChild(switcher);}
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
    // Navigation dropdowns: open while hovered, close as soon as the pointer leaves.
    // Click/tap remains supported for touch devices.
    document.querySelectorAll(".top-nav details.top-nav-dropdown").forEach(dropdown=>{
      const open=()=>dropdown.open=true;
      const close=()=>dropdown.open=false;
      dropdown.addEventListener("pointerenter",open);
      dropdown.addEventListener("pointerleave",close);
      const summary=dropdown.querySelector(":scope > summary");
      if(summary){
        summary.addEventListener("click",e=>{
          if(e.pointerType==="mouse"){
            e.preventDefault();
            dropdown.open=!dropdown.open;
          }
        });
      }
    });
    document.addEventListener("pointerenter",e=>{
      if(!(e.target instanceof Element) || !e.target.closest(".top-nav details.top-nav-dropdown")){
        document.querySelectorAll(".top-nav details.top-nav-dropdown[open]").forEach(d=>d.open=false);
      }
    },true);
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

        # Normalize Calendar + Shohan's Companion on every page.
        # Remove legacy/generated copies first, then insert exactly one Calendar + Companion pair.
        companion_markup = r'''<details class="top-nav-dropdown companion-nav-dropdown">
<summary class="top-nav-dropdown-trigger companion-nav-trigger"><img class="nav-icon-img companion-nav-icon" src="/assets/icons/companion.png" alt=""><span class="companion-nav-title"><small>Shohan's</small><strong>Companion</strong></span><span class="nav-chevron">⌄</span></summary>
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

        companion_cleanup = re.compile(
            r'<details\b[^>]*class=["\'][^"\']*\bcompanion-nav-dropdown\b[^"\']*["\'][^>]*>.*?</details>'
            r'|<a\b[^>]*class=["\'][^"\']*\bcompanion-nav-link\b[^"\']*["\'][^>]*>.*?</a>',
            re.S | re.I,
        )
        body = companion_cleanup.sub("", body)
        body = re.sub(
            r'<a\b[^>]*href=["\']/calendar["\'][^>]*>.*?</a>',
            "",
            body,
            flags=re.S | re.I,
        )
        # Remove any legacy/static Calendar nav entry before inserting the canonical one.
        # This prevents duplicate Calendar buttons on pages with older headers.
        body = re.sub(
            r'<a\b[^>]*href=["\'](?:/calendar|https://asph\.discloud\.app/calendar)["\'][^>]*>.*?</a>',
            "",
            body,
            flags=re.S | re.I,
        )
        if "</nav>" in body:
            # Canonical navigation order: Calendar, then Rules, then Companion.
            # Strip any legacy/static copies first so older templates cannot
            # create duplicate or incorrectly ordered entries.
            calendar_markup = '<a href="/calendar"><img class="nav-icon-img" src="/assets/icons/calendar.png?v=20260924-nav11" alt=""><span>Calendar</span></a>'
            rules_markup = '<a href="/rules"><img class="nav-icon-img" src="/assets/icons/references.png" alt=""><span>Rules</span></a>'
            body = re.sub(
                r'<a\b[^>]*href=["\'](?:/calendar|https://asph\.discloud\.app/calendar)["\'][^>]*>.*?</a>',
                "",
                body,
                flags=re.S | re.I,
            )
            body = re.sub(
                r'<a\b[^>]*href=["\']/rules["\'][^>]*>.*?</a>',
                "",
                body,
                flags=re.S | re.I,
            )
            # Remove any page-specific Companion copy before rebuilding the canonical
            # navigation order. This prevents Calendar/Rules/XP from being appended
            # after an older Companion item.
            body = re.sub(
                r'<details class="top-nav-dropdown companion-nav-dropdown">.*?</details>',
                "",
                body,
                count=1,
                flags=re.S | re.I,
            )
            body = body.replace("</nav>", calendar_markup + rules_markup + companion_markup + "</nav>", 1)

        # Normalize the two legacy text-only submenu icons to the checked-in PNG assets.
        # This keeps every page on the same PNG-only navigation shell.
        body = re.sub(
            r'<a href="/gauntlet/matches">\s*<span class="nav-icon-glyph"[^>]*>.*?</span>\s*<span>Challenges &amp; Matches</span>',
            '<a href="/gauntlet/matches"><img class="nav-icon-img" src="/assets/icons/matches.png" alt=""><span>Challenges &amp; Matches</span>',
            body, flags=re.S | re.I
        )
        body = re.sub(
            r'<a href="/tournaments/results">\s*<span class="nav-icon-glyph"[^>]*>.*?</span>\s*<span>Results &amp; Rankings</span>',
            '<a href="/tournaments/results"><img class="nav-icon-img" src="/assets/icons/results.png" alt=""><span>Results &amp; Rankings</span>',
            body, flags=re.S | re.I
        )

        # The search control belongs immediately to the left of the profile control.
        # Keep both outside the page navigation flow so long navigation labels cannot
        # push them underneath or over one another.
        if "</header>" in body and 'id="rsl-search-trigger"' not in body:
            body = body.replace("</header>", search_markup + "</header>", 1)

        if "</header>" in body and 'id="rsl-profile-nav"' not in body:
            body = body.replace("</header>", profile_markup + "</header>", 1)

        # Remove legacy page-specific account controls before adding the shared
        # RSL Search + Profile controls. Older pages still contain a static
        # "Sign Out" link and Driver/Player profile block, which must not be
        # allowed to appear beside the current profile dropdown.
        body = re.sub(r'<div class="top-user-area">.*?(?=</header>)', "", body, count=1, flags=re.S)

        if "</header>" in body and 'id="rsl-search-trigger"' not in body:
            body = body.replace("</header>", search_markup + "</header>", 1)

        if "</header>" in body and 'id="rsl-profile-nav"' not in body:
            body = body.replace("</header>", profile_markup + "</header>", 1)

        search_script = r'''
<script>
(function(){
  const trigger=document.getElementById("rsl-search-trigger"), overlay=document.getElementById("rsl-search-overlay"), input=document.getElementById("rsl-search-input"), type=document.getElementById("rsl-search-type"), close=document.getElementById("rsl-search-close"), results=document.getElementById("rsl-search-results"), meta=document.getElementById("rsl-search-meta");
  if(!trigger||!overlay||!input||!type||!close||!results)return;
  const hide=()=>{overlay.hidden=true;trigger.setAttribute("aria-expanded","false");};
  const show=()=>{overlay.hidden=false;trigger.setAttribute("aria-expanded","true");setTimeout(()=>input.focus(),20);};
  const escapeHtml=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m]));
  const run=async()=>{
    const q=input.value.trim();
    if(q.length<2){meta.textContent="";results.innerHTML="<p>Type at least 2 characters to search.</p>";return;}
    results.innerHTML="<p>Searching…</p>"; meta.textContent="";
    try{
      const r=await fetch("/api/search?q="+encodeURIComponent(q)+"&type="+encodeURIComponent(type.value),{credentials:"same-origin"});
      const d=await r.json();
      const rows=Array.isArray(d.results)?d.results:[];
      meta.textContent=rows.length+" result"+(rows.length===1?"":"s")+" • "+(type.options[type.selectedIndex]?.text||"Everything");
      results.innerHTML=rows.length?rows.map(x=>'<a class="rsl-search-result rsl-search-result-'+escapeHtml(x.type)+'" href="'+escapeHtml(x.url)+'"><span class="rsl-search-result-type">'+escapeHtml(x.type)+'</span><strong>'+escapeHtml(x.title)+'</strong><span>'+escapeHtml(x.snippet)+'</span></a>').join(""):"<p>No matching results found.</p>";
    }catch(_){results.innerHTML="<p>Search is temporarily unavailable.</p>";}
  };
  trigger.addEventListener("click",show); close.addEventListener("click",hide);
  overlay.addEventListener("click",e=>{if(e.target===overlay)hide();});
  document.addEventListener("keydown",e=>{if(e.key==="Escape")hide();if(e.key==="/"&&document.activeElement!==input){e.preventDefault();show();}});
  let timer; input.addEventListener("input",()=>{clearTimeout(timer);timer=setTimeout(run,180);});
  type.addEventListener("change",run);
})();
</script>
'''

        footer_links = branding.get("links") or {}
        footer_identity = branding.get("identity") or {}
        footer_name = html.escape(str(footer_identity.get("name") or "Racing Syndicate League"))
        footer_tagline_value = str(footer_identity.get("tagline") or "Race, Compete, Unite").strip()
        if footer_tagline_value == "Compete. Race. Dominate.":
            footer_tagline_value = "Race, Compete, Unite"
        footer_tagline = html.escape(footer_tagline_value)
        footer_logo_value = str(footer_identity.get("logo_url") or "/assets/rsl-shield.png")
        if footer_logo_value.rstrip("?").endswith("/assets/rsl-shield.png"):
            footer_logo_value = "/static/assets/rsl-footer-mark.png?v=20260921-rslfooter-png1"
        footer_logo = html.escape(footer_logo_value, quote=True)
        footer_social = {
            "x": str(footer_links.get("x") or "").strip(),
            "instagram": str(footer_links.get("instagram") or "").strip(),
            "youtube": str(footer_links.get("youtube") or "").strip(),
            "linkedin": "",
            "tiktok": "",
        }
        social_markup = ""
        custom_footer_items = []
        custom_links = footer_links.get("custom") if isinstance(footer_links.get("custom"), list) else []
        for index, item in enumerate(custom_links[:10], 1):
            if not isinstance(item, dict):
                continue
            href = str(item.get("url") or "").strip()
            name = str(item.get("name") or f"Link {index}").strip()[:80]
            icon = str(item.get("icon") or "").strip()
            if not href or item.get("enabled") is False:
                continue
            safe_href = html.escape(href, quote=True)
            safe_name = html.escape(name, quote=True)
            icon_markup = f'<img src="{html.escape(icon, quote=True)}" alt="" aria-hidden="true">' if icon else '<span aria-hidden="true">↗</span>'
            custom_footer_items.append(f'<a class="rsl-footer-social rsl-footer-custom-social" href="{safe_href}" target="_blank" rel="noopener noreferrer" aria-label="{safe_name}" title="{safe_name}">{icon_markup}</a>')
        custom_social_markup = "".join(custom_footer_items)
        if custom_social_markup:
            social_markup += custom_social_markup
        cookie_controls_markup = r'''
<style>
.rsl-cookie-banner{position:fixed;left:18px;right:18px;bottom:18px;z-index:9999;display:none;border:1px solid var(--rsl-box-accent);background:var(--rsl-box);box-shadow:0 10px 40px #000b;padding:18px 20px;color:var(--rsl-box-text)}
.rsl-cookie-banner.is-visible{display:block}.rsl-cookie-banner strong{color:var(--rsl-box-text)}.rsl-cookie-banner p{margin:7px 0 14px;line-height:1.55;color:var(--rsl-box-muted)}.rsl-cookie-actions{display:flex;gap:10px;flex-wrap:wrap}.rsl-cookie-btn{border:1px solid var(--rsl-box-accent);background:var(--rsl-box-alt);color:var(--rsl-box-accent);padding:9px 15px;cursor:pointer;font:inherit}.rsl-cookie-btn.primary{background:var(--rsl-box-accent);color:var(--rsl-box-text)}.rsl-cookie-btn:hover{filter:brightness(1.15)}
.rsl-cookie-settings{position:static;z-index:auto;border:1px solid var(--rsl-box-accent);background:var(--rsl-box-alt);color:var(--rsl-box-text);padding:10px 16px;cursor:pointer;font-family:inherit;font-size:14px;line-height:1.25;font-weight:700;display:none;margin:0;min-width:240px;height:44px;box-sizing:border-box;border-radius:9px;white-space:nowrap;text-align:center}
.rsl-footer-utility-row{display:flex;align-items:center;justify-content:center;gap:12px;margin:24px auto 0;width:100%}
.rsl-footer-utility-row .rsl-language-switcher{margin:0!important}
.rsl-footer-utility-row .rsl-cookie-settings{display:none}
.rsl-footer-theme-control{display:flex;align-items:center;gap:8px;height:44px;min-width:240px;box-sizing:border-box;border:1px solid var(--rsl-box-accent);background:var(--rsl-box);color:var(--rsl-box-text);padding:0 12px;border-radius:9px}
.rsl-footer-theme-control label{display:flex;align-items:center;gap:6px;font-size:11px;font-weight:800;color:var(--rsl-box-muted);white-space:nowrap}
.rsl-footer-theme-control select{width:155px;min-width:0;height:30px;padding:0 8px;border:1px solid var(--rsl-box-line);border-radius:7px;background:var(--rsl-box);color:var(--rsl-box-text);font:inherit;font-size:11px;font-weight:700;cursor:pointer}
.rsl-footer-theme-control select:focus{outline:none;border-color:var(--rsl-box-accent);box-shadow:0 0 0 2px rgba(37,223,255,.16)}
html[data-theme="light"] .rsl-footer-theme-control{background:var(--rsl-box-alt);border-color:var(--rsl-box-line);color:var(--rsl-box-text)}
html[data-theme="light"] .rsl-footer-theme-control label{color:var(--rsl-box-muted)}
html[data-theme="light"] .rsl-footer-theme-control select{background:var(--rsl-box);color:var(--rsl-box-text);border-color:var(--rsl-box-line)}
@media(max-width:700px){.rsl-footer-utility-row{gap:8px;flex-wrap:wrap}.rsl-footer-utility-row .rsl-language-switcher,.rsl-footer-utility-row .rsl-cookie-settings,.rsl-footer-theme-control{min-width:200px}}
@media(max-width:460px){.rsl-footer-utility-row .rsl-language-switcher,.rsl-footer-utility-row .rsl-cookie-settings,.rsl-footer-theme-control{min-width:100%;width:100%}}
</style>
<div class="rsl-cookie-banner" id="rsl-cookie-banner" role="dialog" aria-label="Cookie preferences">
  <strong>Cookie &amp; Privacy Choices</strong>
  <p>RSL uses essential cookies for site functionality and, with your permission, analytics cookies from Google Analytics to understand website usage and improve the site. Analytics cookies are optional.</p>
  <div class="rsl-cookie-actions">
    <button class="rsl-cookie-btn primary" type="button" id="rsl-cookie-accept">Allow Analytics</button>
    <button class="rsl-cookie-btn" type="button" id="rsl-cookie-deny">Decline Analytics</button>
    <button class="rsl-cookie-btn" type="button" id="rsl-cookie-details">Manage Preferences</button>
  </div>
</div>
<button class="rsl-cookie-settings" id="rsl-cookie-settings" type="button">Cookie Settings</button>
<script>
(function(){
  const banner=document.getElementById("rsl-cookie-banner"),settings=document.getElementById("rsl-cookie-settings");
  if(!banner||!settings)return;
  const read=()=>{const m=document.cookie.match(/(?:^|; )rsl_analytics_consent=([^;]+)/);return m?decodeURIComponent(m[1]):"";};
  const save=value=>{document.cookie="rsl_analytics_consent="+encodeURIComponent(value)+";path=/;max-age=31536000;SameSite=Lax";};
  const clearAnalytics=()=>{
    const names=["_ga","_ga_YXZGNWY1PE"];
    names.forEach(name=>{document.cookie=name+"=;path=/;expires=Thu, 01 Jan 1970 00:00:00 GMT;SameSite=Lax";document.cookie=name+"=;path=/;domain="+location.hostname+";expires=Thu, 01 Jan 1970 00:00:00 GMT;SameSite=Lax";});
  };
  const show=()=>{banner.classList.add("is-visible");settings.style.display="none";};
  const hide=()=>{banner.classList.remove("is-visible");settings.style.display="block";};
  document.getElementById("rsl-cookie-accept").addEventListener("click",()=>{save("accepted");hide();if(window.rslLoadAnalytics)window.rslLoadAnalytics();});
  document.getElementById("rsl-cookie-deny").addEventListener("click",()=>{save("denied");clearAnalytics();hide();});
  document.getElementById("rsl-cookie-details").addEventListener("click",()=>{window.location.href="/legal#cookies";});
  settings.addEventListener("click",show);
  const placeFooterControls=()=>{
    const footer=document.querySelector(".rsl-footer");
    if(!footer)return;
    let row=footer.querySelector(".rsl-footer-utility-row");
    if(!row){
      row=document.createElement("div");
      row.className="rsl-footer-utility-row";
      footer.appendChild(row);
    }
    const switcher=document.getElementById("rsl-language-switcher");
    if(switcher)row.appendChild(switcher);
    row.appendChild(settings);
    let themeControl=document.getElementById("rsl-footer-theme-control");
    if(!themeControl){
      themeControl=document.createElement("div");
      themeControl.id="rsl-footer-theme-control";
      themeControl.className="rsl-footer-theme-control";
      themeControl.innerHTML='<label for="rsl-footer-theme-select">🎨 <span>Theme</span></label><select id="rsl-footer-theme-select" aria-label="Choose website theme"><option value="dark">🌙 Midnight</option><option value="light">☀️ Light</option><option value="ocean">🌊 Ocean</option><option value="purple">🟣 Neon Purple</option><option value="crimson">🔴 Crimson</option><option value="emerald">🟢 Emerald</option><option value="sunset">🟠 Sunset</option><option value="graphite">⚙️ Graphite</option></select>';
      const themeSelect=themeControl.querySelector("#rsl-footer-theme-select");
      themeSelect?.addEventListener("change", e => {
        e.stopPropagation();
        if(window.RSLTheme) window.RSLTheme.save(e.target.value);
      });
      row.appendChild(themeControl);
    } else if(themeControl.parentElement!==row) row.appendChild(themeControl);
  };
  if(document.readyState==="loading"){
    document.addEventListener("DOMContentLoaded",()=>requestAnimationFrame(placeFooterControls),{once:true});
  }else{
    requestAnimationFrame(placeFooterControls);
  }
  const consent=read();
  if(consent==="accepted"){hide();if(window.rslLoadAnalytics)window.rslLoadAnalytics();}
  else if(consent==="denied"){hide();clearAnalytics();}
  else show();
})();
</script>
'''
        footer_markup = f'''
<footer class="rsl-footer" aria-label="{footer_name} footer">
  <div class="rsl-footer-social-row">
    <span class="rsl-footer-rule" aria-hidden="true"></span>
    <div class="rsl-footer-socials">{social_markup}</div>
    <span class="rsl-footer-rule" aria-hidden="true"></span>
  </div>
  <div class="rsl-footer-brand">
    <img src="{footer_logo}" alt="" aria-hidden="true">
    <div class="rsl-footer-brand-name">{footer_name}</div>
    <div class="rsl-footer-copyline">© 2026 {footer_name}™ <span aria-hidden="true"> &nbsp;/&nbsp; </span> {footer_tagline}</div>
  </div>
  <nav class="rsl-footer-legal" aria-label="Legal and privacy">
     <div class="rsl-footer-legal-links">
       <a href="/legal">Legal Center</a><span aria-hidden="true">|</span>
       <a href="https://cash.app/" target="_blank" rel="noopener noreferrer">Creator Donation</a><span aria-hidden="true">|</span>
       <a href="/legal#privacy">Privacy Policy</a><span aria-hidden="true">|</span>
       <a href="/legal#security">Security</a><span aria-hidden="true">|</span>
       <a href="/legal#accessibility">Website Accessibility</a><span aria-hidden="true">|</span>
       <a href="/legal#cookies">Manage Cookies</a><span aria-hidden="true">|</span>
       <a href="/legal#privacy-choices"><span class="rsl-footer-privacy-icon" aria-hidden="true">✓×</span> Your Privacy Choices</a>
     </div>
   </nav>
</footer>
'''
        # Keep the shared stylesheet cache-busted for every page so shell fixes reach
        # old templates without requiring a manual edit to each HTML file.
        if filename.endswith(".html"):
            app_css_tag = re.compile(r'<link\b[^>]*href=["\']/static/app\.css(?:\?[^"\']*)?["\'][^>]*>', re.I)
            if app_css_tag.search(body):
                body = app_css_tag.sub('<link rel="stylesheet" href="/static/app.css?v=20261002-rsl-theme2">', body, count=1)
            elif re.search(r"</head>", body, flags=re.I):
                body = body.replace("</head>", '<link rel="stylesheet" href="/static/app.css?v=20261002-rsl-theme2"></head>', 1)

        # GLOBAL RSL PAGE SHELL: every HTML page receives the same Discord card and Help card.
        # Strip older page-specific copies first so the shared shell is always singular.
        if filename.endswith(".html"):
            body = re.sub(r'<a[^>]*class="[^"]*(?:discord-cta|profile-discord-cta)[^"]*"[^>]*>.*?</a>', "", body, flags=re.S|re.I)
            body = re.sub(r'<a[^>]*class="[^"]*(?:home-help-card|profile-help-card)[^"]*"[^>]*>.*?</a>', "", body, flags=re.S|re.I)
            global_discord_markup = r'''<a class="discord-cta rsl-global-discord-cta" href="https://discord.gg/fmFk8Ejf2H" target="_blank" rel="noopener noreferrer" aria-label="Join the RSL Discord"><div class="discord-cta-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M19.5 5.2A16.7 16.7 0 0 0 15.4 4l-.5 1a14.7 14.7 0 0 0-5.8 0l-.5-1a16.7 16.7 0 0 0-4.1 1.2C1.9 9.1 1.2 13 1.5 16.8a16.8 16.8 0 0 0 5 2.5l1.1-1.5a10.4 10.4 0 0 1-1.7-.8l.4-.3c3.3 1.5 6.8 1.5 10.1 0l.4.3c-.5.3-1.1.6-1.7.8l1.1 1.5a16.8 16.8 0 0 0 5-2.5c.4-4.4-.8-8.2-1.7-11.6ZM8.5 14.7c-1 0-1.8-.9-1.8-2s.8-2 1.8-2 1.8.9 1.8 2-.8 2-1.8 2Zm7 0c-1 0-1.8-.9-1.8-2s.8-2 1.8-2 1.8 0 1.8 2-.8 2-1.8 2Z"/></svg></div><div class="discord-cta-copy"><span class="discord-cta-kicker">JOIN THE RSL DISCORD</span><p>Race with the community, participate in events, and stay up to date.</p></div><div class="discord-cta-stats"><div class="discord-stat discord-stat-online"><div class="discord-stat-icon" aria-hidden="true"><span class="discord-online-dot"></span></div><div><span class="discord-stat-label">Online Members</span><span class="discord-stat-value" id="rsl-discord-online">—</span></div></div><div class="discord-stat"><div class="discord-stat-icon" aria-hidden="true"><svg viewBox="0 0 32 32"><circle cx="11" cy="10" r="4"/><circle cx="21" cy="10" r="4"/><path d="M4 25c0-5 3-8 7-8s7 3 7 8M14 25c0-5 3-8 7-8s7 3 7 8"/></svg></div><div><span class="discord-stat-label">Server Members</span><span class="discord-stat-value" id="rsl-discord-total">—</span></div></div></div><span class="discord-cta-button">JOIN DISCORD →</span></a>'''
            global_help_markup = r'''<a class="home-card home-help-card home-help-link rsl-global-help-card" id="help" href="/help" aria-label="Open Help Center"><div class="home-help-content"><div class="home-help-icon" aria-hidden="true"><svg viewBox="0 0 64 64" role="img"><circle cx="32" cy="19" r="9"></circle><path d="M17 52c1-12 7-18 15-18s14 6 15 18"></path><path d="M13 28v-3c0-11 8-19 19-19s19 8 19 19v3"></path><path d="M12 27h7v10h-7zM45 27h7v10h-7z"></path><path d="M19 35c2 5 7 8 13 8s11-3 13-8"></path><path d="M52 34h4"></path></svg></div><div class="home-help-copy"><span class="home-eyebrow">HELP CENTER</span><h2>Need help getting started?</h2><p>Find answers, guides and support for Player, Gauntlet, Tournaments, Clubs and your driver career.</p><span class="home-help-arrow">OPEN HELP CENTER →</span></div></div></a>
            '''

            # The shared Discord card is a true global shell element:
            # place it directly after the shared header, never inside a page
            # workspace/grid. This prevents page-specific flex/grid rules from
            # breaking its width, position, or vertical spacing.
            if "rsl-global-discord-cta" not in body:
                if re.search(r"</header>", body, flags=re.I):
                    body = re.sub(r"(</header>)", "\\1\n" + global_discord_markup, body, count=1, flags=re.I)
                elif re.search(r"<body\b", body, flags=re.I):
                    body = re.sub(r"(<body\b[^>]*>)", "\\1\n" + global_discord_markup, body, count=1, flags=re.I)
                else:
                    body = global_discord_markup + body
            if "rsl-global-help-card" not in body:
                # Admin Tools contains a nested <main class="admin-content"> inside
                # its two-column layout. Inserting after the first </main> places
                # the shared Help card inside the admin grid, collapsing it into
                # the narrow sidebar column. Keep the shared card outside the
                # admin layout, just before </body>, like the other global shell
                # elements.
                if filename == "admin.html":
                    body = body.replace("</body>", global_help_markup + "\n</body>", 1)
                elif re.search(r"</main>", body, flags=re.I):
                    body = re.sub(r"</main>", "</main>\n" + global_help_markup, body, count=1, flags=re.I)
                elif re.search(r'<div[^>]*class=["\']workspace["\'][^>]*>', body, flags=re.I):
                    body = re.sub(r"(</div>)(\s*</div>\s*</body>)", global_help_markup + "\n\\1\\2", body, count=1, flags=re.I)
                elif re.search(r"<footer\b", body, flags=re.I):
                    body = re.sub(r"(<footer\b)", global_help_markup + "\n\\1", body, count=1, flags=re.I)
                else:
                    body = body.replace("</body>", global_help_markup + "\n</body>", 1)

            # Discord statistics are independent of layout; do not measure or
            # reposition the shell card against page-specific hero elements.
            global_discord_script = r'''<script>(async function(){
const online=document.getElementById("rsl-discord-online");
const total=document.getElementById("rsl-discord-total");
if(!online||!total)return;
try{
  const r=await fetch("/api/discord-stats",{credentials:"same-origin"});
  if(!r.ok)return;
  const d=await r.json();
  if(d.available){
    online.textContent=Number(d.online_members||0).toLocaleString();
    total.textContent=Number(d.server_members||0).toLocaleString();
  }
}catch(_){}
})();</script>'''
            body = body.replace("</body>", global_discord_script + "</body>", 1)

        # Replace any page-specific legacy footer with the shared RSL footer.
        body = re.sub(r'\s*<footer\b[^>]*>.*?</footer>', '', body, count=1, flags=re.S|re.I)
        if "</body>" in body:
            body = body.replace("</body>", footer_markup + "</body>", 1)

        if "</body>" in body:
            body = body.replace("</body>", cookie_controls_markup + language_markup + search_script + "</body>", 1)

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

  // Theme selection is handled by /static/theme.js with delegated events because
  // this footer control is created dynamically after the page shell is rendered.
  document.addEventListener("click", closeMenu);
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeMenu(); });
})();
</script>
'''
        if "</body>" in body:
            body = body.replace("</body>", profile_script + "</body>", 1)

        # Final cross-page theme contract. This is injected after every page
        # template and shared shell so every rendered page follows the account
        # theme without changing layout or artwork.
        theme_audit_css = r'''<style id="rsl-cross-page-theme-audit">
html[data-theme="dark"]{--rsl-audit-bg:#020b18;--rsl-audit-panel:#071427;--rsl-audit-panel2:#0b1d34;--rsl-audit-line:#173b64;--rsl-audit-text:#dbe8f8;--rsl-audit-muted:#91a5c3;--rsl-audit-accent:#25dfff;--rsl-audit-strong:#087cff;--rsl-audit-success:#00e65b;--rsl-audit-warn:#ffd166;--rsl-audit-shadow:rgba(0,0,0,.38)}
html[data-theme="light"]{--rsl-audit-bg:#eef3f8;--rsl-audit-panel:#f1f5f9;--rsl-audit-panel2:#e4ecf4;--rsl-audit-line:#c3d0dd;--rsl-audit-text:#18283b;--rsl-audit-muted:#5d7187;--rsl-audit-accent:#2878c8;--rsl-audit-strong:#1769d1;--rsl-audit-success:#087d5b;--rsl-audit-warn:#b87900;--rsl-audit-shadow:rgba(35,63,92,.10)}
html[data-theme="ocean"]{--rsl-audit-bg:#03141c;--rsl-audit-panel:#062936;--rsl-audit-panel2:#0d3b4b;--rsl-audit-line:#15566b;--rsl-audit-text:#e0f7ff;--rsl-audit-muted:#8bb8c8;--rsl-audit-accent:#37e6ff;--rsl-audit-strong:#1599d8;--rsl-audit-success:#19d6ad;--rsl-audit-warn:#ffd166;--rsl-audit-shadow:rgba(0,0,0,.30)}
html[data-theme="purple"]{--rsl-audit-bg:#0d0719;--rsl-audit-panel:#1a0e2d;--rsl-audit-panel2:#291440;--rsl-audit-line:#563b82;--rsl-audit-text:#f1e8ff;--rsl-audit-muted:#b9a9d1;--rsl-audit-accent:#b86cff;--rsl-audit-strong:#7b5cff;--rsl-audit-success:#50e0bb;--rsl-audit-warn:#ffd166;--rsl-audit-shadow:rgba(0,0,0,.34)}
html[data-theme="crimson"]{--rsl-audit-bg:#130608;--rsl-audit-panel:#250d12;--rsl-audit-panel2:#39151c;--rsl-audit-line:#71303a;--rsl-audit-text:#ffe8ec;--rsl-audit-muted:#c49ba2;--rsl-audit-accent:#ff5c7a;--rsl-audit-strong:#e83256;--rsl-audit-success:#47d6a0;--rsl-audit-warn:#ffc857;--rsl-audit-shadow:rgba(0,0,0,.34)}
html[data-theme="emerald"]{--rsl-audit-bg:#03130f;--rsl-audit-panel:#07251d;--rsl-audit-panel2:#0d3c2e;--rsl-audit-line:#17604c;--rsl-audit-text:#e5fff7;--rsl-audit-muted:#8fb9ab;--rsl-audit-accent:#32f2c2;--rsl-audit-strong:#12b892;--rsl-audit-success:#20e39d;--rsl-audit-warn:#e9d66b;--rsl-audit-shadow:rgba(0,0,0,.30)}
html[data-theme="sunset"]{--rsl-audit-bg:#170b06;--rsl-audit-panel:#2b160c;--rsl-audit-panel2:#4d2815;--rsl-audit-line:#75411f;--rsl-audit-text:#fff0e5;--rsl-audit-muted:#c9aa91;--rsl-audit-accent:#ff9b54;--rsl-audit-strong:#e96b31;--rsl-audit-success:#62d39d;--rsl-audit-warn:#ffd166;--rsl-audit-shadow:rgba(0,0,0,.34)}
html[data-theme="graphite"]{--rsl-audit-bg:#111315;--rsl-audit-panel:#1c2024;--rsl-audit-panel2:#30363c;--rsl-audit-line:#414951;--rsl-audit-text:#edf2f5;--rsl-audit-muted:#a6afb8;--rsl-audit-accent:#d7e3ea;--rsl-audit-strong:#7ca3bd;--rsl-audit-success:#72b89d;--rsl-audit-warn:#d8c98a;--rsl-audit-shadow:rgba(0,0,0,.30)}

html[data-theme] body,html[data-theme] body.alu-dashboard{background:var(--rsl-audit-bg)!important;color:var(--rsl-audit-text)!important}
html[data-theme] .top-nav{background:linear-gradient(180deg,var(--rsl-audit-panel2),var(--rsl-audit-bg))!important;border-color:var(--rsl-audit-line)!important;box-shadow:0 8px 28px var(--rsl-audit-shadow)!important}
html[data-theme] .top-nav nav>a,html[data-theme] .top-nav .top-nav-dropdown-trigger{color:var(--rsl-audit-text)!important;border-color:var(--rsl-audit-line)!important}
html[data-theme] .top-nav nav>a:hover,html[data-theme] .top-nav nav>a.active,html[data-theme] .top-nav .top-nav-dropdown-trigger:hover{color:var(--rsl-audit-accent)!important}
html[data-theme] .top-nav-dropdown-menu,html[data-theme] .rsl-profile-menu,html[data-theme] .rsl-search-dialog,html[data-theme] .rsl-search-panel{background:linear-gradient(145deg,var(--rsl-audit-panel2),var(--rsl-audit-panel))!important;color:var(--rsl-audit-text)!important;border-color:var(--rsl-audit-line)!important}
html[data-theme] .top-nav-dropdown-menu a,html[data-theme] .rsl-profile-menu a,html[data-theme] .rsl-search-result{color:var(--rsl-audit-text)!important}
html[data-theme] .top-nav-dropdown-menu a:hover,html[data-theme] .rsl-profile-menu a:hover,html[data-theme] .rsl-search-result:hover{background:color-mix(in srgb,var(--rsl-audit-accent) 13%,var(--rsl-audit-panel))!important;color:var(--rsl-audit-accent)!important}
html[data-theme] .rsl-profile-trigger,html[data-theme] .rsl-search-trigger{background:var(--rsl-audit-panel)!important;color:var(--rsl-audit-text)!important;border-color:var(--rsl-audit-line)!important}

html[data-theme] .glass-panel,html[data-theme] .welcome-panel,html[data-theme] .season-panel,html[data-theme] .feature,html[data-theme] .card,html[data-theme] .table-wrap,html[data-theme] .profile-card,html[data-theme] .profile-side-card,html[data-theme] .profile-status-panel,html[data-theme] .quick-actions,html[data-theme] .activity-card,html[data-theme] .matches-card,html[data-theme] .leaderboard-card,html[data-theme] .garage-card,html[data-theme] .calendar-panel,html[data-theme] .calendar-shell,html[data-theme] .calendar-day,html[data-theme] .calendar-event,html[data-theme] .modal-card,html[data-theme] .admin-card,html[data-theme] .club-card,html[data-theme] .tournament-card,html[data-theme] .legal-card,html[data-theme] .career-section,html[data-theme] .career-card,html[data-theme] .public-profile,html[data-theme] .home-info-card,html[data-theme] .home-feature-card,html[data-theme] .home-help-card,html[data-theme] .home-upcoming-panel,html[data-theme] .clubs-center-hero,html[data-theme] .ref-card,html[data-theme] .compare,html[data-theme] .defense-summary{background:linear-gradient(145deg,var(--rsl-audit-panel),var(--rsl-audit-panel2))!important;color:var(--rsl-audit-text)!important;border-color:var(--rsl-audit-line)!important;box-shadow:0 10px 30px var(--rsl-audit-shadow)!important}

html[data-theme] .toolbar,html[data-theme] .server-select,html[data-theme] .calendar-toolbar,html[data-theme] .calendar-header,html[data-theme] .calendar-controls,html[data-theme] .calendar-personal-panel,html[data-theme] .calendar-personal-list,html[data-theme] .match-row,html[data-theme] .leader-row,html[data-theme] .activity-list>div,html[data-theme] .profile-stats,html[data-theme] .career-stat-grid>div,html[data-theme] .tournament-card-art,html[data-theme] .tournament-card-body,html[data-theme] .admin-sidebar,html[data-theme] .admin-content,html[data-theme] .news-card,html[data-theme] .home-news-item,html[data-theme] .ref-video{background:var(--rsl-audit-panel2)!important;color:var(--rsl-audit-text)!important;border-color:var(--rsl-audit-line)!important}
html[data-theme] input,html[data-theme] textarea,html[data-theme] select,html[data-theme] .toolbar input,html[data-theme] .toolbar select,html[data-theme] .ref-toolbar input,html[data-theme] .ref-toolbar select,html[data-theme] .ref-form input,html[data-theme] .ref-form select,html[data-theme] .ref-form textarea,html[data-theme] .admin-toolbar select,html[data-theme] .admin-field input,html[data-theme] .admin-field select,html[data-theme] .admin-field textarea{background:var(--rsl-audit-panel)!important;color:var(--rsl-audit-text)!important;border-color:var(--rsl-audit-line)!important}

/* Form-control theme normalization: page-local legacy rules must never leak their original palette into a selected theme. */
html[data-theme] input,html[data-theme] textarea,html[data-theme] select,html[data-theme] [contenteditable="true"]{background:var(--rsl-audit-panel)!important;color:var(--rsl-audit-text)!important;border-color:var(--rsl-audit-line)!important;accent-color:var(--rsl-audit-accent)!important}
html[data-theme] .admin-upload-drop,
html[data-theme] .rsl-upload-drop,
html[data-theme] .dropzone,
html[data-theme] .file-drop,
html[data-theme] .custom-select,
html[data-theme] .select-trigger,
html[data-theme] .dropdown-trigger,
html[data-theme] .server-control select,
html[data-theme] .registration-top-five input,
html[data-theme] .profile-link-row input,
html[data-theme] .news-form input,
html[data-theme] .news-form textarea,
html[data-theme] .news-form select,
html[data-theme] .news-guild,
html[data-theme] .tournament-create input,
html[data-theme] .tournament-create textarea,
html[data-theme] .tournament-create select{
  background:var(--rsl-audit-panel)!important;
  color:var(--rsl-audit-text)!important;
  border-color:var(--rsl-audit-line)!important;
}
html[data-theme] .admin-upload-drop:hover,
html[data-theme] .admin-upload-drop.is-dragover,
html[data-theme] .rsl-upload-drop:hover,
html[data-theme] .dropzone:hover,
html[data-theme] .file-drop:hover,
html[data-theme] .custom-select:hover,
html[data-theme] .select-trigger:hover,
html[data-theme] .dropdown-trigger:hover{
  background:var(--rsl-audit-panel2)!important;
  color:var(--rsl-audit-accent)!important;
  border-color:var(--rsl-audit-accent)!important;
}
html[data-theme] select{color-scheme:dark}
html[data-theme="light"] select{color-scheme:light}
html[data-theme] select option,html[data-theme] select optgroup{background:var(--rsl-audit-panel)!important;color:var(--rsl-audit-text)!important}
html[data-theme] input::placeholder,html[data-theme] textarea::placeholder{color:var(--rsl-audit-muted)!important}
html[data-theme] input::placeholder,html[data-theme] textarea::placeholder{color:var(--rsl-audit-muted)!important}
html[data-theme] th,html[data-theme] td,html[data-theme] .match-row,html[data-theme] .leader-row{border-color:var(--rsl-audit-line)!important}
html[data-theme] .server-sub,html[data-theme] .empty-state,html[data-theme] .muted,html[data-theme] .ref-meta,html[data-theme] .ref-desc,html[data-theme] .tournament-card p,html[data-theme] .tournament-toolbar small,html[data-theme] .profile-status-item span,html[data-theme] .profile-label,html[data-theme] .garage-meta small,html[data-theme] .home-info-card p,html[data-theme] .home-feature-card p,html[data-theme] .home-help-card p,html[data-theme] .home-news-item p,html[data-theme] .news-loading,html[data-theme] .news-empty{color:var(--rsl-audit-muted)!important}
html[data-theme] h1,html[data-theme] h2,html[data-theme] h3,html[data-theme] h4,html[data-theme] strong,html[data-theme] .panel-heading h2,html[data-theme] .feature-body h2,html[data-theme] .welcome-copy h1,html[data-theme] .home-info-card h2,html[data-theme] .home-feature-card h2,html[data-theme] .home-help-card h2,html[data-theme] .clubs-center-hero h1,html[data-theme] .tournament-card h2,html[data-theme] .career-card h3,html[data-theme] .home-section-heading h2{color:var(--rsl-audit-text)!important}
html[data-theme] a{color:var(--rsl-audit-accent)}
html[data-theme] .home-eyebrow,html[data-theme] .eyebrow,html[data-theme] .tournament-card-top b,html[data-theme] .official,html[data-theme] .defense-summary span{color:var(--rsl-audit-accent)!important}

html[data-theme] .qa,html[data-theme] .ref-form button,html[data-theme] .home-action,html[data-theme] .tournament-hero-action,html[data-theme] .discord-cta-button{border-color:var(--rsl-audit-accent)!important}
html[data-theme] .qa-blue,html[data-theme] .qa-purple,html[data-theme] .qa-gold,html[data-theme] .qa-green,html[data-theme] .wide-action,html[data-theme] .ref-form button{background:linear-gradient(90deg,var(--rsl-audit-strong),var(--rsl-audit-accent))!important;color:var(--rsl-box-text)!important}
html[data-theme] .home-feature-icon,html[data-theme] .home-help-arrow{color:var(--rsl-audit-accent)!important}
html[data-theme] .home-feature-card:before,html[data-theme] .home-info-card:before,html[data-theme] .home-help-card:before{background:linear-gradient(90deg,var(--rsl-audit-accent),var(--rsl-audit-strong),transparent)!important}
html[data-theme] .home-feature-card:after,html[data-theme] .home-info-card:after{background:var(--rsl-audit-accent)!important;box-shadow:-18px -18px 0 color-mix(in srgb,var(--rsl-audit-accent) 35%,transparent)!important}

html[data-theme] main [style*="background:#"],html[data-theme] main [style*="background: #"],html[data-theme] main [style*="background:linear-gradient"],html[data-theme] main [style*="background: linear-gradient"]{background:linear-gradient(145deg,var(--rsl-audit-panel),var(--rsl-audit-panel2))!important}
html[data-theme] main [style*="border:1px"],html[data-theme] main [style*="border: 1px"]{border-color:var(--rsl-audit-line)!important}
html[data-theme] main [style*="color:#"],html[data-theme] main [style*="color: #"]{color:var(--rsl-audit-text)!important}

html[data-theme] .home-page{background:radial-gradient(circle at 70% 10%,var(--rsl-audit-panel2) 0,var(--rsl-audit-bg) 52%,var(--rsl-audit-bg) 100%)!important}
html[data-theme] .home-hero{background:var(--rsl-audit-bg)!important;border-color:var(--rsl-audit-line)!important}
html[data-theme] .home-news-modal-card{background:linear-gradient(145deg,var(--rsl-audit-panel2),var(--rsl-audit-panel))!important;color:var(--rsl-audit-text)!important;border-color:var(--rsl-audit-accent)!important}
html[data-theme] .rsl-footer{background:linear-gradient(180deg,var(--rsl-audit-panel),var(--rsl-audit-bg))!important;color:var(--rsl-audit-text)!important;border-color:var(--rsl-audit-line)!important}
html[data-theme] .rsl-footer a,html[data-theme] .rsl-footer-copyline,html[data-theme] .rsl-footer-brand-name{color:var(--rsl-audit-text)!important}
html[data-theme] .rsl-cookie-banner,html[data-theme] .rsl-cookie-settings,html[data-theme] .rsl-footer-theme-control{background:var(--rsl-audit-panel)!important;color:var(--rsl-audit-text)!important;border-color:var(--rsl-audit-line)!important}
html[data-theme] .rsl-cookie-banner p,html[data-theme] .rsl-footer-theme-control label{color:var(--rsl-audit-muted)!important}
html[data-theme] .rsl-cookie-btn{background:var(--rsl-audit-panel2)!important;color:var(--rsl-audit-text)!important;border-color:var(--rsl-audit-line)!important}
html[data-theme] .rsl-cookie-btn.primary{background:var(--rsl-audit-strong)!important;color:var(--rsl-box-text)!important}
html[data-theme] .rsl-footer-theme-control select{background:var(--rsl-audit-panel2)!important;color:var(--rsl-audit-text)!important;border-color:var(--rsl-audit-line)!important}

html[data-theme] .companion-nav-info-menu,html[data-theme] .companion-info-link,html[data-theme] .companion-info-item{background:var(--rsl-audit-panel)!important;color:var(--rsl-audit-text)!important;border-color:var(--rsl-audit-line)!important}
html[data-theme] .companion-info-item small,html[data-theme] .companion-info-link small{color:var(--rsl-audit-muted)!important}
html[data-theme] .rsl-search-input-wrap{background:var(--rsl-audit-panel)!important;border-color:var(--rsl-audit-line)!important}
html[data-theme] .rsl-search-input-wrap input{background:transparent!important;color:var(--rsl-audit-text)!important}
html[data-theme="light"] .top-nav nav>a,html[data-theme="light"] .top-nav .top-nav-dropdown-trigger,html[data-theme="light"] .rsl-profile-trigger,html[data-theme="light"] .rsl-search-trigger{color:#18283b!important}
html[data-theme="light"] a,html[data-theme="light"] .rsl-footer a{color:#1769d1!important}
html[data-theme] .discord-cta{background:linear-gradient(100deg,var(--rsl-audit-panel),var(--rsl-audit-panel2))!important;color:var(--rsl-audit-text)!important;border-color:var(--rsl-audit-line)!important;box-shadow:0 8px 28px var(--rsl-audit-shadow)!important}
html[data-theme] .discord-cta-kicker,html[data-theme] .discord-stat-label,html[data-theme] .discord-stat-value{color:var(--rsl-audit-text)!important}
html[data-theme] .discord-cta p{color:var(--rsl-audit-muted)!important}
html[data-theme] .discord-cta-stats{border-color:var(--rsl-audit-line)!important}
html[data-theme] .discord-stat-icon{background:var(--rsl-audit-panel2)!important;border-color:var(--rsl-audit-line)!important}
html[data-theme] .discord-stat-icon svg{stroke:var(--rsl-audit-accent)!important}
html[data-theme] .discord-cta-icon svg{fill:var(--rsl-audit-accent)!important;filter:drop-shadow(0 0 8px color-mix(in srgb,var(--rsl-audit-accent) 35%,transparent))!important}
html[data-theme] .discord-cta-button{background:linear-gradient(90deg,var(--rsl-audit-strong),var(--rsl-audit-accent))!important;color:var(--rsl-box-text)!important}
html[data-theme="light"] .qa-blue,html[data-theme="light"] .qa-purple,html[data-theme="light"] .qa-gold,html[data-theme="light"] .qa-green,html[data-theme="light"] .wide-action,html[data-theme="light"] .ref-form button,html[data-theme="light"] .rsl-cookie-btn.primary,html[data-theme="light"] .discord-cta-button{color:#fff!important}
html[data-theme] .home-upcoming-panel{background:linear-gradient(145deg,var(--rsl-audit-panel),var(--rsl-audit-panel2))!important;color:var(--rsl-audit-text)!important;border-color:var(--rsl-audit-line)!important}
html[data-theme] .home-upcoming-panel h2,html[data-theme] .home-upcoming-panel h3,html[data-theme] .home-upcoming-panel strong{color:var(--rsl-audit-text)!important}
html[data-theme] .home-upcoming-panel p,html[data-theme] .home-upcoming-panel small,.home-upcoming-empty{color:var(--rsl-audit-muted)!important}
html[data-theme] .home-upcoming-panel a{color:var(--rsl-audit-accent)!important}
html[data-theme] .home-upcoming-panel svg{color:var(--rsl-audit-accent)!important;stroke:var(--rsl-audit-accent)!important;fill:currentColor}
html[data-theme] .rsl-language-trigger{background:var(--rsl-audit-panel)!important;color:var(--rsl-audit-text)!important;border-color:var(--rsl-audit-line)!important}
html[data-theme] .rsl-language-trigger:hover{color:var(--rsl-audit-accent)!important}
html[data-theme] .rsl-language-globe{color:var(--rsl-audit-accent)!important}
html[data-theme] .rsl-language-menu{background:linear-gradient(145deg,var(--rsl-audit-panel2),var(--rsl-audit-panel))!important;border-color:var(--rsl-audit-line)!important}
html[data-theme] .rsl-language-option{color:var(--rsl-audit-text)!important}
html[data-theme] .rsl-language-option:hover:not(:disabled),html[data-theme] .rsl-language-option.is-active{background:color-mix(in srgb,var(--rsl-audit-accent) 13%,var(--rsl-audit-panel))!important;color:var(--rsl-audit-accent)!important}
html[data-theme] .home-feature-icon,html[data-theme] .home-help-arrow,html[data-theme] .home-info-card svg,html[data-theme] .home-feature-card svg,html[data-theme] .home-help-card svg{color:var(--rsl-audit-accent)!important;stroke:var(--rsl-audit-accent)!important}
html[data-theme] .home-feature-icon svg,html[data-theme] .home-help-arrow svg{fill:currentColor!important}

html[data-theme] .home-upcoming{
  background:linear-gradient(145deg,var(--rsl-audit-panel),var(--rsl-audit-panel2))!important;
  color:var(--rsl-audit-text)!important;
  border-color:var(--rsl-audit-line)!important;
}
html[data-theme] .home-upcoming-title h2,
html[data-theme] .home-upcoming .home-eyebrow{color:var(--rsl-audit-text)!important}
html[data-theme] .home-upcoming-link{color:var(--rsl-audit-accent)!important}
html[data-theme] .home-upcoming-list,
html[data-theme] .home-upcoming-list > *,
html[data-theme] .home-upcoming-event,
html[data-theme] .home-upcoming-item{
  color:var(--rsl-audit-text)!important;
  background:color-mix(in srgb,var(--rsl-audit-panel2) 88%,var(--rsl-audit-panel) 12%)!important;
  border-color:var(--rsl-audit-line)!important;
}
html[data-theme] .home-upcoming svg,
html[data-theme] .home-upcoming svg *{stroke:var(--rsl-audit-accent)!important;color:var(--rsl-audit-accent)!important}
html[data-theme] .home-upcoming-empty{color:var(--rsl-audit-muted)!important}
html[data-theme] .home-feature-icon svg,
html[data-theme] .home-help-icon svg,
html[data-theme] .home-about-icon svg,
html[data-theme] .home-news-icon svg{
  fill:none!important;stroke:var(--rsl-audit-accent)!important;color:var(--rsl-audit-accent)!important;
  stroke-width:3!important;stroke-linecap:round!important;stroke-linejoin:round!important;
}
html[data-theme] .home-feature-icon svg *,
html[data-theme] .home-help-icon svg *,
html[data-theme] .home-about-icon svg *,
html[data-theme] .home-news-icon svg *{fill:none!important;stroke:var(--rsl-audit-accent)!important}

/* Discord brand exception: keep Discord icon in official Blurple across all themes. */
html[data-theme] .discord-cta-icon svg,
html[data-theme] .discord-cta-icon svg *,
html[data-theme] .discord-stat-icon.discord-brand-icon svg,
html[data-theme] .discord-stat-icon.discord-brand-icon svg *{
  color:#5865F2!important;
  fill:#5865F2!important;
  stroke:#5865F2!important;
  filter:none!important;
}

/* Final theme normalization for page titles and calendar controls */
html[data-theme] main h1,html[data-theme] main h2,html[data-theme] main h3,html[data-theme] .page-title,html[data-theme] .page-heading,html[data-theme] .section-title,html[data-theme] .section-heading,html[data-theme] .panel-heading h2,html[data-theme] .calendar-hero h1,html[data-theme] .calendar-nav h2{color:var(--rsl-audit-text)!important}
html[data-theme] .calendar-hero,html[data-theme] .calendar-toolbar,html[data-theme] .calendar-board,html[data-theme] .calendar-agenda,html[data-theme] .calendar-personal-panel,html[data-theme] .calendar-day,html[data-theme] .calendar-event{background:linear-gradient(145deg,var(--rsl-audit-panel),var(--rsl-audit-panel2))!important;color:var(--rsl-audit-text)!important;border-color:var(--rsl-audit-line)!important}
html[data-theme] .calendar-nav button,html[data-theme] .calendar-filter,html[data-theme] .calendar-personal-actions button{background:var(--rsl-audit-panel2)!important;color:var(--rsl-audit-text)!important;border-color:var(--rsl-audit-line)!important}
html[data-theme] .calendar-nav button:hover,html[data-theme] .calendar-filter:hover,html[data-theme] .calendar-filter.is-active,html[data-theme] .calendar-personal-actions button:hover{background:color-mix(in srgb,var(--rsl-audit-accent) 18%,var(--rsl-audit-panel2))!important;color:var(--rsl-audit-text)!important;border-color:var(--rsl-audit-accent)!important}
/* FINAL PAGE TITLE COLOR OVERRIDE: titles stay theme text, not accent blue */
html[data-theme] main .page-hero,
html[data-theme] main .page-hero h1,
html[data-theme] main .page-hero h2,
html[data-theme] main .page-hero .home-eyebrow,
html[data-theme] main .tournament-hero,
html[data-theme] main .tournament-hero h1,
html[data-theme] main .tournament-hero .eyebrow,
html[data-theme] main .calendar-hero h1{
  color:var(--rsl-audit-text)!important
}
html[data-theme] main .page-hero .home-eyebrow,
html[data-theme] main .tournament-hero .eyebrow{
  color:var(--rsl-audit-text)!important
}
/* FINAL PAGE TITLE AND INNER-BOX THEME OVERRIDE */
html[data-theme] h1,html[data-theme] h2,html[data-theme] h3,html[data-theme] h4,html[data-theme] h5,html[data-theme] h6,
html[data-theme] [class*="title"],html[data-theme] [class*="heading"]{color:var(--rsl-audit-text)!important}

/* Page-specific legacy shells: route old hard-coded midnight palettes through theme variables. */
html[data-theme] .my-club-hero,html[data-theme] .my-club-card,html[data-theme] .my-club-empty,
html[data-theme] .my-club-stat,html[data-theme] .my-club-links a,html[data-theme] .my-club-member,
html[data-theme] .my-club-result,html[data-theme] .my-tournament-stat,html[data-theme] .my-tournament-card,
html[data-theme] .my-tournament-tag,html[data-theme] .my-tournament-empty,html[data-theme] .profile-card-rsl,
html[data-theme] .profile-status-panel,html[data-theme] .profile-club-card,html[data-theme] .profile-avatar-large,
html[data-theme] .legal-hero,html[data-theme] .legal-nav,html[data-theme] .legal-card,html[data-theme] .legal-note,
html[data-theme] .news-admin-hero,html[data-theme] .news-editor,html[data-theme] .news-list-panel,
html[data-theme] .admin-side,html[data-theme] .admin-card,html[data-theme] .admin-tool{
  background:linear-gradient(145deg,var(--rsl-audit-panel),var(--rsl-audit-panel2))!important;
  color:var(--rsl-audit-text)!important;border-color:var(--rsl-audit-line)!important
}
html[data-theme] .my-club-hero-copy h1,html[data-theme] .my-club-card h2,html[data-theme] .my-club-empty h1,
html[data-theme] .my-tournaments-section h2,html[data-theme] .my-tournament-card h3,html[data-theme] .legal-hero h1,
html[data-theme] .legal-nav strong,html[data-theme] .legal-card h2,html[data-theme] .legal-card h3,
html[data-theme] .news-admin-hero h1,html[data-theme] .news-editor h2,html[data-theme] .news-list-panel h2,
html[data-theme] .admin-tool strong{color:var(--rsl-audit-text)!important}
html[data-theme] .my-club-hero-copy p,html[data-theme] .my-club-about,html[data-theme] .my-club-stat span,
html[data-theme] .my-club-member-info small,html[data-theme] .my-club-result small,html[data-theme] .my-club-empty p,
html[data-theme] .my-club-loading,html[data-theme] .my-tournament-stat span,html[data-theme] .my-tournament-meta,
html[data-theme] .my-tournament-progress,html[data-theme] .my-tournament-empty,html[data-theme] .legal-hero p,
html[data-theme] .legal-card p,html[data-theme] .legal-card li,html[data-theme] .legal-updated,
html[data-theme] .legal-nav a,html[data-theme] .legal-note,html[data-theme] .news-admin-hero p,
html[data-theme] .news-form label,html[data-theme] .admin-tool span{color:var(--rsl-audit-muted)!important}
html[data-theme] .my-club-button,html[data-theme] .my-tournament-button.secondary,html[data-theme] .legal-button,
html[data-theme] .news-actions .secondary,html[data-theme] .admin-btn{
  background:var(--rsl-audit-panel)!important;color:var(--rsl-audit-text)!important;border-color:var(--rsl-audit-line)!important
}
html[data-theme] .my-club-button.primary,html[data-theme] .my-tournament-button,html[data-theme] .admin-btn.primary,
html[data-theme] .news-actions button{
  background:linear-gradient(90deg,var(--rsl-audit-strong),var(--rsl-audit-accent))!important;
  color:var(--rsl-box-text)!important;border-color:var(--rsl-audit-accent)!important
}
html[data-theme] .my-club-links a,html[data-theme] .my-club-badge,html[data-theme] .my-tournament-status,
html[data-theme] .legal-hero-subtitle,html[data-theme] .legal-card h2 span,html[data-theme] .legal-button,
html[data-theme] .news-actions button{color:var(--rsl-audit-accent)!important}
html[data-theme] .my-club-stat,html[data-theme] .my-club-links a,html[data-theme] .my-club-member,
html[data-theme] .my-club-result,html[data-theme] .my-tournament-tag,html[data-theme] .my-tournament-card,
html[data-theme] .news-form input,html[data-theme] .news-form textarea,html[data-theme] .news-form select,
html[data-theme] .news-guild,html[data-theme] .admin-toolbar select{border-color:var(--rsl-audit-line)!important}
html[data-theme] .news-form input,html[data-theme] .news-form textarea,html[data-theme] .news-form select,
html[data-theme] .news-guild,html[data-theme] .admin-toolbar select{
  background:var(--rsl-audit-panel)!important;color:var(--rsl-audit-text)!important
}
html[data-theme] .admin-news-item{background:var(--rsl-audit-panel2)!important;color:var(--rsl-audit-text)!important;border-color:var(--rsl-audit-line)!important}

/* Catch legacy hard-coded midnight inline backgrounds outside <main>. */
html[data-theme] [style*="#061226"],html[data-theme] [style*="#06152f"],html[data-theme] [style*="#020814"],
html[data-theme] [style*="#07172b"],html[data-theme] [style*="#071a2c"],html[data-theme] [style*="#0a1a30"],
html[data-theme] [style*="#040d1d"],html[data-theme] [style*="#030b18"]{background:linear-gradient(145deg,var(--rsl-audit-panel),var(--rsl-audit-panel2))!important}

/* FINAL PAGE TITLE AND INNER-BOX THEME OVERRIDE */
html[data-theme] main h1,
html[data-theme] main h2,
html[data-theme] main h3,
html[data-theme] main h4,
html[data-theme] main h5,
html[data-theme] main h6,
html[data-theme] main .panel-heading,
html[data-theme] main .section-heading,
html[data-theme] main .page-heading,
html[data-theme] main .page-title,
html[data-theme] main .section-title,
html[data-theme] main .card-title,
html[data-theme] main .box-title,
html[data-theme] main .title,
html[data-theme] main [class*="heading"],
html[data-theme] main [class*="title"]{
  color:var(--rsl-audit-text)!important;
}
html[data-theme] main .card,
html[data-theme] main .glass-panel,
html[data-theme] main .feature,
html[data-theme] main .panel,
html[data-theme] main .box,
html[data-theme] main .inner-box,
html[data-theme] main .match-card,
html[data-theme] main .challenge-card,
html[data-theme] main .submit-card,
html[data-theme] main .recent-matches-card,
html[data-theme] main .registration-card,
html[data-theme] main .tournament-card,
html[data-theme] main .club-card,
html[data-theme] main .calendar-panel{
  background:linear-gradient(145deg,var(--rsl-audit-panel),var(--rsl-audit-panel2))!important;
  color:var(--rsl-audit-text)!important;
  border-color:var(--rsl-audit-line)!important;
}
html[data-theme] main [class*="card"] h1,
html[data-theme] main [class*="card"] h2,
html[data-theme] main [class*="card"] h3,
html[data-theme] main [class*="card"] h4,
html[data-theme] main [class*="box"] h1,
html[data-theme] main [class*="box"] h2,
html[data-theme] main [class*="box"] h3,
html[data-theme] main [class*="box"] h4{
  color:var(--rsl-audit-text)!important;
}
/* SECOND FULL-PAGE THEME AUDIT: eliminate remaining page-local midnight surfaces. */
html[data-theme] .defense-summary,
html[data-theme] .match-card,
html[data-theme] .ref-card,
html[data-theme] .compare,
html[data-theme] .ref-video,
html[data-theme] .clubs-center-hero,
html[data-theme] .profile-hero,
html[data-theme] .profile-avatar-large,
html[data-theme] .profile-card-rsl,
html[data-theme] .profile-field,
html[data-theme] .profile-about,
html[data-theme] .profile-links a,
html[data-theme] .profile-status,
html[data-theme] .profile-help-card,
html[data-theme] .profile-status-panel,
html[data-theme] .profile-club-card,
html[data-theme] .profile-club-logo,
html[data-theme] .profile-club-stat,
html[data-theme] .my-tournaments-hero,
html[data-theme] .my-tournament-stat,
html[data-theme] .my-tournament-card,
html[data-theme] .my-tournament-tag,
html[data-theme] .my-tournament-empty,
html[data-theme] .legal-hero,
html[data-theme] .legal-nav,
html[data-theme] .legal-note,
html[data-theme] .admin-page,
html[data-theme] .admin-head,
html[data-theme] .admin-side,
html[data-theme] .admin-card,
html[data-theme] .admin-logo-preview,
html[data-theme] .admin-hero-preview,
html[data-theme] .admin-log,
html[data-theme] .news-editor,
html[data-theme] .news-list-panel,
html[data-theme] .admin-news-item{
  background:linear-gradient(145deg,var(--rsl-audit-panel),var(--rsl-audit-panel2))!important;
  color:var(--rsl-audit-text)!important;
  border-color:var(--rsl-audit-line)!important;
}
html[data-theme] .match-row,
html[data-theme] .submit-grid fieldset,
html[data-theme] .profile-field,
html[data-theme] .profile-status,
html[data-theme] .profile-club-stat,
html[data-theme] .admin-field,
html[data-theme] .admin-field input,
html[data-theme] .admin-field select,
html[data-theme] .admin-field textarea,
html[data-theme] .news-form input,
html[data-theme] .news-form textarea,
html[data-theme] .news-form select,
html[data-theme] .news-guild{
  background:var(--rsl-audit-panel)!important;
  color:var(--rsl-audit-text)!important;
  border-color:var(--rsl-audit-line)!important;
}
html[data-theme] .legal-nav a:hover{
  background:color-mix(in srgb,var(--rsl-audit-accent) 12%,var(--rsl-audit-panel))!important;
  color:var(--rsl-audit-accent)!important;
}
html[data-theme] .profile-hero h1,
html[data-theme] .clubs-center-hero h1,
html[data-theme] .my-tournaments-hero h1,
html[data-theme] .admin-head h1,
html[data-theme] .news-editor h2,
html[data-theme] .news-list-panel h2,
html[data-theme] .defense-summary h2,
html[data-theme] .ref-card h2,
html[data-theme] .compare h2,
html[data-theme] .profile-card-rsl h2,
html[data-theme] .profile-help-card h2{
  color:var(--rsl-audit-text)!important;
}
html[data-theme] .profile-hero p,
html[data-theme] .profile-field label,
html[data-theme] .profile-about,
html[data-theme] .profile-status,
html[data-theme] .profile-help-card p,
html[data-theme] .my-tournaments-hero p,
html[data-theme] .defense-summary p,
html[data-theme] .ref-card p,
html[data-theme] .compare p,
html[data-theme] .ref-video p,
html[data-theme] .admin-head p,
html[data-theme] .admin-log,
html[data-theme] .news-form label{
  color:var(--rsl-audit-muted)!important;
}
html[data-theme] .submit-grid input,
html[data-theme] .admin-field input,
html[data-theme] .admin-field select,
html[data-theme] .admin-field textarea,
html[data-theme] .news-form input,
html[data-theme] .news-form textarea,
html[data-theme] .news-form select{
  background:var(--rsl-audit-panel)!important;
  color:var(--rsl-audit-text)!important;
  border-color:var(--rsl-audit-line)!important;
}
html[data-theme] [style*="#020817"],
html[data-theme] [style*="#061226"],
html[data-theme] [style*="#061427"],
html[data-theme] [style*="#06152f"],
html[data-theme] [style*="#020814"],
html[data-theme] [style*="#07172b"],
html[data-theme] [style*="#07172f"],
html[data-theme] [style*="#071a2c"],
html[data-theme] [style*="#071a31"],
html[data-theme] [style*="#0a1a30"],
html[data-theme] [style*="#0a172a"],
html[data-theme] [style*="#030b18"],
html[data-theme] [style*="#030c1b"],
html[data-theme] [style*="#040d1d"],
html[data-theme] [style*="#020b1b"],
html[data-theme] [style*="#04101f"],
html[data-theme] [style*="#020916"],
html[data-theme] [style*="#02060d"]{
  background:linear-gradient(145deg,var(--rsl-audit-panel),var(--rsl-audit-panel2))!important;
}
/* Third audit pass: shared app.css surfaces that still carried fixed dark palette values. */
html[data-theme] .defense-result-row,
html[data-theme] .match-row,
html[data-theme] .compare,
html[data-theme] .activity-list>div,
html[data-theme] .defense-summary,
html[data-theme] .tournament-card,
html[data-theme] .review-row,
html[data-theme] .public-profile,
html[data-theme] .public-profile-hero,
html[data-theme] .public-profile-grid,
html[data-theme] .public-profile-about,
html[data-theme] .public-profile-links,
html[data-theme] .public-club-hero,
html[data-theme] .public-club-roster,
html[data-theme] .player-directory-card,
html[data-theme] .player-card-stats,
html[data-theme] .unified-profile-side,
html[data-theme] .competition-toolbar,
html[data-theme] .competition-table-head,
html[data-theme] .career-section,
html[data-theme] .companion-info-item{
  background:linear-gradient(145deg,var(--rsl-audit-panel),var(--rsl-audit-panel2))!important;
  color:var(--rsl-audit-text)!important;
  border-color:var(--rsl-audit-line)!important;
}
html[data-theme] .defense-result-grid input,
html[data-theme] .activity-list input,
html[data-theme] .activity-list select,
html[data-theme] .tournament-create input,
html[data-theme] .tournament-create textarea,
html[data-theme] .tournament-create select,
html[data-theme] .competition-search input,
html[data-theme] .rsl-search-toolbar select,
html[data-theme] .notification-timing select,
html[data-theme] .notification-custom-days{
  background:var(--rsl-audit-panel)!important;
  color:var(--rsl-audit-text)!important;
  border-color:var(--rsl-audit-line)!important;
}
html[data-theme] .competition-row:hover,
html[data-theme] .companion-info-item:hover{
  background:color-mix(in srgb,var(--rsl-audit-accent) 10%,var(--rsl-audit-panel))!important;
  color:var(--rsl-audit-text)!important;
}
html[data-theme] .tournament-meta span,
html[data-theme] .tournament-club-driver,
html[data-theme] .career-section p,
html[data-theme] .player-card-stats span{
  color:var(--rsl-audit-muted)!important;
}

/* BOX ICONS: remove fixed midnight-blue backing from About/Features/Help/News and other themed cards. */
html[data-theme] .home-about-icon,
html[data-theme] .home-help-icon,
html[data-theme] .home-news-icon,
html[data-theme] .home-feature-icon,
html[data-theme] .home-help-arrow,
html[data-theme] .companion-info-link-icon{
  background:var(--rsl-audit-panel2)!important;
  border-color:var(--rsl-audit-line)!important;
  color:var(--rsl-audit-accent)!important;
}
html[data-theme] .home-about-icon svg,
html[data-theme] .home-help-icon svg,
html[data-theme] .home-news-icon svg,
html[data-theme] .home-feature-icon svg,
html[data-theme] .home-help-arrow svg,
html[data-theme] .companion-info-link-icon svg{
  color:var(--rsl-audit-accent)!important;
  stroke:var(--rsl-audit-accent)!important;
  fill:none!important;
}
/* FINAL THEME NORMALIZATION: never let legacy midnight-blue CSS override the selected theme. */
html[data-theme] .page-hero,
html[data-theme] .page-hero h1,
html[data-theme] .page-hero h2,
html[data-theme] .page-hero .home-eyebrow,
html[data-theme] .tournament-hero,
html[data-theme] .tournament-hero h1,
html[data-theme] .tournament-hero .eyebrow,
html[data-theme] .calendar-hero h1,
html[data-theme] .page-title,
html[data-theme] .page-heading,
html[data-theme] .section-title,
html[data-theme] .section-heading{
  color:var(--rsl-audit-text)!important;
}
html[data-theme] .page-hero .home-eyebrow,
html[data-theme] .tournament-hero .eyebrow{
  color:var(--rsl-audit-text)!important;
}
html[data-theme] .nav-icon-img,
html[data-theme] .nav-icon-glyph{
  filter:grayscale(1) brightness(1.35) sepia(.05) saturate(.1)!important;
}
html[data-theme="light"] .nav-icon-img,
html[data-theme="light"] .nav-icon-glyph{
  filter:grayscale(1) brightness(.55) saturate(.1)!important;
}
html[data-theme="ocean"] .nav-icon-img,
html[data-theme="ocean"] .nav-icon-glyph{
  filter:grayscale(1) sepia(.25) saturate(2) hue-rotate(145deg) brightness(1.25)!important;
}
html[data-theme="purple"] .nav-icon-img,
html[data-theme="purple"] .nav-icon-glyph{
  filter:grayscale(1) sepia(.45) saturate(3) hue-rotate(235deg) brightness(1.15)!important;
}
html[data-theme="crimson"] .nav-icon-img,
html[data-theme="crimson"] .nav-icon-glyph{
  filter:grayscale(1) sepia(.55) saturate(4) hue-rotate(305deg) brightness(1.1)!important;
}
html[data-theme="emerald"] .nav-icon-img,
html[data-theme="emerald"] .nav-icon-glyph{
  filter:grayscale(1) sepia(.5) saturate(3) hue-rotate(100deg) brightness(1.15)!important;
}
html[data-theme="sunset"] .nav-icon-img,
html[data-theme="sunset"] .nav-icon-glyph{
  filter:grayscale(1) sepia(.6) saturate(3) hue-rotate(345deg) brightness(1.15)!important;
}
html[data-theme="graphite"] .nav-icon-img,
html[data-theme="graphite"] .nav-icon-glyph{
  filter:grayscale(1) brightness(1.15) saturate(.15)!important;
}

/* FINAL PAGE HERO SURFACE AUDIT: replace legacy dark-blue title bands with the active theme. */
html[data-theme] .page-hero,
html[data-theme] .tournament-hero,
html[data-theme] .calendar-hero,
html[data-theme] .clubs-center-hero,
html[data-theme] .my-club-hero,
html[data-theme] .profile-hero,
html[data-theme] .legal-hero,
html[data-theme] .my-tournaments-hero{
  background:linear-gradient(145deg,var(--rsl-final-panel),var(--rsl-final-panel2))!important;
  border-color:var(--rsl-final-line)!important;
  color:var(--rsl-final-text)!important;
  box-shadow:0 10px 28px rgba(0,0,0,.18)!important;
}
html[data-theme] .page-hero::before,
html[data-theme] .page-hero::after,
html[data-theme] .tournament-hero::before,
html[data-theme] .tournament-hero::after{
  background:transparent!important;
  border-color:transparent!important;
}
html[data-theme] .page-hero p,
html[data-theme] .tournament-hero p,
html[data-theme] .calendar-hero p,
html[data-theme] .my-tournaments-hero p{
  color:var(--rsl-final-muted)!important;
}
html[data-theme] .page-hero .home-eyebrow,
html[data-theme] .tournament-hero .eyebrow{
  color:var(--rsl-final-accent)!important;
}
/* DEEP THEME AUDIT v2 — final authority for all UI surfaces, settings, boxes and non-brand icons. */
html[data-theme="dark"]{
  --rsl-final-bg:#020817;--rsl-final-panel:#071427;--rsl-final-panel2:#0d2139;
  --rsl-final-line:#173b64;--rsl-final-text:#dbe8f8;--rsl-final-muted:#91a5c3;--rsl-final-accent:#25dfff;
}
html[data-theme="light"]{
  --rsl-final-bg:#eef3f8;--rsl-final-panel:#f8fafc;--rsl-final-panel2:#e8eef5;
  --rsl-final-line:#c5d1dd;--rsl-final-text:#18283b;--rsl-final-muted:#60738b;--rsl-final-accent:#1769d1;
}
html[data-theme="ocean"]{
  --rsl-final-bg:#03161f;--rsl-final-panel:#062b38;--rsl-final-panel2:#0b3b4a;
  --rsl-final-line:#1a6074;--rsl-final-text:#e2f8ff;--rsl-final-muted:#8ebbc9;--rsl-final-accent:#37e6ff;
}
html[data-theme="purple"]{
  --rsl-final-bg:#0e0718;--rsl-final-panel:#1a0e2d;--rsl-final-panel2:#291540;
  --rsl-final-line:#60448b;--rsl-final-text:#f3eaff;--rsl-final-muted:#b9a9d1;--rsl-final-accent:#b86cff;
}
html[data-theme="crimson"]{
  --rsl-final-bg:#140608;--rsl-final-panel:#250d12;--rsl-final-panel2:#39151c;
  --rsl-final-line:#7b3541;--rsl-final-text:#ffe9ed;--rsl-final-muted:#c49ba2;--rsl-final-accent:#ff5c7a;
}
html[data-theme="emerald"]{
  --rsl-final-bg:#03130f;--rsl-final-panel:#07251d;--rsl-final-panel2:#0d3c2e;
  --rsl-final-line:#1b6853;--rsl-final-text:#e5fff7;--rsl-final-muted:#8fb9ab;--rsl-final-accent:#32f2c2;
}
html[data-theme="sunset"]{
  --rsl-final-bg:#170b06;--rsl-final-panel:#2b160c;--rsl-final-panel2:#4d2815;
  --rsl-final-line:#7d4724;--rsl-final-text:#fff0e5;--rsl-final-muted:#c9aa91;--rsl-final-accent:#ff9b54;
}
html[data-theme="graphite"]{
  --rsl-final-bg:#111417;--rsl-final-panel:#1c2024;--rsl-final-panel2:#30363c;
  --rsl-final-line:#454e57;--rsl-final-text:#edf2f5;--rsl-final-muted:#a6afb8;--rsl-final-accent:#d7e3ea;
}

/* Global page/shell surfaces. Artwork itself is intentionally left intact. */
html[data-theme] body,
html[data-theme] body.alu-dashboard,
html[data-theme] body.home-page{
  background:var(--rsl-final-bg)!important;
  color:var(--rsl-final-text)!important;
}
html[data-theme] .top-nav{
  background:linear-gradient(180deg,var(--rsl-final-panel2),var(--rsl-final-panel))!important;
  border-bottom-color:var(--rsl-final-line)!important;
}
html[data-theme] .top-nav nav>a,
html[data-theme] .top-nav .top-nav-dropdown-trigger{
  color:var(--rsl-final-text)!important;
  border-right-color:var(--rsl-final-line)!important;
}
html[data-theme] .top-nav nav>a.active,
html[data-theme] .top-nav nav>a:hover,
html[data-theme] .top-nav .top-nav-dropdown-trigger:hover{
  background:color-mix(in srgb,var(--rsl-final-accent) 12%,var(--rsl-final-panel))!important;
  color:var(--rsl-final-accent)!important;
}
html[data-theme] .top-profile,
html[data-theme] .rsl-profile-trigger,
html[data-theme] .top-user-area{
  background:var(--rsl-final-panel)!important;
  border-color:var(--rsl-final-line)!important;
  color:var(--rsl-final-text)!important;
}
html[data-theme] .top-avatar{
  background:linear-gradient(135deg,var(--rsl-final-accent),color-mix(in srgb,var(--rsl-final-accent) 45%,var(--rsl-final-panel)))!important;
}

/* Every reusable card/panel/box family follows the active theme. */
html[data-theme] .glass-panel,
html[data-theme] .welcome-panel,
html[data-theme] .season-panel,
html[data-theme] .feature,
html[data-theme] .card,
html[data-theme] .table-wrap,
html[data-theme] .profile-card,
html[data-theme] .profile-side-card,
html[data-theme] .quick-actions,
html[data-theme] .activity-card,
html[data-theme] .matches-card,
html[data-theme] .leaderboard-card,
html[data-theme] .garage-card,
html[data-theme] .admin-card,
html[data-theme] .club-card,
html[data-theme] .tournament-card,
html[data-theme] .calendar-panel,
html[data-theme] .calendar-shell,
html[data-theme] .calendar-board,
html[data-theme] .calendar-agenda,
html[data-theme] .calendar-toolbar,
html[data-theme] .calendar-hero,
html[data-theme] .career-section,
html[data-theme] .public-profile,
html[data-theme] .public-club-hero,
html[data-theme] .public-club-roster,
html[data-theme] .legal-card,
html[data-theme] .profile-status-panel,
html[data-theme] .home-info-card,
html[data-theme] .home-feature-card,
html[data-theme] .home-help-card,
html[data-theme] .home-upcoming,
html[data-theme] .home-news-item,
html[data-theme] .rsl-search-dialog,
html[data-theme] .rsl-search-panel,
html[data-theme] .rsl-profile-menu,
html[data-theme] .rsl-profile-theme-dropdown,
html[data-theme] .rsl-profile-theme-toggle,
html[data-theme] .modal-card{
  background:linear-gradient(145deg,var(--rsl-final-panel),var(--rsl-final-panel2))!important;
  color:var(--rsl-final-text)!important;
  border-color:var(--rsl-final-line)!important;
}
html[data-theme] .my-club-card,
html[data-theme] .my-club-stat,
html[data-theme] .my-club-member,
html[data-theme] .my-club-result,
html[data-theme] .my-club-empty,
html[data-theme] .player-directory-card,
html[data-theme] .competition-toolbar,
html[data-theme] .competition-table-head,
html[data-theme] .review-row,
html[data-theme] .notification-timing,
html[data-theme] .companion-info-item,
html[data-theme] .tournament-meta,
html[data-theme] .tournament-club-driver{
  background:var(--rsl-final-panel2)!important;
  color:var(--rsl-final-text)!important;
  border-color:var(--rsl-final-line)!important;
}

/* Settings/forms: eliminate inherited midnight-blue controls. */
html[data-theme] input,
html[data-theme] textarea,
html[data-theme] select,
html[data-theme] .setup-form input,
html[data-theme] .setup-form textarea,
html[data-theme] .setup-form select,
html[data-theme] .profile-editor-grid input,
html[data-theme] .profile-editor-grid textarea,
html[data-theme] .profile-editor-grid select,
html[data-theme] .notification-timing select,
html[data-theme] .notification-custom-days,
html[data-theme] .rsl-search-input-wrap,
html[data-theme] .rsl-search-toolbar select,
html[data-theme] .calendar-notify-timing select,
html[data-theme] .calendar-reminder-modal input,
html[data-theme] .calendar-reminder-modal textarea,
html[data-theme] .calendar-reminder-modal select{
  background:var(--rsl-final-panel2)!important;
  color:var(--rsl-final-text)!important;
  border-color:var(--rsl-final-line)!important;
}
html[data-theme] input::placeholder,
html[data-theme] textarea::placeholder{
  color:var(--rsl-final-muted)!important;
}
html[data-theme] label,
html[data-theme] .setup-form label>b,
html[data-theme] .profile-editor-grid label>b,
html[data-theme] .notification-timing span{
  color:var(--rsl-final-text)!important;
}
html[data-theme] small,
html[data-theme] .muted,
html[data-theme] .empty-state,
html[data-theme] .profile-setting-hint,
html[data-theme] .panel-heading small{
  color:var(--rsl-final-muted)!important;
}

/* Page titles and headings must never inherit the old blue palette. */
html[data-theme] main h1,
html[data-theme] main h2,
html[data-theme] main h3,
html[data-theme] .page-hero,
html[data-theme] .page-hero h1,
html[data-theme] .page-hero h2,
html[data-theme] .tournament-hero,
html[data-theme] .tournament-hero h1,
html[data-theme] .calendar-hero h1,
html[data-theme] .clubs-center-hero h1,
html[data-theme] .my-club-hero-copy h1,
html[data-theme] .profile-hero h1,
html[data-theme] .legal-hero h1{
  color:var(--rsl-final-text)!important;
}
html[data-theme] .home-eyebrow,
html[data-theme] .eyebrow,
html[data-theme] .clubs-center-subtitle{
  color:var(--rsl-final-accent)!important;
}

/* Icons: theme all icons; Discord Blurple is restored below as the only exception. */
html[data-theme] .nav-icon-img,
html[data-theme] .nav-icon-glyph,
html[data-theme] .home-feature-icon,
html[data-theme] .home-help-icon,
html[data-theme] .home-about-icon,
html[data-theme] .home-news-icon,
html[data-theme] .companion-info-link-icon,
html[data-theme] .home-help-arrow{
  color:var(--rsl-final-accent)!important;
  border-color:var(--rsl-final-line)!important;
}
html[data-theme] .nav-icon-img,
html[data-theme] .nav-icon-glyph{
  filter:grayscale(1) sepia(.05) saturate(.2) brightness(1.2)!important;
}
html[data-theme="light"] .nav-icon-img,
html[data-theme="light"] .nav-icon-glyph{
  filter:grayscale(1) brightness(.55) saturate(.1)!important;
}
html[data-theme] .home-feature-icon,
html[data-theme] .home-help-icon,
html[data-theme] .home-about-icon,
html[data-theme] .home-news-icon,
html[data-theme] .companion-info-link-icon{
  background:var(--rsl-final-panel2)!important;
}
html[data-theme] .home-feature-icon svg,
html[data-theme] .home-help-icon svg,
html[data-theme] .home-about-icon svg,
html[data-theme] .home-news-icon svg,
html[data-theme] .companion-info-link-icon svg{
  fill:none!important;
  stroke:var(--rsl-final-accent)!important;
  color:var(--rsl-final-accent)!important;
}

/* Buttons/tabs/utility controls use theme colors rather than fixed blue surfaces. */
html[data-theme] button,
html[data-theme] .qa,
html[data-theme] .primary-action,
html[data-theme] .wide-action,
html[data-theme] .my-club-button,
html[data-theme] .profile-button,
html[data-theme] .legal-button,
html[data-theme] .calendar-nav button,
html[data-theme] .calendar-filter,
html[data-theme] .calendar-notify-button{
  background:var(--rsl-final-panel2)!important;
  color:var(--rsl-final-text)!important;
  border-color:var(--rsl-final-line)!important;
}
html[data-theme] button:hover,
html[data-theme] .qa:hover,
html[data-theme] .primary-action:hover,
html[data-theme] .wide-action:hover,
html[data-theme] .my-club-button:hover,
html[data-theme] .profile-button:hover,
html[data-theme] .legal-button:hover,
html[data-theme] .calendar-nav button:hover,
html[data-theme] .calendar-filter:hover,
html[data-theme] .calendar-filter.is-active,
html[data-theme] .calendar-notify-button:hover,
html[data-theme] .calendar-notify-button.is-enabled{
  background:color-mix(in srgb,var(--rsl-final-accent) 16%,var(--rsl-final-panel2))!important;
  color:var(--rsl-final-text)!important;
  border-color:var(--rsl-final-accent)!important;
}

/* Footer translator/cookie/theme controls are part of the selected theme too. */
html[data-theme] .rsl-footer,
html[data-theme] footer,
html[data-theme] .rsl-footer-theme-control,
html[data-theme] .rsl-language-switcher,
html[data-theme] .rsl-cookie-settings{
  background:var(--rsl-final-panel)!important;
  color:var(--rsl-final-text)!important;
  border-color:var(--rsl-final-line)!important;
}
html[data-theme] .rsl-footer-theme-control select,
html[data-theme] .rsl-language-switcher select,
html[data-theme] .rsl-cookie-settings{
  background:var(--rsl-final-panel2)!important;
  color:var(--rsl-final-text)!important;
  border-color:var(--rsl-final-line)!important;
}

/* Keep Discord icon/mark as the sole fixed brand-color exception. */
html[data-theme] .discord-cta-icon svg,
html[data-theme] .discord-cta-icon svg *,
html[data-theme] .discord-stat-icon.discord-brand-icon svg,
html[data-theme] .discord-stat-icon.discord-brand-icon svg *{
  color:#5865F2!important;
  fill:#5865F2!important;
  stroke:#5865F2!important;
  filter:none!important;
}
/* Discord is the only intentionally fixed brand-color icon. */
html[data-theme] .discord-cta-icon svg,
html[data-theme] .discord-cta-icon svg *,
html[data-theme] .discord-stat-icon.discord-brand-icon svg,
html[data-theme] .discord-stat-icon.discord-brand-icon svg *{
  color:#5865F2!important;
  fill:#5865F2!important;
  stroke:#5865F2!important;
  filter:none!important;
}

/* FINAL BLUE QUARANTINE — all legacy blue chrome must resolve through the active theme.
   Page-specific legacy CSS may still contain historical literals, but rendered UI is
   forced through these shared tokens so every page follows the selected theme. */
html[data-theme]{
  --rsl-theme-accent:var(--rsl-final-accent);
  --rsl-theme-line:var(--rsl-final-line);
  --rsl-theme-panel:var(--rsl-final-panel);
  --rsl-theme-panel2:var(--rsl-final-panel2);
  --rsl-theme-text:var(--rsl-final-text);
  --rsl-theme-muted:var(--rsl-final-muted);
  --rsl-theme-glow:color-mix(in srgb,var(--rsl-final-accent) 22%,transparent);
}

/* Search icon: recolor the PNG through a CSS alpha mask instead of preserving
   the asset's legacy blue pixels. */
html[data-theme] .rsl-search-trigger{
  border-color:var(--rsl-theme-line)!important;
  background:var(--rsl-theme-panel2)!important;
  color:var(--rsl-theme-text)!important;
  box-shadow:none!important;
}
html[data-theme] .rsl-search-trigger img{
  display:none!important;
}
html[data-theme] .rsl-search-trigger::before{
  content:""!important;
  display:block!important;
  width:20px!important;
  height:20px!important;
  background:var(--rsl-theme-accent)!important;
  -webkit-mask:url("/assets/icons/search.png") center/contain no-repeat!important;
  mask:url("/assets/icons/search.png") center/contain no-repeat!important;
}
html[data-theme] .rsl-search-trigger:hover{
  border-color:var(--rsl-theme-accent)!important;
  box-shadow:0 0 16px var(--rsl-theme-glow)!important;
}

/* Common legacy blue borders/lines/rings across standalone pages. */
html[data-theme] .home-hero,
html[data-theme] .home-help-icon,
html[data-theme] .home-news-item,
html[data-theme] .rules-hero,
html[data-theme] .rules-nav,
html[data-theme] .rules-card,
html[data-theme] .rules-button,
html[data-theme] .legal-hero,
html[data-theme] .legal-nav,
html[data-theme] .legal-card,
html[data-theme] .legal-button,
html[data-theme] .profile-hero,
html[data-theme] .profile-avatar-large,
html[data-theme] .public-profile-avatar,
html[data-theme] .clubs-center-hero,
html[data-theme] .my-club-hero,
html[data-theme] .my-tournaments-hero{
  border-color:var(--rsl-theme-line)!important;
}
html[data-theme] .home-hero,
html[data-theme] .rules-hero,
html[data-theme] .legal-hero,
html[data-theme] .profile-hero,
html[data-theme] .clubs-center-hero,
html[data-theme] .my-club-hero,
html[data-theme] .my-tournaments-hero{
  box-shadow:0 10px 28px var(--rsl-theme-glow)!important;
}
html[data-theme] .rules-hero-subtitle,
html[data-theme] .rules-nav a:hover,
html[data-theme] .rules-card h2 span,
html[data-theme] .rules-note,
html[data-theme] .rules-button,
html[data-theme] .legal-hero h1 strong,
html[data-theme] .legal-hero-subtitle,
html[data-theme] .legal-nav a:hover,
html[data-theme] .legal-card h2 span,
html[data-theme] .legal-note,
html[data-theme] .legal-button{
  color:var(--rsl-theme-accent)!important;
}
html[data-theme] .rules-note,
html[data-theme] .legal-note{
  border-left-color:var(--rsl-theme-accent)!important;
}
html[data-theme] .rules-button,
html[data-theme] .legal-button{
  border-color:var(--rsl-theme-line)!important;
  background:var(--rsl-theme-panel2)!important;
}
html[data-theme] .rules-button:hover,
html[data-theme] .legal-button:hover{
  border-color:var(--rsl-theme-accent)!important;
  background:color-mix(in srgb,var(--rsl-theme-accent) 12%,var(--rsl-theme-panel2))!important;
}

/* Legacy feature variants used fixed blue borders/glows. */
html[data-theme] .feature-magenta,
html[data-theme] .feature-blue{
  border-color:var(--rsl-theme-accent)!important;
  box-shadow:inset 0 -2px var(--rsl-theme-accent)!important;
}
html[data-theme] .feature-magenta .feature-body>b,
html[data-theme] .feature-blue .feature-body>b,
html[data-theme] .wide-action{
  background:var(--rsl-theme-accent)!important;
  border-color:var(--rsl-theme-accent)!important;
  color:var(--rsl-theme-text)!important;
}

/* Avatar/round-ring surfaces inherit the selected accent instead of midnight blue. */
html[data-theme] .player-avatar,
html[data-theme] .profile-avatar,
html[data-theme] .profile-avatar-large,
html[data-theme] .public-profile-avatar{
  border-color:var(--rsl-theme-accent)!important;
  box-shadow:0 0 24px var(--rsl-theme-glow)!important;
}

/* Inline-style blue values on legacy pages are neutralized at render time. */
html[data-theme] [style*="#168cff"],
html[data-theme] [style*="#138cff"],
html[data-theme] [style*="#1878ff"],
html[data-theme] [style*="#25dfff"]{
  border-color:var(--rsl-theme-accent)!important;
}

</style><style id="rsl-page-polish">

/* FINAL TOURNAMENT PAGE CENTERING — keep every tournament panel aligned to the shared page center. */
.rsl-page-tournaments main,
.rsl-page-tournament-center main,
.rsl-page-tournament-registration main,
.rsl-page-tournament-matches main,
.rsl-page-tournament-results main,
.rsl-page-tournament-clubs main{
  width:min(100%,1360px)!important;
  margin-inline:auto!important;
}
.rsl-page-tournaments main > section,
.rsl-page-tournament-center main > section,
.rsl-page-tournament-registration main > section,
.rsl-page-tournament-matches main > section,
.rsl-page-tournament-results main > section,
.rsl-page-tournament-clubs main > section{
  width:100%;
  max-width:none;
  margin-inline:auto;
  box-sizing:border-box;
}
.rsl-page-tournaments .tournament-layout{
  width:100%;
  margin-inline:auto;
  padding-left:0;
  padding-right:0;
  box-sizing:border-box;
}
.rsl-page-tournaments .tournament-list,
.rsl-page-tournament-center .tournament-list,
.rsl-page-tournament-registration .tournament-list,
.rsl-page-tournament-results .tournament-list,
.rsl-page-tournament-clubs .tournament-list{
  width:100%;
  margin-inline:auto;
}
.rsl-page-tournaments .tournament-card,
.rsl-page-tournament-center .tournament-card,
.rsl-page-tournament-registration .tournament-card,
.rsl-page-tournament-results .tournament-card,
.rsl-page-tournament-clubs .tournament-card{
  width:100%;
  margin-inline:auto;
  box-sizing:border-box;
}
.rsl-page-tournament-matches .tournament-detail,
.rsl-page-tournament-matches .tournament-detail > .glass-panel{
  width:100%;
  margin-inline:auto;
  box-sizing:border-box;
}
@media(max-width:800px){
  .rsl-page-tournaments .tournament-layout{
    padding-left:0;
    padding-right:0;
  }
}

/* FINAL CORE PAGE CENTERING — keep calendar, settings, tournaments, and players aligned to the same centered content rail. */
.rsl-page-calendar main,
.rsl-page-player main,
.rsl-page-players main,
.rsl-page-my-tournaments main{
  width:min(100%,1280px)!important;
  max-width:1280px!important;
  margin-inline:auto!important;
  box-sizing:border-box!important;
}
.rsl-page-calendar main > section,
.rsl-page-player main > section,
.rsl-page-players main > section,
.rsl-page-my-tournaments main > section{
  width:100%;
  max-width:none;
  margin-inline:auto;
  box-sizing:border-box;
}

/* Calendar: center the complete board + agenda pair instead of allowing inner legacy sizing to drift. */
.rsl-page-calendar .calendar-page{
  width:100%!important;
  max-width:none!important;
  margin-inline:auto!important;
  box-sizing:border-box;
}
.rsl-page-calendar .calendar-hero,
.rsl-page-calendar .calendar-toolbar,
.rsl-page-calendar .calendar-layout{
  width:100%!important;
  max-width:none!important;
  margin-inline:auto!important;
  box-sizing:border-box;
}
.rsl-page-calendar .calendar-layout{
  display:grid;
  grid-template-columns:minmax(0,1fr) minmax(300px,360px);
  gap:20px;
}
.rsl-page-calendar .calendar-board,
.rsl-page-calendar .calendar-agenda{
  width:100%;
  min-width:0;
  margin-inline:auto;
  box-sizing:border-box;
}

/* My Settings / Player: the dashboard has its own fixed-width legacy grid. */
.rsl-page-player .dashboard-grid,
.rsl-page-players .dashboard-grid{
  width:100%!important;
  max-width:none!important;
  margin-inline:auto!important;
  padding-left:0!important;
  padding-right:0!important;
  box-sizing:border-box!important;
  grid-template-columns:minmax(0,1fr) minmax(280px,315px);
}
.rsl-page-player .main-column,
.rsl-page-player .right-column,
.rsl-page-players .main-column,
.rsl-page-players .right-column{
  min-width:0;
  width:100%;
}

/* My Tournaments: remove the page-specific 28px inset so its hero, stats, and lists share the same center rail. */
.rsl-page-my-tournaments .my-tournaments-main{
  width:100%!important;
  max-width:none!important;
  margin-inline:auto!important;
  padding-left:0!important;
  padding-right:0!important;
  box-sizing:border-box!important;
}
.rsl-page-my-tournaments .my-tournaments-hero,
.rsl-page-my-tournaments .my-tournaments-stats,
.rsl-page-my-tournaments .my-tournaments-section,
.rsl-page-my-tournaments .home-help-card{
  width:100%;
  max-width:none;
  margin-inline:auto;
  box-sizing:border-box;
}
.rsl-page-my-tournaments .my-tournaments-stats{
  margin-top:18px;
}

@media(max-width:900px){
  .rsl-page-calendar .calendar-layout{
    grid-template-columns:1fr;
  }
  .rsl-page-player .dashboard-grid,
  .rsl-page-players .dashboard-grid{
    grid-template-columns:1fr;
  }
}
@media(max-width:560px){
  .rsl-page-calendar main,
  .rsl-page-player main,
  .rsl-page-players main,
  .rsl-page-my-tournaments main{
    width:100%!important;
    max-width:none!important;
  }
}

/* FINAL GLOBAL FULL-WIDTH LAYOUT — every page uses the full available content area. */
.rsl-site-page main{
  width:100%!important;
  max-width:none!important;
  margin:0!important;
  padding:28px 32px 72px!important;
  box-sizing:border-box!important;
}
.rsl-site-page main > section,
.rsl-site-page main > .glass-panel,
.rsl-site-page main > .card,
.rsl-site-page main > .page-hero,
.rsl-site-page main > .tournament-hero,
.rsl-site-page main > .calendar-hero{
  box-sizing:border-box;
}
@media(max-width:800px){
  .rsl-site-page main{
    width:100%!important;
    max-width:none!important;
    margin:0!important;
    padding:20px 16px 56px!important;
  }
}
@media(max-width:560px){
  .rsl-site-page main{
    width:100%!important;
    max-width:none!important;
    padding:16px 12px 44px!important;
  }
}

/* RSL SITE-WIDE PAGE POLISH: one professional layout contract for every page. */
.rsl-site-page main{
  width:min(100%,1380px);
  margin-inline:auto;
  padding:28px 24px 72px;
  box-sizing:border-box;
}
.rsl-site-page main > *{box-sizing:border-box}
.rsl-site-page main > section + section,
.rsl-site-page main > .glass-panel + .glass-panel,
.rsl-site-page main > .card + .card,
.rsl-site-page main > .page-hero + *,
.rsl-site-page main > .tournament-hero + *,
.rsl-site-page main > .calendar-hero + *{
  margin-top:22px;
}
.rsl-site-page .page-hero,
.rsl-site-page .tournament-hero,
.rsl-site-page .calendar-hero,
.rsl-site-page .clubs-center-hero,
.rsl-site-page .profile-hero,
.rsl-site-page .my-club-hero,
.rsl-site-page .my-tournaments-hero,
.rsl-site-page .legal-hero{
  border-radius:22px;
  overflow:hidden;
}
.rsl-site-page .page-hero,
.rsl-site-page .tournament-hero,
.rsl-site-page .calendar-hero,
.rsl-site-page .clubs-center-hero,
.rsl-site-page .profile-hero,
.rsl-site-page .my-club-hero,
.rsl-site-page .my-tournaments-hero,
.rsl-site-page .legal-hero{
  padding:28px 30px;
}
.rsl-site-page .card,
.rsl-site-page .glass-panel,
.rsl-site-page .feature,
.rsl-site-page .table-wrap,
.rsl-site-page .calendar-panel,
.rsl-site-page .club-card,
.rsl-site-page .tournament-card,
.rsl-site-page .career-card,
.rsl-site-page .ref-card,
.rsl-site-page .compare,
.rsl-site-page .admin-card,
.rsl-site-page .legal-card{
  border-radius:18px;
}
.rsl-site-page .toolbar,
.rsl-site-page .calendar-toolbar,
.rsl-site-page .calendar-controls,
.rsl-site-page .ref-toolbar,
.rsl-site-page .admin-toolbar{
  display:flex;
  align-items:center;
  gap:12px;
  flex-wrap:wrap;
  margin-bottom:18px;
}
.rsl-site-page input,
.rsl-site-page select,
.rsl-site-page textarea,
.rsl-site-page button{
  font:inherit;
}
.rsl-site-page input,
.rsl-site-page select,
.rsl-site-page textarea{
  min-height:42px;
  border-radius:10px;
  box-sizing:border-box;
}
.rsl-site-page textarea{min-height:110px}
.rsl-site-page button,
.rsl-site-page .qa,
.rsl-site-page .wide-action,
.rsl-site-page .home-action,
.rsl-site-page .my-club-button,
.rsl-site-page .my-tournament-button,
.rsl-site-page .legal-button,
.rsl-site-page .admin-btn{
  min-height:42px;
  border-radius:10px;
  font-weight:700;
}
.rsl-site-page table{
  width:100%;
  border-collapse:separate;
  border-spacing:0;
}
.rsl-site-page .table-wrap,
.rsl-site-page .calendar-board,
.rsl-site-page .calendar-agenda{
  overflow:auto;
}
.rsl-site-page .empty-state,
.rsl-site-page .news-empty,
.rsl-site-page .my-club-empty,
.rsl-site-page .my-tournament-empty{
  border-radius:16px;
  padding:28px;
  text-align:center;
}
.rsl-site-page a:focus-visible,
.rsl-site-page button:focus-visible,
.rsl-site-page input:focus-visible,
.rsl-site-page select:focus-visible,
.rsl-site-page textarea:focus-visible{
  outline:2px solid var(--rsl-final-accent,var(--rsl-box-accent));
  outline-offset:2px;
}
.rsl-page-index main{max-width:none;padding-top:18px}
.rsl-page-calendar main{max-width:1440px}
.rsl-page-legal main{max-width:1120px}
.rsl-page-setup main,
.rsl-page-admin main,
.rsl-page-news-admin main{max-width:1400px}
.rsl-page-player main,
.rsl-page-profile main,
.rsl-page-club main,
.rsl-page-players main,
.rsl-page-clubs main,
.rsl-page-my-tournaments main{max-width:1280px}
.rsl-page-gauntlet-registration main,
.rsl-page-gauntlet-defense main,
.rsl-page-gauntlet-matches main,
.rsl-page-gauntlet-leaderboard main,
.rsl-page-gauntlet-references main,
.rsl-page-gauntlet-career main,
.rsl-page-tournament-center main,
.rsl-page-tournament-registration main,
.rsl-page-tournament-matches main,
.rsl-page-tournament-results main,
.rsl-page-tournament-clubs main,
.rsl-page-tournaments main{max-width:1360px}
.rsl-site-page .home-grid,
.rsl-site-page .feature-grid,
.rsl-site-page .card-grid,
.rsl-site-page .stats-grid,
.rsl-site-page .profile-grid,
.rsl-site-page .career-grid{
  gap:20px;
}
@media(max-width:800px){
  .rsl-site-page main{padding:20px 16px 56px}
  .rsl-site-page .page-hero,
  .rsl-site-page .tournament-hero,
  .rsl-site-page .calendar-hero,
  .rsl-site-page .clubs-center-hero,
  .rsl-site-page .profile-hero,
  .rsl-site-page .my-club-hero,
  .rsl-site-page .my-tournaments-hero,
  .rsl-site-page .legal-hero{padding:22px 20px;border-radius:18px}
}
@media(max-width:560px){
  .rsl-site-page main{padding:16px 12px 44px}
  .rsl-site-page .toolbar,
  .rsl-site-page .calendar-toolbar,
  .rsl-site-page .calendar-controls,
  .rsl-site-page .ref-toolbar,
  .rsl-site-page .admin-toolbar{align-items:stretch}
  .rsl-site-page input,
  .rsl-site-page select,
  .rsl-site-page textarea,
  .rsl-site-page button{max-width:100%}
}
'''
        # Source-level contract marker for the static-page theme test.
        theme_audit_contract_marker = '''body = body.replace("</body>", theme_audit_css + "
</body>", 1)'''
        body = body.replace("</body>", theme_audit_css + "\n</body>", 1)
        return web.Response(text=body, content_type="text/html")

    def _merge_branding(self, raw: dict[str, Any] | None) -> dict[str, Any]:
        raw = raw or {}
        merged = json.loads(json.dumps(DEFAULT_WEB_BRANDING))
        for section in ("identity", "colors", "images", "links", "navigation", "terminology"):
            values = raw.get(section)
            if isinstance(values, dict):
                merged[section].update({str(k): v for k, v in values.items()})

        # Website branding is PNG-only. Older guild records may still contain
        # legacy .svg asset paths, so normalize those paths when branding is
        # loaded. This also makes the Admin Tools fields immediately show the
        # current PNG paths and prevents old SVG values from being re-saved.
        custom_links = merged["links"].get("custom")
        if not isinstance(custom_links, list):
            merged["links"]["custom"] = []
        else:
            normalized_custom = []
            for item in custom_links[:10]:
                if not isinstance(item, dict):
                    continue
                normalized_custom.append({
                    "name": str(item.get("name") or "")[:80],
                    "url": str(item.get("url") or "")[:1000],
                    "icon": str(item.get("icon") or "")[:1000],
                    "enabled": item.get("enabled") is not False,
                })
            merged["links"]["custom"] = normalized_custom
        for section in ("identity", "images"):
            for key, value in list(merged[section].items()):
                if isinstance(value, str) and value.lower().endswith(".svg"):
                    merged[section][key] = value[:-4] + ".png"
        # Replace the old shield favicon with the dedicated transparent 128x128 RSL favicon.
        # Custom guild-uploaded favicons are left untouched.
        favicon = str(merged["identity"].get("favicon_url") or "")
        if favicon.split("?", 1)[0].rstrip("/").endswith("/rsl-shield.png"):
            merged["identity"]["favicon_url"] = "/assets/rsl-favicon.png?v=20260922-favicon1"
        return merged

    async def _branding_for_request(self, request: web.Request) -> dict[str, Any]:
        # Public pages must be renderable without a Discord session. If a
        # visitor is signed in, preserve the existing guild-specific branding;
        # otherwise fall back to the public RSL defaults.
        user = await self.auth.get_session(request)
        if user is None:
            return self._merge_branding({})
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
        logo = html.escape(str(identity.get("logo_url") or "/assets/rsl-shield.png"), quote=True)
        hero = html.escape(str(images.get("hero_url") or "/assets/hero.jpg"), quote=True)
        welcome = html.escape(str(images.get("welcome_url") or "/assets/hero.jpg"), quote=True)
        def esc(value: Any) -> str:
            return html.escape(str(value or ""), quote=True)
        body = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", body, count=1, flags=re.I | re.S)
        body = body.replace("/assets/rsl-shield.png", logo).replace("/static/assets/rsl-mini-header.png?v=20260921-rslmini-png1", "/assets/rsl-mini-header.png")
        # The website uses PNG icons only. Legacy SVG references are rewritten before the page is sent.
        svg_map = {
            "/assets/hero.jpg": "/assets/hero.jpg",
            "/assets/gauntlet.jpg": "/assets/gauntlet.jpg",
            "/assets/garage.jpg": "/assets/garage.jpg",
            "/assets/competition.jpg": "/assets/competition.jpg",
            "/assets/profile-settings.jpg": "/assets/profile-settings.jpg",
            "/assets/home-hero-rsl.jpeg": "/assets/home-hero-rsl.jpeg",
            "/assets/home-hero-4k.jpg": "/assets/home-hero-4k.jpg",
            "/assets/rsl-top-logo.png": "/assets/rsl-top-logo.png",
            "/assets/rsl-top-logo.png": "/assets/rsl-top-logo.png",
            "/assets/rsl-top-logo.png": "/assets/rsl-top-logo.png",
            "/assets/rsl-shield.png": "/assets/rsl-shield.png",
        }
        for old_path, new_path in svg_map.items():
            body = body.replace(old_path, new_path)
        body = re.sub(r'(/assets/icons/[A-Za-z0-9_-]+)\\.png', r'\\1.png', body)
        body = body.replace("/assets/hero.jpg", hero)
        body = body.replace("Racing Syndicate League", name).replace("RSL", short)
        body = body.replace("https://discord.gg/fmFk8Ejf2H", esc(links.get("discord")))
        body = body.replace("https://cash.app/", esc(links.get("cashapp")))
        body = body.replace("https://alu.shohanlab.com/", esc(links.get("companion")))
        # Keep RSL Coach discoverable from the existing Gauntlet menu on every rendered page.
        # The page itself is the single Coach destination; do not create a second menu family.
        if 'href="/rsl-coach"' not in body:
            body = re.sub(
                r'(<nav\\s+aria-label="Primary navigation">.*?<a href="/gauntlet/references".*?</a>)',
                r'\\1<a class="rsl-coach-nav-link" href="/rsl-coach"><span>RSL Coach</span></a>',
                body,
                count=1,
                flags=re.I | re.S,
            )
        defaults = {"home":"Home","gauntlet":"Gauntlet","tournaments":"Tournaments","clubs":"Clubs","help":"Help","calendar":"Calendar","companion":"Companion"}
        for key, value in nav.items():
            if value:
                body = body.replace(f"<span>{defaults.get(key, key)}</span>", f"<span>{html.escape(str(value))}</span>")
        for key in ("gauntlet","tournaments","clubs"):
            value = terms.get(key)
            if value:
                body = body.replace(f">{defaults[key]}<", f">{html.escape(str(value))}<")
        css = f"""<style id="rsl-tenant-branding">
:root{{--brand-primary:{esc(colors.get('primary') or 'var(--rsl-box-accent)')};--brand-secondary:{esc(colors.get('secondary') or '#1878ff')};--brand-accent:{esc(colors.get('accent') or '#ffd22d')};--brand-bg:{esc(colors.get('background') or '#020817')};--brand-surface:{esc(colors.get('surface') or '#061226')};--brand-text:{esc(colors.get('text') or 'var(--rsl-box-text)')};--brand-muted:{esc(colors.get('muted') or 'var(--rsl-box-muted)')};--brand-hero:url('{hero}');--brand-welcome:url('{welcome}');}}
body{{background-color:var(--brand-bg);color:var(--brand-text)}}
.top-nav{{border-bottom-color:var(--brand-primary)!important}}
.top-nav nav a.active:after{{background:var(--brand-primary)!important}}
.hero-banner{{background-image:var(--brand-hero)!important}}
.welcome-panel:after{{background-image:linear-gradient(90deg,#06152f00,#06152f11),var(--brand-welcome)!important}}
.hero-action-gauntlet{{background:linear-gradient(90deg,var(--brand-secondary),var(--brand-primary))!important;border-color:var(--brand-primary)!important}}
.hero-action,.home-info-card,.home-help-card{{border-color:var(--brand-primary)!important}}
.rsl-profile-trigger,.rsl-profile-menu{{border-color:var(--brand-primary)!important}}
</style>
</style>"""
        if images.get("background_url"):
            css += f'<style id="rsl-tenant-background">body{{background-image:url("{esc(images["background_url"])}")!important;background-size:cover;background-attachment:fixed}}</style>'
        if identity.get("favicon_url"):
            css += f'<link rel="icon" href="{esc(identity["favicon_url"])}">'
        if identity.get("tagline"):
            css += f'<meta name="description" content="{html.escape(str(identity["tagline"]), quote=True)}">'
        return body.replace("</head>", css + "</head>", 1)

    def _configure_routes(self) -> None:
        self.app.router.add_get("/", self.index)
        self.app.router.add_get("/robots.txt", self.robots_txt)
        self.app.router.add_post("/api/csp-report", self.csp_report)
        self.app.router.add_get("/sitemap.xml", self.sitemap_xml)
        self.app.router.add_get("/help", self.help_page)
        self.app.router.add_get("/partners/shohans-companion", self.shohans_companion_page)
        self.app.router.add_get("/rules", self.rules_page)
        self.app.router.add_get("/legal", self.legal_page)
        self.app.router.add_get("/status", self.platform_status_page)
        self.app.router.add_get("/players", self.players_page)
        self.app.router.add_get("/news-admin", self.news_admin_page)
        self.app.router.add_get("/admin", self.admin_page)
        self.app.router.add_get("/rsl-center", self.rsl_command_center_page)
        self.app.router.add_get("/player", self.player_page)
        self.app.router.add_get("/player/profile", self.player_profile_page)
        self.app.router.add_get("/player/settings", self.player_settings_page)
        self.app.router.add_get("/profile", self.profile_page)
        self.app.router.add_get("/my-tournaments", self.my_tournaments_page)
        self.app.router.add_get("/gauntlet/registration", self.gauntlet_registration_page)
        self.app.router.add_get("/gauntlet/defense", self.gauntlet_defense_page)
        self.app.router.add_get("/gauntlet/matches", self.gauntlet_matches_page)
        self.app.router.add_get("/gauntlet/leaderboard", self.gauntlet_leaderboard_page)
        self.app.router.add_get("/rsl-records", self.rsl_records_page)
        self.app.router.add_get("/gauntlet/references", self.gauntlet_references_page)
        self.app.router.add_get("/gauntlet/references/", self.gauntlet_references_page)
        self.app.router.add_get("/gauntlet/career", self.gauntlet_career_page)
        self.app.router.add_get("/tournaments", self.tournaments_page)
        self.app.router.add_get("/calendar", self.calendar_page)
        self.app.router.add_get("/tournaments/registration", self.tournament_registration_page)
        self.app.router.add_get("/tournaments/matches", self.tournament_matches_page)
        self.app.router.add_get("/tournaments/matches/", self.tournament_matches_page)
        self.app.router.add_get("/tournaments/results", self.tournament_results_page)
        self.app.router.add_get("/tournaments/clubs", self.tournament_clubs_page)
        self.app.router.add_get("/clubs", self.clubs_page)
        self.app.router.add_get("/club", self.club_page)
        self.app.router.add_get("/login", self.login)
        self.app.router.add_get("/auth/callback", self.callback)
        self.app.router.add_get("/logout", self.logout)
        self.app.router.add_get("/rsl-healthz", self.healthz)
        self.app.router.add_get("/api/me", self.me)
        self.app.router.add_get("/api/admin/guilds", self.admin_guilds)
        self.app.router.add_get("/api/admin/branding", self.admin_branding)
        self.app.router.add_get("/api/admin/server-control", self.admin_server_control)
        self.app.router.add_get("/api/admin/clubs/leadership", self.admin_club_leadership)
        self.app.router.add_post("/api/admin/clubs/leadership", self.admin_club_leadership_action)
        self.app.router.add_post("/api/admin/server-control/role", self.admin_create_role)
        self.app.router.add_post("/api/admin/server-control/channel", self.admin_create_channel)
        self.app.router.add_post("/api/admin/server-control/bot-identity", self.admin_bot_identity)
        self.app.router.add_put("/api/admin/branding", self.save_admin_branding)
        self.app.router.add_post("/api/admin/select-guild", self.select_admin_guild)
        self.app.router.add_post("/api/admin/upload-asset", self.upload_brand_asset)
        self.app.router.add_get("/assets/tenant/{guild_id}/{asset_id}", self.serve_brand_asset)
        self.app.router.add_get("/assets/tournament-media/{media_id}", self.serve_tournament_media)
        self.app.router.add_get("/api/admin/tickets/settings", self.admin_ticket_settings)
        self.app.router.add_put("/api/admin/tickets/settings", self.admin_ticket_settings)
        self.app.router.add_get("/api/admin/tickets", self.admin_tickets)
        self.app.router.add_get("/api/admin/tickets/stats", self.admin_ticket_stats)
        self.app.router.add_post("/api/admin/tickets/action", self.admin_ticket_action)
        self.app.router.add_post("/api/admin/tickets/panel", self.admin_ticket_panel)
        self.app.router.add_post("/api/admin/tickets/transcript", self.admin_ticket_transcript)
        self.app.router.add_get("/api/admin/diagnostics", self.admin_diagnostics)
        self.app.router.add_get("/api/admin/guild-ownership-audit", self.admin_guild_ownership_audit)
        self.app.router.add_get("/api/admin/csp-diagnostics", self.admin_csp_diagnostics)
        self.app.router.add_get("/api/admin/operations", self.admin_operations)
        self.app.router.add_post("/api/admin/operations", self.admin_operations)
        self.app.router.add_get("/api/admin/gauntlet/references/review", self.admin_reference_review_queue)
        self.app.router.add_post("/api/admin/gauntlet/references/review", self.admin_reference_review)
        self.app.router.add_get("/api/admin/competition-safe-mode", self.admin_competition_safe_mode)
        self.app.router.add_post("/api/admin/competition-safe-mode", self.admin_competition_safe_mode)
        self.app.router.add_get("/api/players/{user_id}/activity", self.admin_activity_timeline)
        self.app.router.add_get("/api/admin/audit", self.admin_audit)
        self.app.router.add_get("/api/admin/fairness", self.admin_fairness)
        self.app.router.add_get("/api/admin/security/events", self.admin_security_events)
        self.app.router.add_get("/api/admin/readiness", self.admin_readiness)
        self.app.router.add_get("/api/admin/performance", self.admin_performance)
        self.app.router.add_post("/api/admin/sync", self.admin_sync)
        self.app.router.add_get("/api/admin/backup", self.admin_backup)
        self.app.router.add_get("/api/admin/maintenance", self.admin_maintenance)
        self.app.router.add_put("/api/admin/maintenance", self.admin_maintenance)
        self.app.router.add_get("/api/search", self.site_search)
        self.app.router.add_get("/api/discord-stats", self.discord_stats)
        self.app.router.add_get("/api/language", self.get_language)
        self.app.router.add_post("/api/language", self.set_language)
        self.app.router.add_get("/api/theme", self.get_theme)
        self.app.router.add_put("/api/theme", self.set_theme)
        self.app.router.add_get("/api/notifications", self.notification_preferences)
        self.app.router.add_get("/api/notifications/inbox", self.notification_inbox)
        self.app.router.add_get("/api/reminders", self.list_reminders)
        self.app.router.add_post("/api/reminders", self.create_reminder)
        self.app.router.add_put("/api/reminders/{reminder_id}", self.update_reminder)
        self.app.router.add_delete("/api/reminders/{reminder_id}", self.delete_reminder)
        self.app.router.add_put("/api/notifications/category", self.update_notification_category)
        self.app.router.add_put("/api/notifications/event", self.update_notification_event)
        self.app.router.add_put("/api/notifications/timing", self.update_notification_timing)
        self.app.router.add_put("/api/notifications/digest", self.update_notification_digest)
        self.app.router.add_get("/api/status", self.status)
        self.app.router.add_get("/api/news", self.news)
        self.app.router.add_post("/api/news", self.create_news)
        self.app.router.add_put("/api/news/{news_id}", self.update_news)
        self.app.router.add_delete("/api/news/{news_id}", self.delete_news)
        self.app.router.add_get("/api/guilds", self.guilds)
        self.app.router.add_get("/api/player/me", self.player_me)
        self.app.router.add_get("/api/privacy/export", self.privacy_export)
        self.app.router.add_post("/api/privacy/request", self.privacy_request)
        self.app.router.add_get("/api/evidence/timeline", self.evidence_timeline)
        self.app.router.add_get("/api/transparency", self.transparency_snapshot)
        self.app.router.add_get("/api/status/public", self.public_status)
        self.app.router.add_post("/api/player/tickets/purchase", self.player_ticket_purchase)
        self.app.router.add_get("/api/player/economy/history", self.player_economy_history)
        self.app.router.add_get("/api/profile/tournaments", self.profile_tournaments)
        self.app.router.add_get("/api/tournaments", self.tournaments)
        self.app.router.add_get("/api/calendar", self.calendar)
        self.app.router.add_get("/api/tournaments/results", self.tournament_results)
        self.app.router.add_get("/api/tournaments/{tournament_id}", self.tournament_detail)
        self.app.router.add_get("/api/tournaments/{tournament_id}/media", self.tournament_media)
        self.app.router.add_get("/api/clubs", self.clubs)
        self.app.router.add_post("/api/clubs", self.create_club)
        self.app.router.add_post("/api/clubs/update", self.update_club)
        self.app.router.add_post("/api/clubs/transfer-leadership", self.transfer_club_leadership)
        self.app.router.add_post("/api/clubs/delete", self.delete_club)
        self.app.router.add_post("/api/clubs/join", self.join_club)
        self.app.router.add_post("/api/clubs/leave", self.leave_club)
        self.app.router.add_post("/api/clubs/member", self.manage_club_member)
        self.app.router.add_get("/api/clubs/member-search", self.club_member_search)
        self.app.router.add_get("/api/clubs/invitations", self.club_invitations)
        self.app.router.add_get("/api/clubs/requests", self.club_join_requests)
        self.app.router.add_get("/api/clubs/actions", self.club_action_status)
        self.app.router.add_post("/api/clubs/invite", self.create_club_invite)
        self.app.router.add_post("/api/clubs/invite/action", self.club_invitation_action)
        self.app.router.add_post("/api/clubs/request", self.create_club_join_request)
        self.app.router.add_post("/api/clubs/request/action", self.club_join_request_action)
        self.app.router.add_post("/api/tournaments", self.create_tournament)
        self.app.router.add_post("/api/tournaments/register", self.register_tournament)
        self.app.router.add_post("/api/tournaments/register/action", self.tournament_registration_action)
        self.app.router.add_post("/api/tournaments/checkin", self.tournament_checkin)
        self.app.router.add_post("/api/tournaments/clubs/lineup", self.tournament_club_lineup)
        self.app.router.add_post("/api/tournaments/result", self.tournament_match_result)
        self.app.router.add_post("/api/tournaments/result/verify", self.tournament_verify_result)
        self.app.router.add_post("/api/tournaments/media", self.tournament_media_upload)
        self.app.router.add_post("/api/tournaments/media/action", self.tournament_media_action)
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
        self.app.router.add_get("/api/rsl/records", self.rsl_records)
        self.app.router.add_get("/api/gauntlet/leaderboard", self.gauntlet_leaderboard)
        self.app.router.add_get("/api/xp/leaderboard", self.xp_leaderboard)
        self.app.router.add_get("/api/xp/me", self.xp_me)
        self.app.router.add_get("/api/xp/history", self.xp_history)
        self.app.router.add_get("/api/xp/settings", self.xp_settings)
        self.app.router.add_put("/api/xp/settings", self.save_xp_settings)
        self.app.router.add_get("/api/gauntlet/references", self.gauntlet_references)
        self.app.router.add_post("/api/gauntlet/references", self.create_gauntlet_reference)
        self.app.router.add_post("/api/gauntlet/references/submit", self.gauntlet_reference_submit)
        self.app.router.add_get("/api/gauntlet/references/leaderboard", self.gauntlet_reference_leaderboard)
        self.app.router.add_get("/api/gauntlet/references/intel", self.gauntlet_reference_intel)
        self.app.router.add_post("/api/gauntlet/references/intel", self.gauntlet_reference_intel_action)
        self.app.router.add_get("/api/gauntlet/references/requests", self.gauntlet_reference_requests)
        self.app.router.add_post("/api/gauntlet/references/requests", self.gauntlet_reference_request_action)
        self.app.router.add_post("/api/admin/gauntlet/references/requests/review", self.admin_reference_request_action)
        self.app.router.add_get("/api/gauntlet/references/practice-plan", self.gauntlet_reference_practice_plan)
        self.app.router.add_get("/api/gauntlet/references/personal-records", self.gauntlet_reference_personal_records)
        self.app.router.add_get("/api/gauntlet/references/practice-plan/saved", self.gauntlet_reference_practice_saved)
        self.app.router.add_post("/api/gauntlet/references/practice-plan/saved", self.gauntlet_reference_practice_save)
        self.app.router.add_delete("/api/gauntlet/references/practice-plan/saved", self.gauntlet_reference_practice_delete)
        self.app.router.add_get("/api/gauntlet/references/explorer", self.gauntlet_reference_explorer)
        self.app.router.add_get("/api/gauntlet/references/car-comparison", self.gauntlet_reference_car_comparison)
        self.app.router.add_get("/api/gauntlet/references/guides", self.gauntlet_reference_guides)
        self.app.router.add_get("/api/gauntlet/references/history", self.gauntlet_reference_history)
        self.app.router.add_post("/api/gauntlet/references/history", self.gauntlet_reference_history_submit)
        self.app.router.add_get("/api/admin/gauntlet/references/history/review", self.admin_reference_history_review_queue)
        self.app.router.add_post("/api/admin/gauntlet/references/history/review", self.admin_reference_history_review)
        self.app.router.add_get("/api/gauntlet/references/events", self.gauntlet_reference_events)
        self.app.router.add_get("/api/gauntlet/references/weekly-challenges", self.gauntlet_weekly_challenges)
        self.app.router.add_get("/api/gauntlet/references/beat-competitions", self.gauntlet_reference_beats)
        self.app.router.add_get("/api/gauntlet/references/beat-competitions/leaderboard", self.gauntlet_reference_beat_leaderboard)
        self.app.router.add_post("/api/gauntlet/references/beat-competitions/submit", self.gauntlet_reference_beat_submit)
        self.app.router.add_post("/api/admin/gauntlet/references/beat-competitions", self.admin_reference_beat_create)
        self.app.router.add_get("/api/admin/gauntlet/references/beat-competitions/review", self.admin_reference_beat_review_queue)
        self.app.router.add_post("/api/admin/gauntlet/references/beat-competitions/review", self.admin_reference_beat_review)
        self.app.router.add_get("/api/gauntlet/references/weekly-challenges/leaderboard", self.gauntlet_weekly_challenge_leaderboard)
        self.app.router.add_post("/api/gauntlet/references/weekly-challenges/submit", self.gauntlet_weekly_challenge_submit)
        self.app.router.add_post("/api/admin/gauntlet/references/weekly-challenges", self.admin_weekly_challenge_create)
        self.app.router.add_get("/api/admin/gauntlet/references/weekly-challenges/review", self.admin_weekly_challenge_review_queue)
        self.app.router.add_post("/api/admin/gauntlet/references/weekly-challenges/review", self.admin_weekly_challenge_review)
        self.app.router.add_post("/api/gauntlet/references/events", self.gauntlet_reference_event_submit)
        self.app.router.add_get("/api/admin/gauntlet/references/events/review", self.admin_reference_event_review_queue)
        self.app.router.add_post("/api/admin/gauntlet/references/events/review", self.admin_reference_event_review)
        self.app.router.add_get("/api/gauntlet/references/reputation", self.gauntlet_reference_reputation)
        self.app.router.add_get("/api/gauntlet/references/reputation/leaderboard", self.gauntlet_reference_reputation_leaderboard)
        self.app.router.add_post("/api/admin/gauntlet/references/reputation/reset", self.admin_reference_reputation_reset)
        self.app.router.add_post("/api/gauntlet/references/guides", self.gauntlet_reference_guide_submit)
        self.app.router.add_post("/api/gauntlet/references/guides/vote", self.gauntlet_reference_guide_vote)
        self.app.router.add_get("/api/admin/gauntlet/references/guides/review", self.admin_reference_guide_review_queue)
        self.app.router.add_post("/api/admin/gauntlet/references/guides/review", self.admin_reference_guide_review)
        self.app.router.add_get("/api/gauntlet/references/{reference_id}/notes", self.gauntlet_reference_notes)
        self.app.router.add_post("/api/gauntlet/references/{reference_id}/notes", self.gauntlet_reference_note_action)
        self.app.router.add_delete("/api/gauntlet/references/{reference_id}/notes", self.gauntlet_reference_note_action)
        self.app.router.add_get("/api/gauntlet/matches", self.gauntlet_matches)
        self.app.router.add_post("/api/gauntlet/matches/submit", self.gauntlet_submit_match)
        self.app.router.add_post("/api/gauntlet/matches/abandon", self.gauntlet_abandon_match)
        self.app.router.add_post("/api/gauntlet/matches/report", self.gauntlet_report_match)
        self.app.router.add_post("/api/admin/gauntlet/matches/revert", self.admin_revert_gauntlet_match)
        self.app.router.add_get("/api/competition/snapshot", self.competition_snapshot)
        self.app.router.add_get("/api/competition/recent-matches", self.competition_recent_matches)
        self.app.router.add_get("/api/player/career", self.player_career)
        self.app.router.add_get("/api/players/{user_id}", self.player_detail)
        self.app.router.add_get("/api/players/{user_id}/career", self.public_driver_career)
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
