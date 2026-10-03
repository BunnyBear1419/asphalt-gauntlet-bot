"""RSL web public route family."""
from .._web_context import *
from ...core.rsl_roles import XP_LEVEL_ROLES, GAUNTLET_SEASONAL_ROLES, TOURNAMENT_SEASONAL_ROLES, PERMANENT_ACHIEVEMENT_ROLES

class PublicRoutesMixin:
    @staticmethod
    def _is_png_asset_url(value: str) -> bool:
        # Generated tenant assets are always normalized to PNG even though their route has no .png suffix.
        try:
            path = (urlsplit(str(value or '')).path or '').lower()
        except Exception:
            path = str(value or '').split('?', 1)[0].split('#', 1)[0].lower()
        return path.endswith('.png') or path.startswith('/assets/tenant/')

    async def save_admin_branding(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        try:
            payload = await self._json_object(request)
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
                if section in {"images","identity"} and key.endswith("_url") and value and value.startswith("/") and section == "identity" and not self._is_png_asset_url(value):
                    raise web.HTTPBadRequest(text=f"{section}.{key} must use a PNG asset.")
                clean[section][key]=value
        custom = clean["links"].get("custom")
        if not isinstance(custom, list):
            custom = []
        link_payload = incoming.get("links") if isinstance(incoming.get("links"), dict) else {}
        if len(custom) > 10:
            raise web.HTTPBadRequest(text="A maximum of 10 custom footer links is allowed.")
        clean_custom = []
        for item in custom:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name","")).strip()[:80]
            url = str(item.get("url","")).strip()[:1000]
            icon = str(item.get("icon","")).strip()[:1000]
            if url and not (url.startswith("https://") or url.startswith("http://") or url.startswith("/")):
                raise web.HTTPBadRequest(text="Custom footer link URLs must be http(s) or site-relative paths.")
            if icon and not (icon.startswith("https://") or icon.startswith("http://") or icon.startswith("/")):
                raise web.HTTPBadRequest(text="Custom footer icon URLs must be http(s) or site-relative paths.")
            if icon.startswith("/") and not self._is_png_asset_url(icon):
                raise web.HTTPBadRequest(text="Custom footer icons must use PNG assets.")
            if not name and not url and not icon:
                continue
            if not name:
                name = "Footer Link"
            if not url:
                raise web.HTTPBadRequest(text="Each custom footer link needs a URL.")
            enabled = item.get("enabled") is not False
            clean_custom.append({"name":name,"url":url,"icon":icon,"enabled":enabled})
        clean["links"]["custom"] = clean_custom
        # Capture only assets referenced by the previous durable branding. This
        # avoids deleting newly uploaded-but-not-yet-assigned assets.
        previous_settings = await self.bot.db.settings.find_one({"_id": guild_id}) or {}
        previous_branding = self._merge_branding(previous_settings.get("web_branding"))
        def _tenant_asset_ids(value: Any) -> set[str]:
            matches = re.findall(r"/assets/tenant/[^/]+/([A-Za-z0-9_-]+)", str(value or ""))
            return set(matches)
        previous_asset_ids = _tenant_asset_ids(json.dumps(previous_branding))
        new_asset_ids = _tenant_asset_ids(json.dumps(clean))
        superseded_asset_ids = previous_asset_ids - new_asset_ids

        # Persist the new branding pointer before deleting superseded assets.
        await self.bot.db.settings.update_one({"_id":guild_id},{"$set":{"web_branding":clean}},upsert=True)
        if superseded_asset_ids:
            from bson import ObjectId
            try:
                async for asset in self.bot.db.web_brand_assets.find({
                    "guild_id": str(guild_id),
                    "_id": {"$in": list(superseded_asset_ids)},
                }):
                    gridfs_id = asset.get("gridfs_id")
                    if asset.get("storage") == "gridfs" and gridfs_id:
                        try:
                            from gridfs.asynchronous import AsyncGridFSBucket
                            bucket = AsyncGridFSBucket(self.bot.db, bucket_name="web_brand_assets")
                            try:
                                await bucket.delete(ObjectId(str(gridfs_id)))
                            except Exception as exc:
                                # NoFile means the blob is already gone, which is the goal.
                                if type(exc).__name__ != "NoFile":
                                    raise
                        except Exception:
                            # Keep the metadata row (and its gridfs_id pointer) so the
                            # blob is not orphaned with no record of where it lives.
                            log.exception("Unable to purge superseded brand asset GridFS file %s", gridfs_id)
                            continue
                    await self.bot.db.web_brand_assets.delete_one({"_id": asset.get("_id"), "guild_id": str(guild_id)})
            except Exception:
                log.exception("Unable to purge superseded brand assets for guild %s", guild_id)
        await self._audit(guild_id,user.user_id,"Web white-label branding updated")
        return web.json_response({"ok":True,"branding":clean,"guild_id":guild_id})

    async def select_admin_guild(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        payload = await self._json_object(request)
        gid = str(payload.get("guild_id","")).strip()
        rows = await self._admin_guilds_data(user)
        if gid not in {row["id"] for row in rows}:
            raise web.HTTPForbidden(text="You do not have administrator access to that server.")
        response = web.json_response({"ok":True,"guild_id":gid})
        response.set_cookie("rsl_guild_id",gid,max_age=2592000,path="/",secure=request.secure,httponly=False,samesite="Lax")
        return response

    async def robots_txt(self, request: web.Request) -> web.Response:
        """Return crawler instructions for the public Racing Syndicate League site."""
        body = "User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /news-admin\nDisallow: /player\nDisallow: /players\nDisallow: /api/\nDisallow: /assets/tenant/\nSitemap: https://asph.discloud.app/sitemap.xml\n"
        return web.Response(text=body, content_type="text/plain")

    async def sitemap_xml(self, request: web.Request) -> web.Response:
        """Return the canonical public-page XML sitemap."""
        # Keep this list aligned with public routes only. Account/admin/API
        # endpoints and pages marked noindex are intentionally excluded.
        urls = [
            "/",
            "/help",
            "/legal",
            "/gauntlet/registration",
            "/gauntlet/defense",
            "/gauntlet/matches",
            "/gauntlet/leaderboard",
            "/gauntlet/references",
            "/gauntlet/career",
            "/tournaments",
            "/tournaments/registration",
            "/tournaments/matches",
            "/tournaments/results",
            "/tournaments/clubs",
            "/calendar",
            "/clubs",
        ]
        website_url = str((self._merge_branding({}).get("links") or {}).get("website") or "https://asph.discloud.app").rstrip("/")
        entries = "".join(
            f"<url><loc>{html.escape(website_url + path)}</loc></url>"
            for path in urls
        )
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"{entries}</urlset>"
        )
        return web.Response(text=body, content_type="application/xml")

    async def save_xp_settings(self, request: web.Request) -> web.Response:
        from ...core.rsl_xp import DEFAULT_XP_SETTINGS
        _, guild_id, _ = await self.require_admin(request)
        payload = await self._json_object(request)
        clean = {k: payload[k] for k in payload if k in DEFAULT_XP_SETTINGS}
        if "curve" in clean and clean["curve"] not in {"linear", "exponential", "flat"}:
            raise web.HTTPBadRequest(text="Invalid XP curve.")
        if "multiplier" in clean:
            clean["multiplier"] = max(0.1, min(10.0, float(clean["multiplier"])))
        if "max_level" in clean:
            clean["max_level"] = max(0, int(clean["max_level"]))
        await self.bot.db.rsl_xp_settings.update_one({"_id": guild_id}, {"$set": clean}, upsert=True)
        return web.json_response({"ok": True})

    async def create_gauntlet_reference(self, request: web.Request) -> web.Response:
        user,guild_id,_=await self.require_admin(request); payload = await self._json_object(request)
        course=str(payload.get("course","")).strip(); title=str(payload.get("title","")).strip()[:120]; video_url=str(payload.get("video_url","")).strip()[:500]
        if course not in ALU_TRACKS or not title or not video_url: raise web.HTTPBadRequest(text="Course, title and video URL are required.")
        from bson import ObjectId
        try: car_rank=int(payload.get("car_rank",0) or 0)
        except (TypeError,ValueError): car_rank=0
        doc={"_id":ObjectId(),"guild_id":str(guild_id),"course":course,"title":title,"driver":str(payload.get("driver","")).strip()[:100],"time":str(payload.get("time","")).strip()[:30],"car":str(payload.get("car","")).strip()[:100],"car_rank":max(0,car_rank),"video_url":video_url,"description":str(payload.get("description","")).strip()[:1000],"official":bool(payload.get("official",False)),"created_by":str(user.user_id),"created_at":time.time()}
        await self.bot.db.gauntlet_references.insert_one(doc); await self._audit(str(guild_id),str(user.user_id),"Gauntlet reference added")
        return web.json_response({"ok":True,"id":str(doc["_id"])})






    async def update_notification_category(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        payload = await self._json_object(request)
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
        payload = await self._json_object(request)
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

    async def update_notification_digest(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        payload = await self._json_object(request)
        frequency = str(payload.get("frequency", "off")).strip().lower()
        if frequency not in {"off", "daily", "weekly"}:
            raise web.HTTPBadRequest(text="Digest frequency must be off, daily, or weekly.")
        try:
            hour = int(payload.get("hour", 9))
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="Digest hour must be an integer.")
        if not 0 <= hour <= 23:
            raise web.HTTPBadRequest(text="Digest hour must be between 0 and 23.")
        guild_id = str(payload.get("guild_id", "")).strip()
        if guild_id and guild_id not in await self._live_guild_ids_for_user(user):
            raise web.HTTPForbidden(text="You are not a member of that RSL server.")
        await self.bot.db.notification_preferences.update_one(
            {"_id": str(user.user_id)},
            {"$set": {"digest_frequency": frequency, "digest_hour": hour, "guild_id": guild_id, "updated_at": time.time()}},
            upsert=True,
        )
        return web.json_response({"ok": True, "frequency": frequency, "hour": hour})

    async def update_notification_event(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        payload = await self._json_object(request)
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

    async def create_tournament(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_tournament_admin(request)
        try:
            payload = await self._json_object(request)
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
        result_submission_mode = str(payload.get("result_submission_mode", "player_review")).strip().casefold()
        if result_submission_mode not in {"admin_only", "player_review"}:
            raise web.HTTPBadRequest(text="Result submission mode must be admin_only or player_review.")
        from ALU_Gauntlet.core.tournament import generate_tournament_bracket
        from ALU_Gauntlet.core.rsl_tournament_rewards import normalize_tournament_rewards
        bracket = generate_tournament_bracket(fmt, max_players)
        try:
            rewards = normalize_tournament_rewards(payload.get("rewards"))
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="Tournament rewards must contain non-negative integer values.")
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
            "result_submission_mode": result_submission_mode,
            "rewards": rewards,
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
        user, _live_guild_id, _ = await self.require_guild_member(request)
        try:
            payload = await self._json_object(request)
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
        if tournament and tournament.get("registration_deadline"):
            try:
                deadline = datetime.fromisoformat(str(tournament["registration_deadline"]).replace("Z", "+00:00"))
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) >= deadline.astimezone(timezone.utc):
                    raise web.HTTPConflict(text="Tournament registration has closed.")
            except ValueError:
                raise web.HTTPConflict(text="This tournament has an invalid registration deadline.")
        if not tournament or str(tournament.get("guild_id")) not in await self._live_guild_ids_for_user(user):
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
            membership = await self.bot.db.club_members.find_one({"club_id": club_id, "guild_id": str(tournament["guild_id"]), "user_id": str(user.user_id)})
            if not membership:
                raise web.HTTPForbidden(text="You must be a member of the club to register it.")
            if str(club.get("leader_id")) != str(user.user_id):
                raise web.HTTPForbidden(text="Only the club leader can enter a club in a tournament.")
            count = await self.bot.db.tournament_club_registrations.count_documents(
                {"tournament_id": tournament_id, "guild_id": str(tournament["guild_id"]), "status": {"$in": ["pending", "accepted", "checked_in"]}}
            )
            if count >= int(tournament.get("max_players", 32)):
                raise web.HTTPConflict(text="This tournament is full.")
            existing = await self.bot.db.tournament_club_registrations.find_one(
                {"tournament_id": tournament_id, "guild_id": str(tournament["guild_id"]), "club_id": club_id, "status": {"$in": ["pending", "accepted", "checked_in"]}}
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
            {"tournament_id": tournament_id, "guild_id": str(tournament["guild_id"]), "status": {"$in": ["pending", "accepted", "checked_in"]}}
        )
        if count >= int(tournament.get("max_players", 32)):
            raise web.HTTPConflict(text="This tournament is full.")
        if tournament.get("gauntlet_only"):
            profile = await self.bot.db.drivers.find_one({"_id": f'{tournament["guild_id"]}_{user.user_id}'})
            current_season = await get_current_season_number(str(tournament["guild_id"]))
            if not profile or not profile.get("season_registered") or int(profile.get("season_number", 0) or 0) != int(current_season):
                raise web.HTTPForbidden(text="This tournament is limited to drivers registered for the current Gauntlet season.")
        existing = await self.bot.db.tournament_registrations.find_one(
            {"tournament_id": tournament_id, "guild_id": str(tournament["guild_id"]), "user_id": str(user.user_id), "status": {"$in": ["pending", "accepted"]}}
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

    async def _claim_tournament_action(self, tournament_id, match_id, action):
        """Claim a short-lived MongoDB lock shared by web tournament actions and return its owner token."""
        from datetime import datetime, timezone, timedelta
        from secrets import token_urlsafe
        from pymongo.errors import DuplicateKeyError
        now = datetime.now(timezone.utc)
        token = token_urlsafe(24)
        doc = {"tournament_id": str(tournament_id), "match_id": str(match_id), "action": str(action),
               "claimed_at": now, "expires_at": now + timedelta(seconds=60), "lock_token": token}
        try:
            await self.bot.db.tournament_action_locks.insert_one(doc)
            return token
        except DuplicateKeyError:
            replaced = await self.bot.db.tournament_action_locks.find_one_and_replace(
                {"tournament_id": str(tournament_id), "match_id": str(match_id), "expires_at": {"$lt": now}}, doc
            )
            return replaced.get("lock_token") == token if replaced else False

    async def _release_tournament_action(self, tournament_id, match_id, action, lock_token):
        # Do not delete a replacement lock created after the original 60-second lease expired.
        await self.bot.db.tournament_action_locks.delete_one(
            {"tournament_id": str(tournament_id), "match_id": str(match_id), "action": str(action), "lock_token": str(lock_token)}
        )

    async def serve_tournament_media(self, request: web.Request) -> web.Response:
        user = await self.require_user(request); media_id = str(request.match_info.get("media_id", ""))
        live_guild_ids = await self._live_guild_ids_for_user(user)
        media = await self.bot.db.tournament_media.find_one({"_id": media_id, "guild_id": {"$in": list(live_guild_ids)}})
        if not media or media.get("status") != "approved": raise web.HTTPNotFound(text="Tournament media not found.")
        if str(media.get("guild_id")) not in live_guild_ids: raise web.HTTPForbidden(text="You are not a member of this server.")
        body = media.get("data") or b""
        if media.get("storage") == "gridfs" and media.get("gridfs_id"):
            try:
                from bson import ObjectId
                from gridfs.asynchronous import AsyncGridFSBucket
                bucket = AsyncGridFSBucket(self.bot.db, bucket_name="rsl_tournament_media")
                stream = await bucket.open_download_stream(ObjectId(str(media["gridfs_id"])))
                response = web.StreamResponse(status=200, headers={
                    "Content-Type": str(media.get("mime_type") or "application/octet-stream"),
                    "Cache-Control": "private, max-age=3600",
                    "X-Content-Type-Options": "nosniff",
                })
                if getattr(stream, "length", None) is not None:
                    response.content_length = int(stream.length)
                await response.prepare(request)
                while True:
                    chunk = await stream.read(64 * 1024)
                    if not chunk:
                        break
                    await response.write(chunk)
                await response.write_eof()
                return response
            except Exception as exc:
                log.exception("Tournament media GridFS read failed for %s", media_id)
                raise web.HTTPServiceUnavailable(text="Tournament media is temporarily unavailable.") from exc
        return web.Response(body=body, content_type=str(media.get("mime_type") or "application/octet-stream"), headers={"Cache-Control":"private, max-age=3600", "X-Content-Type-Options":"nosniff"})

    async def index(self, request: web.Request) -> web.StreamResponse:
        # The homepage is public. Discord authentication is only required when
        # visitors enter account-specific, player, tournament, or staff areas.
        try:
            return await self._page_response("index.html", request)
        except Exception:
            log.exception("Unable to serve the web dashboard")
            raise web.HTTPServiceUnavailable(text="The Racing Syndicate League web dashboard is temporarily unavailable.")

    async def news_admin_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_admin(request)
        return await self._page_response("news-admin.html", request)

    async def site_search(self, request: web.Request) -> web.Response:
        """Search public site content plus account-visible racing data."""
        query = request.query.get("q", "").strip()
        category = request.query.get("type", "all").strip().casefold()
        if len(query) < 2:
            return web.json_response({"query": query, "type": category, "results": []})

        allowed_types = {"all", "pages", "players", "clubs", "tournaments", "help"}
        if category not in allowed_types:
            category = "all"
        terms = [x.lower() for x in re.findall(r"[\w]+", query) if len(x) > 1][:8]
        if not terms:
            return web.json_response({"query": query, "type": category, "results": []})

        results: list[dict[str, str]] = []

        def add_result(kind: str, title: str, url: str, snippet: str, keywords: str = "") -> None:
            haystack = (title + " " + snippet + " " + keywords).lower()
            if all(term in haystack for term in terms):
                results.append({"type": kind, "title": title, "url": url, "snippet": snippet})

        pages = [
            ("Home", "/", "index.html", "pages"),
            ("Help Center", "/help", "help.html", "help"),
            ("Legal Center", "/legal", "legal.html", "pages"),
            ("Calendar", "/calendar", "calendar.html", "pages"),
            ("Clubs", "/clubs", "clubs.html", "clubs"),
            ("Tournaments", "/tournaments", "tournaments.html", "tournaments"),
            ("Tournament Registration", "/tournaments/registration", "tournament-registration.html", "tournaments"),
            ("Tournament Matches", "/tournaments/matches", "tournament-matches.html", "tournaments"),
            ("Tournament Results", "/tournaments/results", "tournament-results.html", "tournaments"),
            ("Club Tournaments", "/tournaments/clubs", "tournament-clubs.html", "tournaments"),
            ("Gauntlet Registration", "/gauntlet/registration", "gauntlet-registration.html", "pages"),
            ("Gauntlet Defense", "/gauntlet/defense", "gauntlet-defense.html", "pages"),
            ("Gauntlet Challenges & Matches", "/gauntlet/matches", "gauntlet-matches.html", "pages"),
            ("Gauntlet Leaderboards", "/gauntlet/leaderboard", "gauntlet-leaderboard.html", "pages"),
            ("Gauntlet References", "/gauntlet/references", "gauntlet-references.html", "help"),
            ("My Gauntlet Career", "/gauntlet/career", "gauntlet-career.html", "pages"),
        ]
        if category in {"all", "pages", "help", "clubs", "tournaments"}:
            for title, path, filename, kind in pages:
                if category not in {"all", kind} and not (category == "pages" and kind == "pages"):
                    continue
                try:
                    raw = (WEB_DIR / filename).read_text(encoding="utf-8")
                except OSError:
                    continue
                clean = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
                clean = html.unescape(re.sub(r"(?s)<[^>]+>", " ", clean))
                clean = re.sub(r"\s+", " ", clean).strip()
                pos = min((clean.lower().find(term) for term in terms if clean.lower().find(term) >= 0), default=0)
                snippet = clean[max(0, pos - 80):pos + 220] if clean else ""
                if pos > 80:
                    snippet = "…" + snippet
                if pos + 220 < len(clean):
                    snippet += "…"
                add_result(kind, title, path, snippet, clean[:600])

        user = None
        try:
            user = await self.auth.get_session(request)
        except Exception:
            user = None

        if user and category in {"all", "players"}:
            guild_ids = [str(x) for x in (getattr(user, "guild_ids", []) or [])]
            if guild_ids:
                player_docs = await self.bot.db.players.find(
                    {"guild_id": {"$in": guild_ids}},
                    {"user_id": 1, "username": 1, "global_name": 1, "game_name": 1, "game_id": 1, "about": 1, "location": 1}
                ).limit(100).to_list(length=100)
                for player in player_docs:
                    name = str(player.get("global_name") or player.get("username") or player.get("game_name") or "Driver")
                    profile = " ".join(str(player.get(k) or "") for k in ("game_name", "game_id", "about", "location"))
                    add_result("players", name, "/players", f"Driver profile • {profile[:220]}", profile)

        if user and category in {"all", "clubs"}:
            guild_ids = [str(x) for x in (getattr(user, "guild_ids", []) or [])]
            if guild_ids:
                async for club in self.bot.db.clubs.find(
                    {"guild_id": {"$in": guild_ids}},
                    {"name": 1, "about": 1, "guild_id": 1}
                ).sort("name_ci", 1).limit(100):
                    name = str(club.get("name") or "Club")
                    about = str(club.get("about") or "")
                    add_result("clubs", name, "/clubs", f"Club • {about[:220]}", about)

        if user and category in {"all", "tournaments"}:
            guild_ids = [str(x) for x in (getattr(user, "guild_ids", []) or [])]
            if guild_ids:
                async for tournament in self.bot.db.tournaments.find(
                    {"guild_id": {"$in": guild_ids}},
                    {"name": 1, "description": 1, "format": 1, "team_size": 1, "status": 1}
                ).sort("start_time", 1).limit(100):
                    name = str(tournament.get("name") or "Tournament")
                    details = " ".join(str(tournament.get(k) or "") for k in ("description", "format", "team_size", "status"))
                    add_result("tournaments", name, "/tournaments", f"Tournament • {details[:220]}", details)

        # Relevance: exact title/name matches first, then shorter snippets.
        needle = query.casefold()
        results.sort(key=lambda x: (0 if needle in x["title"].casefold() else 1, len(x["title"]), x["title"].casefold()))
        return web.json_response({"query": query, "type": category, "results": results[:30]})

    def _discord_community_counts(self, guild: Any) -> tuple[int, int]:
        """Return live human presence count and total member count for a guild.

        Presence data is authoritative for the live counter once the Discord
        presence intent is enabled. Bots are deliberately excluded from the
        human online count, while the total member count includes bots.
        """
        total = int(getattr(guild, "member_count", 0) or 0)
        if not total:
            total = len(list(getattr(guild, "members", []) or []))

        online = 0
        presences = getattr(guild, "presences", None)
        if presences is not None:
            seen: set[int] = set()
            for presence in list(presences or []):
                try:
                    status = str(getattr(presence, "status", "") or "").lower()
                    if status not in {"online", "idle", "dnd"}:
                        continue
                    user = getattr(presence, "user", None)
                    user_id = int(getattr(user, "id", 0) or 0)
                    if not user_id or user_id in seen:
                        continue
                    seen.add(user_id)
                    member = guild.get_member(user_id)
                    if bool(getattr(member, "bot", False) if member is not None else getattr(user, "bot", False)):
                        continue
                    online += 1
                except Exception:
                    continue
        else:
            # Compatibility fallback for test doubles/older discord.py objects.
            for member in list(getattr(guild, "members", []) or []):
                try:
                    if getattr(member, "bot", False):
                        continue
                    status = str(getattr(member, "status", "") or "").lower()
                    if status in {"online", "idle", "dnd"}:
                        online += 1
                except Exception:
                    continue

        return online, total

    async def discord_stats(self, request: web.Request) -> web.Response:
        """Return live Discord community counts for community banners and profile pages."""
        guilds = list(getattr(self.bot, "guilds", []) or [])
        if not guilds:
            return web.json_response({"online_members": 0, "server_members": 0, "available": False})
        # Prefer the largest connected guild, which is normally the main RSL community.
        guild = max(guilds, key=lambda g: int(getattr(g, "member_count", 0) or 0))
        online, total = self._discord_community_counts(guild)
        return web.json_response({
            "online_members": online,
            "server_members": total,
            "server_name": str(getattr(guild, "name", "") or ""),
            "available": True,
        })

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
            guild_ids = await self._live_guild_ids_for_user(user)
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
        payload = await self._json_object(request)
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
        payload = await self._json_object(request)
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

    async def save_setup_settings(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        try:
            payload = await self._json_object(request)
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        allowed = {key for key, _ in SETUP_CHANNELS + SETUP_ROLES} | {"timezone"} | {
            "tournament_main_channel_id", "tournament_log_channel_id", "tournament_bracket_channel_id",
            "tournament_admin_channel_id", "tournament_announcement_channel_id",
            "tournament_admin_role_id", "tournament_player_announcement_role_id",
        }
        clean = {key: str(payload[key]).strip() for key in allowed if payload.get(key)}
        role_name_payload = payload.get("achievement_role_names")
        if role_name_payload is not None and not isinstance(role_name_payload, dict):
            raise web.HTTPBadRequest(text="Invalid achievement role names.")
        role_name_payload = role_name_payload or {}
        managed_role_names = tuple(XP_LEVEL_ROLES.values()) + GAUNTLET_SEASONAL_ROLES + TOURNAMENT_SEASONAL_ROLES + PERMANENT_ACHIEVEMENT_ROLES
        achievement_names = {}
        for canonical in managed_role_names:
            value = str(role_name_payload.get(canonical, canonical)).strip() or canonical
            if len(value) > 100:
                raise web.HTTPBadRequest(text=f"Achievement role name is too long: {canonical}.")
            achievement_names[canonical] = value
        used_names = {}
        for canonical, desired in achievement_names.items():
            owner = used_names.get(desired.casefold())
            if owner and owner != canonical:
                raise web.HTTPBadRequest(text=f"Achievement role name '{desired}' is used more than once.")
            used_names[desired.casefold()] = canonical
        clean["achievement_role_names"] = achievement_names
        if clean.get("timezone") not in {None, *(value for _, value in TIMEZONE_LABELS)}:
            raise web.HTTPBadRequest(text="Invalid timezone.")
        if not clean:
            raise web.HTTPBadRequest(text="Nothing to save.")
        guild = next(g for g in self.bot.guilds if str(g.id) == guild_id)
        old_settings = await self.bot.db.settings.find_one({"_id": guild_id}, {"achievement_role_ids": 1}) or {}
        old_ids = old_settings.get("achievement_role_ids", {})
        achievement_ids = {}
        for canonical, desired in achievement_names.items():
            configured_id = str(old_ids.get(canonical) or "")
            role = guild.get_role(int(configured_id)) if configured_id.isdigit() else None
            if role is None:
                role = next((r for r in guild.roles if not r.is_default() and not r.managed and r.name == canonical), None)
            if role is not None:
                if role.name != desired:
                    try:
                        await role.edit(name=desired, reason="RSL achievement role name configured by staff")
                    except discord.Forbidden:
                        raise web.HTTPForbidden(text=f"Discord permission prevents renaming the {canonical} role.")
                    except Exception as exc:
                        raise web.HTTPBadRequest(text=f"Could not rename {canonical}: {exc}")
                achievement_ids[canonical] = str(role.id)
        clean["achievement_role_ids"] = achievement_ids
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
        tournament_channels = (
            ("tournament_main_channel_id", "Tournament player channel"),
            ("tournament_log_channel_id", "Tournament log channel"),
            ("tournament_bracket_channel_id", "Tournament bracket/results channel"),
            ("tournament_admin_channel_id", "Tournament admin channel"),
            ("tournament_announcement_channel_id", "Tournament announcement channel"),
        )
        tournament_roles = (
            ("tournament_admin_role_id", "Tournament admin role"),
            ("tournament_player_announcement_role_id", "Tournament driver role"),
        )
        for key, label in tournament_channels:
            value = clean.get(key)
            if value:
                try: valid = guild.get_channel(int(value))
                except (TypeError, ValueError): valid = None
                if valid is None: raise web.HTTPBadRequest(text=f"Invalid channel for {label}.")
        for key, label in tournament_roles:
            value = clean.get(key)
            if value:
                try: valid = guild.get_role(int(value))
                except (TypeError, ValueError): valid = None
                if valid is None: raise web.HTTPBadRequest(text=f"Invalid role for {label}.")
        await self.bot.db.settings.update_one({"_id": guild_id}, {"$set": clean}, upsert=True)
        await self._audit(guild_id, user.user_id, "Web setup updated")
        return web.json_response({"ok": True, "settings": clean})

    async def save_season(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        try:
            payload = await self._json_object(request)
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        if "automatic_season_end" in payload:
            value = bool(payload["automatic_season_end"])
            await self.bot.db.settings.update_one({"_id": guild_id}, {"$set": {"automatic_season_end": value}}, upsert=True)
            await self._audit(guild_id, user.user_id, f"Web season automation {'enabled' if value else 'disabled'}")
        return web.json_response({"ok": True})

    async def _audit(self, guild_id: str, user_id: str, action: str) -> None:
        await self.bot.db.system_events.insert_one({"guild_id": guild_id, "source": "web", "user_id": user_id, "action": action})

    async def public_driver_career(self, request: web.Request) -> web.Response:
        """Return safe public career records for the unified Driver Profile."""
        _, guild_id, _ = await self.require_guild_member(request)
        uid = str(request.match_info["user_id"]).strip()
        if not uid.isdigit():
            raise web.HTTPNotFound(text="Driver not found.")
        driver = await self.players.get_player(guild_id, uid)
        # A Discord member can have a public RSL profile before they have a Gauntlet driver record.
        # Keep the profile usable and show their Discord identity instead of returning "Driver not found".
        if driver is None:
            driver = {}
        season = await get_current_season_number(str(guild_id))
        elo = int(driver.get("elo", 1000) or 1000)
        higher = await self.bot.db.drivers.count_documents({"guild_id": str(guild_id), "season_registered": True, "season_number": season, "elo": {"$gt": elo}})
        matches = await self.bot.db.matches.find({
            "guild_id": str(guild_id), "reverted": {"$ne": True},
            "$or": [{"challenger_id": uid}, {"opponent_id": uid}],
        }).sort("timestamp", -1).to_list(length=1000)
        wins = sum(1 for m in matches if str(m.get("w_id")) == uid)
        losses = sum(1 for m in matches if str(m.get("l_id")) == uid)
        race_wins = sum(max(0, min(5, int(m.get("courses_beat", 0) or 0))) if str(m.get("w_id")) == uid else max(0, 5 - min(5, int(m.get("courses_beat", 0) or 0))) for m in matches if str(m.get("w_id")) == uid or str(m.get("l_id")) == uid)
        race_losses = max(0, (wins + losses) * 5 - race_wins)
        dominance = driver.get("rsl_dominance") or {}
        buckets = dominance.get("score_buckets") or {}
        try:
            division = get_division_for_pi(int(driver.get("garage_pi", 0) or 0)).get("name", "Unranked")
        except Exception:
            division = "Unranked"
        lap_rows = await self.bot.db.lap_times.find({"guild_id": str(guild_id), "user_id": uid}).sort("best_ms", 1).to_list(length=100)
        track_records = 0
        lap_stats = []
        for row in lap_rows[:10]:
            track = str(row.get("track", "Unknown"))
            best_ms = int(row.get("best_ms", 0) or 0)
            record_id = re.sub(r"[^a-z0-9]+", "_", track.lower()).strip("_")
            global_rec = await self.bot.db.map_records.find_one({"_id": record_id})
            is_record = bool(global_rec and str(global_rec.get("user_id")) == uid and int(global_rec.get("best_ms", 10**18)) == best_ms)
            if is_record: track_records += 1
            lap_stats.append({"track": track, "best_lap_time": row.get("best_lap_time") or row.get("time") or "—", "track_record": is_record})
        tournaments = []
        async for reg in self.bot.db.tournament_registrations.find({"guild_id": str(guild_id), "user_id": uid}).sort("registered_at", -1):
            tid = str(reg.get("tournament_id", ""))
            try:
                from bson import ObjectId
                tournament = await self.bot.db.tournaments.find_one({"_id": ObjectId(tid)})
            except Exception:
                tournament = None
            if not tournament: continue
            bracket = tournament.get("bracket") or {}
            groups = bracket.get("rounds") or bracket.get("winners") or []
            tw = tl = tp = 0
            for group in groups:
                for match in group.get("matches", []):
                    slots = [str(x) for x in (match.get("player_slots") or []) if x]
                    if uid not in slots or str(match.get("status", "")) != "completed": continue
                    winner = str(match.get("winner_id", ""))
                    if not winner: continue
                    tp += 1
                    if winner == uid: tw += 1
                    else: tl += 1
            status = str(tournament.get("status", "unknown"))
            tournaments.append({
                "id": tid, "name": str(tournament.get("name", "Tournament")),
                "format": str(tournament.get("format", "tournament")).replace("_", " ").title(),
                "status": status.replace("_", " ").title(), "played": tp, "wins": tw, "losses": tl,
                "record": f"{tw}-{tl}", "start_time": str(tournament.get("start_time", "")),
            })
        season_registered = bool(driver.get("season_registered")) and int(driver.get("season_number", 0) or 0) == season
        season_archives = []
        async for archive in self.bot.db.season_history.find({"guild_id": str(guild_id)}).sort("season_number", -1).limit(12):
            rows = archive.get("standings") or []
            mine = next((r for r in rows if str(r.get("user_id")) == uid), None)
            if mine is None:
                continue
            season_archives.append({
                "season_number": int(archive.get("season_number", 0) or 0),
                "rank": int(mine.get("rank", 0) or 0) or None,
                "points": int(mine.get("season_points", mine.get("gauntlet_points", 0)) or 0),
                "wins": int(mine.get("season_wins", mine.get("wins", 0)) or 0),
                "losses": int(mine.get("season_losses", mine.get("losses", 0)) or 0),
                "played": int(mine.get("season_played", mine.get("played", 0)) or 0),
                "races_won": int(mine.get("season_races_won", mine.get("races_won", 0)) or 0),
            })
        record_rows = await self.bot.db.drivers.find({"guild_id": str(guild_id)}).to_list(length=5000)
        records = {
            "highest_elo": max((int(r.get("elo", 1000) or 1000) for r in record_rows), default=1000),
            "most_career_wins": max((int(r.get("career_wins", 0) or 0) for r in record_rows), default=0),
            "longest_current_streak": max((int(r.get("streak", 0) or 0) for r in record_rows), default=0),
            "most_season_points": max((int(r.get("season_points", 0) or 0) for r in record_rows), default=0),
        }
        return web.json_response({
            "gauntlet": {
                "season": season, "division": division, "registered": season_registered,
                "rank": higher + 1 if season_registered else None, "elo": elo,
                "wins": wins, "losses": losses, "played": wins + losses,
                "win_rate": round((wins / (wins + losses) * 100), 1) if wins + losses else 0.0,
                "streak": int(driver.get("streak", 0) or 0),
                "race_wins": race_wins, "race_losses": race_losses,
                "score_buckets": {k: int(buckets.get(k, 0) or 0) for k in ("5-0","4-1","3-2","2-3","1-4","0-5")},
                "season_points": int(driver.get("season_points", 0) or 0),
                "season_matches": int(driver.get("season_matches", 0) or 0),
                "season_races_won": int(driver.get("season_races_won", 0) or 0),
                "track_records": track_records,
                "recent_matches": [{
                    "opponent_id": str(m.get("opponent_id") if str(m.get("challenger_id")) == uid else m.get("challenger_id")),
                    "result": "WIN" if str(m.get("w_id")) == uid else "LOSS",
                    "score": f"{int(m.get('courses_beat', 0) or 0)}/5",
                    "timestamp": m.get("timestamp") or 0,
                } for m in matches[:10]],
            },
            "laps": lap_stats,
            "tournaments": tournaments[:50],
            "tournament_summary": {
                "events": len(tournaments),
                "played": sum(int(t["played"]) for t in tournaments),
                "wins": sum(int(t["wins"]) for t in tournaments),
                "losses": sum(int(t["losses"]) for t in tournaments),
            },
            "season_history": season_archives,
            "rsl_records": records,
        })

    async def public_status(self, request: web.Request) -> web.Response:
        heartbeat = await self.bot.db.system_events.find_one({"_id": "production_heartbeat"}) or {}
        db_ok = False
        try:
            await self.bot.db.command("ping")
            db_ok = True
        except Exception:
            db_ok = False
        heartbeat_ok = bool(heartbeat) and time.time() - float(heartbeat.get("timestamp", 0) or 0) < 300
        discord_ok = bool(getattr(self.bot, "is_ready", lambda: False)())
        auth_ok = bool(getattr(self.auth, "configured", False))
        competition_ok = bool(heartbeat_ok and discord_ok and db_ok)
        notifications_ok = not bool(getattr(self.bot, "last_health_error", None))
        snapshot = public_status_snapshot(
            web_ok=True,
            discord_ok=discord_ok,
            database_ok=db_ok,
            competition_ok=competition_ok,
            auth_ok=auth_ok,
            notifications_ok=notifications_ok,
            release=current_release_revision(),
        )
        snapshot["heartbeat"] = heartbeat_ok
        return web.json_response(snapshot)

    async def help_page(self, request: web.Request) -> web.Response:
        """Render the public Help Center page."""
        return await self._page_response("help.html", request)

    async def rules_page(self, request: web.Request) -> web.Response:
        """Render the public RSL Rules Center page."""
        return await self._page_response("rules.html", request)

    async def legal_page(self, request: web.Request) -> web.Response:
        """Render the public Legal Center page."""
        return await self._page_response("legal.html", request)
