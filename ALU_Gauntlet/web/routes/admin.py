import inspect
from bson import ObjectId
from gridfs.asynchronous import AsyncGridFSBucket
import ipaddress
import socket
from urllib.parse import urlsplit
"""RSL web admin route family."""
from .._web_context import *

class AdminRoutesMixin:
    async def _admin_guilds_data(self, user: Any) -> list[dict[str, Any]]:
        rows = []
        live_guilds = await self._connected_guilds_for_user(user)
        for gid, guild in live_guilds.items():
            allowed = await self._is_live_guild_staff(user, gid, guild)
            if allowed:
                rows.append({
                    "id": gid,
                    "name": str(getattr(guild, "name", gid)),
                    "member_count": int(getattr(guild, "member_count", 0) or len(list(getattr(guild, "members", []) or []))),
                })
        rows.sort(key=lambda item: item["name"].casefold())
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

    async def upload_brand_asset(self, request: web.Request) -> web.Response:
        """Accept common image formats and normalize every stored brand asset to PNG."""
        user, guild_id, _ = await self.require_admin(request)
        max_size = 8 * 1024 * 1024
        max_pixels = 4096 * 4096
        if request.content_length and request.content_length > max_size:
            raise web.HTTPRequestEntityTooLarge(max_size=max_size, actual_size=request.content_length)
        try:
            reader = await request.multipart()
            field = await reader.next()
        except Exception as exc:
            log.exception("Brand asset multipart parsing failed for guild %s", guild_id)
            raise web.HTTPBadRequest(text=f"Invalid image upload: {str(exc)[:200]}") from exc
        if field is None or field.name != "file":
            raise web.HTTPBadRequest(text="Send an image in the 'file' field.")

        original_name = Path(field.filename or "brand-image").name[:120]
        content_type = str(field.headers.get("Content-Type", "") or "").lower().split(";", 1)[0]
        upload_target = str(request.query.get("target") or "").strip().lower()
        data = await field.read()
        if not data:
            raise web.HTTPBadRequest(text="The selected image is empty.")
        if len(data) > max_size:
            raise web.HTTPRequestEntityTooLarge(max_size=max_size, actual_size=len(data))
        # Multipart readers may return bytearray; BSON requires bytes for binary fields.
        data = bytes(data)

        # Do not trust the filename or browser MIME type. Pillow decodes the actual
        # image bytes, then we write a real PNG regardless of the original format.
        try:
            with Image.open(BytesIO(data)) as source:
                if int(getattr(source, "width", 0) or 0) * int(getattr(source, "height", 0) or 0) > max_pixels:
                    raise ValueError("image dimensions exceed the 4096×4096 pixel safety limit")
                source.load()
                image = ImageOps.exif_transpose(source)
                if image.mode not in {"RGB", "RGBA"}:
                    image = image.convert("RGBA")

                # Normalize uploads to sensible dimensions for their destination
                # while preserving aspect ratio.
                target_sizes = {
                    "logo_url": (512, 512),
                    "favicon_url": (128, 128),
                    "hero_url": (1920, 900),
                    "welcome_url": (1400, 800),
                    "gauntlet_url": (1400, 800),
                    "tournament_url": (1400, 800),
                    "club_url": (1400, 800),
                    "login_url": (1400, 800),
                    "background_url": (1920, 1080),
                    "custom_icon": (36, 36),
                }
                target_size = target_sizes.get(upload_target)
                if target_size:
                    image.thumbnail(target_size, Image.Resampling.LANCZOS)

                output = BytesIO()
                image.save(output, format="PNG", optimize=True)
                png_data = output.getvalue()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise web.HTTPBadRequest(text="The selected file is not a supported image.") from exc
        except Exception as exc:
            log.exception("Brand asset image conversion failed for guild %s", guild_id)
            raise web.HTTPBadRequest(text=f"Unable to convert the selected image to PNG: {str(exc)[:160]}") from exc

        if not png_data:
            raise web.HTTPBadRequest(text="The selected image could not be converted to PNG.")
        if len(png_data) > max_size:
            raise web.HTTPRequestEntityTooLarge(max_size=max_size, actual_size=len(png_data))

        stem = Path(original_name).stem or "brand-image"
        filename = f"{stem[:110]}.png"
        asset_id = hashlib.sha256(f"{guild_id}:{filename}:{time.time()}".encode() + png_data).hexdigest()[:32]
        document = {
            "_id": asset_id,
            "guild_id": str(guild_id),
            "filename": filename,
            "content_type": "image/png",
            "created_at": time.time(),
            "created_by": str(user.user_id),
            "source_filename": original_name,
            "source_content_type": content_type,
        }
        try:
            # Production Mongo stores normalized media in GridFS rather than
            # embedding binary payloads in ordinary documents. Lightweight test
            # databases without a Mongo client keep the legacy bytes fallback.
            client = getattr(self.bot.db, "client", None)
            if client is not None:
                bucket = AsyncGridFSBucket(self.bot.db, bucket_name="web_brand_assets")
                gridfs_id = await bucket.upload_from_stream(
                    filename,
                    png_data,
                    metadata={"guild_id": str(guild_id), "asset_id": asset_id, "content_type": "image/png"},
                )
                document["storage"] = "gridfs"
                document["gridfs_id"] = str(gridfs_id)
            else:
                document["storage"] = "inline"
                document["data"] = png_data
            await self.bot.db.web_brand_assets.insert_one(document)
        except Exception as exc:
            log.exception("Brand asset database save failed for guild %s", guild_id)
            raise web.HTTPServiceUnavailable(text=f"Unable to save PNG upload: {str(exc)[:200]}") from exc
        url = f"/assets/tenant/{guild_id}/{asset_id}"
        try:
            await self._audit(
                guild_id,
                user.user_id,
                f"Web brand asset uploaded and normalized to PNG: {filename}",
            )
        except Exception:
            log.exception("Brand asset audit logging failed for guild %s", guild_id)
        return web.json_response({
            "ok": True,
            "asset_id": asset_id,
            "url": url,
            "filename": filename,
            "content_type": "image/png",
            "source_filename": original_name,
            "source_content_type": content_type,
        })

    async def serve_brand_asset(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        guild_id = str(request.match_info["guild_id"])
        if guild_id not in {str(x) for x in getattr(user,"guild_ids",[])}:
            raise web.HTTPForbidden(text="You are not a member of this server.")
        asset_id = str(request.match_info["asset_id"])
        asset = await self.bot.db.web_brand_assets.find_one({"_id":asset_id,"guild_id":guild_id})
        if not asset:
            raise web.HTTPNotFound(text="Brand asset not found.")
        body = asset.get("data") or b""
        if asset.get("storage") == "gridfs" and asset.get("gridfs_id"):
            try:
                bucket = AsyncGridFSBucket(self.bot.db, bucket_name="web_brand_assets")
                stream = await bucket.open_download_stream(ObjectId(str(asset["gridfs_id"])))
                response = web.StreamResponse(status=200, headers={
                    "Content-Type": str(asset.get("content_type") or "application/octet-stream"),
                    "Cache-Control": "public, max-age=3600",
                })
                if getattr(stream, "length", None) is not None:
                    response.content_length = int(stream.length)
                self._apply_security_headers(request, response)
                await response.prepare(request)
                try:
                    while True:
                        chunk = await stream.read(64 * 1024)
                        if not chunk:
                            break
                        await response.write(chunk)
                    await response.write_eof()
                    return response
                finally:
                    close = getattr(stream, "close", None)
                    if close is not None:
                        result = close()
                        if inspect.isawaitable(result):
                            await result
            except Exception as exc:
                log.exception("Brand asset GridFS read failed for %s", asset_id)
                raise web.HTTPServiceUnavailable(text="Brand asset is temporarily unavailable.") from exc
        return web.Response(body=body,content_type=str(asset.get("content_type") or "application/octet-stream"),headers={"Cache-Control":"public, max-age=3600"})

    async def admin_csp_diagnostics(self, request: web.Request) -> web.Response:
        """Return a privacy-safe aggregate of recent CSP reports for authorized staff."""
        _, guild_id, _guild = await self.require_admin(request)
        try:
            limit = max(1, min(500, int(request.query.get("limit", "250") or 250)))
            days = max(1, min(14, int(request.query.get("days", "14") or 14)))
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="limit and days must be integers.")

        from datetime import datetime, timedelta, timezone
        from urllib.parse import urlsplit

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        rows = await self.bot.db.csp_reports.find(
            {"created_at": {"$gte": cutoff}},
            {"_id": 0, "created_at": 1, "report": 1},
        ).sort("created_at", -1).limit(limit).to_list(length=limit)

        def host_or_kind(value: Any) -> str:
            raw = str(value or "").strip()
            if not raw:
                return ""
            if raw in {"inline", "eval", "wasm-eval", "data", "blob", "self"}:
                return raw
            try:
                parsed = urlsplit(raw)
                host = str(parsed.hostname or "").lower()
                return host[:253] if host else raw[:80]
            except Exception:
                return raw[:80]

        def add_count(bucket: dict[str, int], value: str) -> None:
            if value:
                bucket[value] = bucket.get(value, 0) + 1

        blocked: dict[str, int] = {}
        sources: dict[str, int] = {}
        directives: dict[str, int] = {}
        documents: dict[str, int] = {}
        dispositions: dict[str, int] = {}
        for row in rows:
            report = row.get("report") if isinstance(row.get("report"), dict) else {}
            add_count(blocked, host_or_kind(report.get("blocked-uri")))
            add_count(sources, host_or_kind(report.get("source-file")))
            add_count(directives, str(report.get("effective-directive") or report.get("violated-directive") or "").strip()[:120])
            add_count(documents, host_or_kind(report.get("document-uri")))
            add_count(dispositions, str(report.get("disposition") or "").strip()[:40])

        def ranked(bucket: dict[str, int], count: int = 50) -> list[dict[str, Any]]:
            return [
                {"value": key, "count": value}
                for key, value in sorted(bucket.items(), key=lambda item: (-item[1], item[0]))[:count]
            ]

        # Reports are intentionally aggregated: no client IPs, full URLs, script
        # samples, or raw CSP payloads are exposed through this staff endpoint.
        return web.json_response({
            "ok": True,
            "guild_id": str(guild_id),
            "window_days": days,
            "reports_examined": len(rows),
            "truncated": len(rows) >= limit,
            "blocked_hosts": ranked(blocked),
            "source_hosts": ranked(sources),
            "document_hosts": ranked(documents),
            "directives": ranked(directives),
            "dispositions": ranked(dispositions),
        })

    async def admin_diagnostics(self, request: web.Request) -> web.Response:
        _, guild_id, guild = await self.require_admin(request)
        checks=[{"name":"Discord connection","ok":guild is not None},{"name":"MongoDB","ok":False}]
        try:
            await self.bot.db.command("ping"); checks[-1]["ok"]=True
        except Exception as exc:
            checks[-1]["detail"]=str(exc)[:200]
        settings = await self.bot.db.settings.find_one({"_id":guild_id}) or {}
        checks.append({"name":"Branding configuration","ok":bool(self._merge_branding(settings.get("web_branding"))["identity"]["name"])})

        # Reuse the canonical operational collections/indexes for a lightweight
        # integrity check. This is advisory and never mutates competition state.
        required = ("drivers","matches","active_challenges","pending","system_events","season_state")
        existing = set(await self.bot.db.list_collection_names())
        missing = [name for name in required if name not in existing]
        checks.append({
            "name":"Core collections",
            "ok":not missing,
            "detail":("Missing: " + ", ".join(missing)) if missing else f"{len(required)} verified",
        })
        if not missing:
            try:
                driver_issues = 0
                async for driver in self.bot.db.drivers.find({"guild_id": guild_id}, {"career_wins": 1, "career_played": 1}):
                    wins = int(driver.get("career_wins", 0) or 0)
                    played = int(driver.get("career_played", 0) or 0)
                    if wins < 0 or played < 0 or wins > played:
                        driver_issues += 1
                checks.append({"name":"Driver record invariants","ok":driver_issues == 0,"detail":"all driver counters valid" if driver_issues == 0 else f"{driver_issues} invalid driver record(s)"})
            except Exception as exc:
                checks.append({"name":"Driver record invariants","ok":False,"detail":str(exc)[:180]})

            try:
                match_issues = 0
                async for match in self.bot.db.matches.find({"guild_id": guild_id, "reverted": {"$ne": True}}, {"settlement_status": 1, "w_id": 1, "l_id": 1, "courses_beat": 1}):
                    if str(match.get("settlement_status") or "") == "completed":
                        winner = str(match.get("w_id") or "")
                        loser = str(match.get("l_id") or "")
                        if not winner or not loser or winner == loser:
                            match_issues += 1
                    try:
                        courses = int(match.get("courses_beat", 0) or 0)
                        if courses < 0 or courses > 5:
                            match_issues += 1
                    except (TypeError, ValueError):
                        match_issues += 1
                checks.append({"name":"Match settlement invariants","ok":match_issues == 0,"detail":"match records valid" if match_issues == 0 else f"{match_issues} invalid match record(s)"})
            except Exception as exc:
                checks.append({"name":"Match settlement invariants","ok":False,"detail":str(exc)[:180]})

            try:
                defense_pending = await self.bot.db.drivers.count_documents({"guild_id": guild_id, "defense_review_pending": True, "defense_review_payload": {"$exists": False}})
                reference_pending = await self.bot.db.reference_pending.count_documents({"guild_id": guild_id, "status": "pending"})
                media_pending = await self.bot.db.tournament_media.count_documents({"guild_id": guild_id, "status": "pending"})
                checks.append({"name":"Evidence/review queues","ok":defense_pending == 0,"detail":f"{reference_pending} reference + {media_pending} tournament media item(s) pending; {defense_pending} defense flag(s) missing payload"})
            except Exception as exc:
                checks.append({"name":"Evidence/review queues","ok":False,"detail":str(exc)[:180]})

            try:
                event_indexes = set((await self.bot.db.system_events.index_information()).keys())
                checks.append({
                    "name":"Audit event index",
                    "ok":"guild_id_1_timestamp_-1" in event_indexes,
                    "detail":"guild/time index verified" if "guild_id_1_timestamp_-1" in event_indexes else "guild/time index missing",
                })
            except Exception as exc:
                checks.append({"name":"Audit event index","ok":False,"detail":str(exc)[:180]})

            try:
                season = await self.bot.db.season_state.find_one({"_id":f"guild_{guild_id}"}) or {}
                if season:
                    starts = float(season.get("starts_at",0) or 0)
                    ends = float(season.get("ends_at",0) or 0)
                    valid_window = not starts or not ends or ends > starts
                    checks.append({"name":"Season state","ok":valid_window,"detail":"season window valid" if valid_window else "season end precedes start"})
                else:
                    checks.append({"name":"Season state","ok":True,"detail":"no season scheduled"})
            except Exception as exc:
                checks.append({"name":"Season state","ok":False,"detail":str(exc)[:180]})

            try:
                stale = await self.bot.db.active_challenges.count_documents({
                    "guild_id":guild_id,
                    "status":"processing",
                    "processing_at":{"$lt":time.time()-900},
                })
                checks.append({"name":"Settlement reservations","ok":stale == 0,"detail":"no stale reservations" if stale == 0 else f"{stale} stale reservation(s) require review"})
            except Exception as exc:
                checks.append({"name":"Settlement reservations","ok":False,"detail":str(exc)[:180]})

        return web.json_response({"ok":all(x["ok"] for x in checks),"checks":checks,"guild":{"id":guild_id,"name":guild.name,"members":getattr(guild,"member_count",0)}})

    async def admin_operations(self, request: web.Request) -> web.Response:
        """Unified staff operations surface for safe mode, integrity, season finalization and release history."""
        user, guild_id, _guild = await self.require_admin(request)
        action = str(request.query.get("action") or "").strip().lower()
        if request.method == "GET" and action == "status":
            settings = await self.bot.db.settings.find_one({"_id": guild_id}) or {}
            mode = settings.get("maintenance_mode") or {}
            state = await self.bot.db.season_state.find_one({"_id": f"guild_{guild_id}"}) or {}
            return web.json_response({
                "maintenance": mode,
                "season": {
                    "number": int(state.get("season_number", 1) or 1),
                    "active": bool(state.get("season_active")),
                    "starts_at": float(state.get("starts_at", 0) or 0),
                    "ends_at": float(state.get("ends_at", 0) or 0),
                },
                "release_sha": current_release_revision(),
            })
        if request.method == "GET" and action == "reliability":
            settings = await self.bot.db.settings.find_one({"_id": guild_id}) or {}
            snapshot = await build_reliability_snapshot(self.bot.db, guild_id, settings=settings)
            snapshot["release_sha"] = current_release_revision()
            snapshot["discord_ready"] = bool(getattr(self.bot, "is_ready", lambda: False)())
            snapshot["readiness"] = readiness_check({
                "database": bool(snapshot["economy"].get("ok") is not False),
                "discord": snapshot["discord_ready"],
                "economy_integrity": bool(snapshot["economy"].get("ok")),
                "backup_evidence": True if snapshot["backup"].get("available") else None,
                "competition_safe_mode": True,
            })
            return web.json_response(snapshot)

        if request.method == "GET" and action == "evidence":
            queues = []
            drivers = await self.bot.db.drivers.find({"guild_id": guild_id, "defense_review_pending": True}).to_list(length=50)
            for d in drivers:
                payload = d.get("defense_review_payload") or {}
                queues.append({
                    "type": "gauntlet_defense",
                    "id": str(payload.get("submission_id") or d.get("_id") or ""),
                    "user_id": str(d.get("user_id") or ""),
                    "submitted_at": payload.get("submitted_at") or d.get("updated_at"),
                    "evidence": payload.get("video_url") or payload.get("proof_url") or payload.get("video_reference") or "",
                    "status": "pending",
                })
            async for row in self.bot.db.reference_pending.find({"guild_id": guild_id, "status": "pending"}).sort("created_at", -1).limit(50):
                queues.append({
                    "type": "gauntlet_reference", "id": str(row.get("_id") or ""),
                    "user_id": str(row.get("user_id") or ""), "submitted_at": row.get("created_at"),
                    "evidence": str(row.get("video_reference") or row.get("proof_url") or ""), "status": "pending",
                })
            async for row in self.bot.db.tournament_media.find({"guild_id": guild_id, "status": "pending"}).sort("created_at", -1).limit(50):
                queues.append({
                    "type": "tournament_media", "id": str(row.get("_id") or ""),
                    "user_id": str(row.get("uploaded_by") or row.get("submitted_by") or row.get("user_id") or ""),
                    "submitted_at": row.get("created_at"),
                    "evidence": str(row.get("url") or row.get("media_url") or ""), "status": "pending",
                })
            return web.json_response({"queue": queues, "counts": {
                "total": len(queues),
                "gauntlet_defense": sum(1 for x in queues if x["type"] == "gauntlet_defense"),
                "gauntlet_reference": sum(1 for x in queues if x["type"] == "gauntlet_reference"),
                "tournament_media": sum(1 for x in queues if x["type"] == "tournament_media"),
            }})
        if request.method == "GET" and action == "releases":
            events = []
            cursor = self.bot.db.system_events.find({"guild_id": guild_id}).sort("timestamp", -1).limit(200)
            async for row in cursor:
                label = str(row.get("event_type") or row.get("action") or "")
                if any(term in label.casefold() for term in ("release", "deploy", "rollback", "revision")):
                    events.append({
                        "timestamp": float(row.get("timestamp", 0) or 0),
                        "event": label,
                        "actor_id": str(row.get("actor_id") or row.get("user_id") or ""),
                        "target_id": str(row.get("target_id") or ""),
                    })
            return web.json_response({"current_revision": current_release_revision(), "events": events[:50]})
        if request.method == "POST":
            try:
                payload = await self._json_object(request)
            except Exception as exc:
                raise web.HTTPBadRequest(text="Invalid JSON body.") from exc
            action = str(payload.get("action") or "").strip().lower()
            if action == "maintenance":
                enabled = bool(payload.get("enabled"))
                message = str(payload.get("message") or "").strip()[:500]
                mode = await set_maintenance_mode(self.bot.db, guild_id, enabled, message, user.user_id)
                return web.json_response({"ok": True, "guild_id": str(guild_id), "maintenance": mode})

            if action == "recovery_checkpoint":
                checkpoint = await create_recovery_checkpoint(
                    self.bot.db,
                    guild_id,
                    str(user.user_id),
                    release=current_release_revision(),
                )
                await self._audit(
                    guild_id,
                    str(user.user_id),
                    "Created RSL recovery checkpoint " + str(checkpoint.get("id")),
                )
                return web.json_response({
                    "ok": True,
                    "checkpoint": {
                        "id": checkpoint.get("id"),
                        "created_at": checkpoint.get("created_at"),
                        "release": checkpoint.get("release"),
                        "collection_counts": checkpoint.get("collection_counts", {}),
                    },
                })

            if action == "season_preview":
                state = await self.bot.db.season_state.find_one({"_id": f"guild_{guild_id}"}) or {}
                season_number = int(state.get("season_number", 1) or 1)
                drivers = await self.bot.db.drivers.count_documents({"guild_id": guild_id, "season_registered": True, "season_number": season_number})
                completed = await self.bot.db.matches.count_documents({"guild_id": guild_id, "settlement_status": "completed", "reverted": {"$ne": True}})
                return web.json_response({
                    "season": season_number, "registered_drivers": drivers, "completed_matches_available": completed,
                    "active": bool(state.get("season_active")), "ends_at": float(state.get("ends_at", 0) or 0),
                })
            if action == "season_finalize":
                from ..cogs.season import trigger_global_season_end
                state = await self.bot.db.season_state.find_one({"_id": f"guild_{guild_id}"}) or {}
                season_number = int(state.get("season_number", 1) or 1)
                claim = await self.bot.db.season_state.update_one(
                    {"_id": f"guild_{guild_id}", "season_number": season_number, "admin_finalize_lock_at": {"$exists": False}},
                    {"$set": {"admin_finalize_lock_at": time.time(), "admin_finalize_actor": str(user.user_id)}},
                )
                if claim.modified_count != 1:
                    raise web.HTTPConflict(text="Season finalization is already being processed.")
                try:
                    result = await trigger_global_season_end(
                        guild_id=guild_id, forced_interaction=None,
                        start_next_season=bool(payload.get("start_next_season", False)),
                    )
                except Exception:
                    await self.bot.db.season_state.update_one(
                        {"_id": f"guild_{guild_id}", "season_number": season_number},
                        {"$unset": {"admin_finalize_lock_at": "", "admin_finalize_actor": ""}},
                    )
                    raise
                await self.bot.db.season_state.update_one(
                    {"_id": f"guild_{guild_id}"},
                    {"$unset": {"admin_finalize_lock_at": "", "admin_finalize_actor": ""}},
                )
                await self._audit(guild_id, str(user.user_id), f"Season {season_number} finalized from web administration")
                return web.json_response({"ok": True, "result": result})
        raise web.HTTPBadRequest(text="Unsupported administration operation.")

    async def admin_activity_timeline(self, request: web.Request) -> web.Response:
        """Return a safe public activity timeline for one driver."""
        _, guild_id, _ = await self.require_guild_member(request)
        uid = str(request.match_info["user_id"]).strip()
        if not uid.isdigit():
            raise web.HTTPNotFound(text="Driver not found.")
        events = []
        matches = await self.bot.db.matches.find({
            "guild_id": guild_id, "reverted": {"$ne": True},
            "$or": [{"challenger_id": uid}, {"opponent_id": uid}],
        }).sort("timestamp", -1).limit(20).to_list(length=20)
        for m in matches:
            won = str(m.get("w_id") or "") == uid
            lost = str(m.get("l_id") or "") == uid
            if not won and not lost:
                continue
            events.append({
                "kind": "gauntlet_match", "title": "Gauntlet Win" if won else "Gauntlet Loss",
                "detail": f"{int(m.get('courses_beat', 0) or 0)}-course result",
                "timestamp": m.get("timestamp", 0), "match_id": str(m.get("_id") or ""),
            })
        async for archive in self.bot.db.season_history.find({"guild_id": guild_id}).sort("closed_at", -1).limit(20):
            mine = next((x for x in (archive.get("standings") or []) if str(x.get("user_id")) == uid), None)
            if mine:
                events.append({
                    "kind": "season",
                    "title": f"Season {int(archive.get('season_number', 0) or 0)} completed",
                    "detail": f"Rank #{int(mine.get('rank', 0) or 0) or '—'} • {int(mine.get('season_points', 0) or 0)} points",
                    "timestamp": archive.get("closed_at", 0),
                })
        events.sort(key=lambda x: float(x.get("timestamp", 0) or 0), reverse=True)
        return web.json_response({"events": events[:30]})

    async def admin_audit(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_admin(request)
        rows=[]
        cursor=self.bot.db.system_events.find({"guild_id":guild_id}).sort("timestamp",-1).limit(50)
        async for row in cursor:
            rows.append({
                "id":str(row.get("_id","")),
                "source":str(row.get("source") or "system"),
                "user_id":str(row.get("user_id") or row.get("actor_id") or ""),
                "action":str(row.get("action") or row.get("event_type") or "System event"),
                "timestamp":float(row.get("timestamp",0) or 0),
            })
        return web.json_response({"events":rows})

    async def admin_fairness(self, request: web.Request) -> web.Response:
        """Return staff-only advisory Gauntlet fairness review signals."""
        user, guild_id, _ = await self.require_admin(request)
        report = await build_fairness_review(self.bot.db, str(guild_id), limit=100)
        await self._audit(str(guild_id), str(user.user_id), "Viewed Gauntlet fairness review")
        return web.json_response(report)

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

    async def admin_maintenance(self, request: web.Request) -> web.StreamResponse:
        user, guild_id, _guild = await self.require_admin(request)
        settings = await self.bot.db.settings.find_one({"_id": str(guild_id)}) or {}
        if request.method == "GET":
            mode = (settings.get("maintenance_mode") or {})
            return web.json_response({"ok": True, "guild_id": str(guild_id), "maintenance": mode})
        try:
            payload = await self._json_object(request)
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON payload.")
        enabled = bool(payload.get("enabled"))
        message = str(payload.get("message") or "").strip()[:500]
        mode = await set_maintenance_mode(self.bot.db, guild_id, enabled, message, user.user_id)
        return web.json_response({"ok": True, "guild_id": str(guild_id), "maintenance": mode})

    async def admin_ticket_settings(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_admin(request)
        from ..cogs.tickets import settings_for
        if request.method == "GET":
            return web.json_response(await settings_for(str(guild_id)))
        payload = await self._json_object(request)
        types = payload.get("types") or []
        if len(types) > 25:
            raise web.HTTPBadRequest(text="A maximum of 25 ticket types is supported.")
        clean_types = []
        for item in types:
            key = re.sub(r"[^a-z0-9_-]", "", str(item.get("key") or "").lower())[:32]
            if not key:
                continue
            questions = [str(x)[:200] for x in (item.get("questions") or [])[:5]]
            translations = {}
            for locale, data in (item.get("translations") or {}).items():
                if not isinstance(data, dict):
                    continue
                loc = re.sub(r"[^a-zA-Z-]", "", str(locale))[:12].replace("_", "-").lower()
                if not loc:
                    continue
                translations[loc] = {
                    "label": str(data.get("label") or "")[:80],
                    "description": str(data.get("description") or "")[:120],
                    "questions": [str(x)[:200] for x in (data.get("questions") or [])[:5]],
                }
            clean_types.append({
                "key": key,
                "label": str(item.get("label") or key.title())[:80],
                "emoji": str(item.get("emoji") or "🎫")[:32],
                "description": str(item.get("description") or "")[:120],
                "priority": str(item.get("priority") or "normal") if str(item.get("priority") or "normal") in {"low","normal","high","urgent"} else "normal",
                "category_id": str(item.get("category_id") or ""),
                "staff_role_ids": [str(x) for x in (item.get("staff_role_ids") or [])[:20]],
                "questions": questions,
                "translations": translations,
            })
        webhook_url = str(payload.get("webhook_url") or "").strip()
        if webhook_url:
            parsed = urlsplit(webhook_url)
            host = (parsed.hostname or "").lower().rstrip(".")
            if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.port and not (1 <= parsed.port <= 65535):
                raise web.HTTPBadRequest(text="Integration webhook must be a public HTTPS endpoint.")
            try:
                addresses={ipaddress.ip_address(host)}
            except ValueError:
                try:
                    addresses={ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)}
                except (OSError, ValueError):
                    addresses=set()
            if not addresses or any(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified for ip in addresses):
                raise web.HTTPBadRequest(text="Integration webhook must resolve to a public HTTPS endpoint.")
        await self.bot.db.rsl_ticket_settings.update_one(
            {"_id": str(guild_id)},
            {"$set": {
                "enabled": bool(payload.get("enabled", True)),
                "panel_channel_id": str(payload.get("panel_channel_id") or ""),
                "transcript_channel_id": str(payload.get("transcript_channel_id") or ""),
                "closed_category_id": str(payload.get("closed_category_id") or ""),
                "default_category_id": str(payload.get("default_category_id") or ""),
                "staff_role_ids": [str(x) for x in (payload.get("staff_role_ids") or [])[:20]],
                "max_open_per_user": max(1, min(10, int(payload.get("max_open_per_user", 2) or 2))),
                "auto_close_hours": max(0, min(720, int(payload.get("auto_close_hours", 168) or 168))),
                "reminder_hours": max(0, min(168, int(payload.get("reminder_hours", 24) or 24))),
                "sla_minutes": max(0, min(10080, int(payload.get("sla_minutes", 60) or 60))),
                "auto_assign_enabled": bool(payload.get("auto_assign_enabled", False)),
                "notify_player_dm": bool(payload.get("notify_player_dm", True)),
                "support_hours_enabled": bool(payload.get("support_hours_enabled", False)),
                "support_hours_timezone": str(payload.get("support_hours_timezone") or "UTC")[:64],
                "support_hours_start": str(payload.get("support_hours_start") or "09:00")[:5],
                "support_hours_end": str(payload.get("support_hours_end") or "17:00")[:5],
                "support_hours_days": [int(x) for x in (payload.get("support_hours_days") or [0,1,2,3,4])[:7] if str(x).isdigit() and 0 <= int(x) <= 6],
                "webhook_url": webhook_url[:1000],
                "types": clean_types,
                "updated_at": time.time(),
            }},
            upsert=True,
        )
        return web.json_response({"ok": True, "settings": await settings_for(str(guild_id))})

    async def admin_tickets(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_admin(request)
        status = str(request.query.get("status") or "").strip().lower()
        query = {"guild_id": str(guild_id)}
        if status:
            query["status"] = status
        limit = max(1, min(200, int(request.query.get("limit", "100") or 100)))
        rows = await self.bot.db.rsl_tickets.find(query).sort("updated_at", -1).limit(limit).to_list(length=limit)
        for row in rows:
            row["_id"] = str(row.get("_id"))
        return web.json_response({"rows": redact_document(rows)})

    async def admin_ticket_stats(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_admin(request)
        gid = str(guild_id)
        open_statuses = ["open","assigned","investigating","awaiting_player","escalated"]
        counts = {}
        for status in open_statuses + ["closed"]:
            counts[status] = await self.bot.db.rsl_tickets.count_documents({"guild_id": gid, "status": status})
        total = sum(counts.values())
        assigned = await self.bot.db.rsl_tickets.count_documents({"guild_id": gid, "claimed_by": {"$nin": [None, ""]}, "status": {"$ne": "closed"}})
        now = time.time()
        sla = await self.bot.db.rsl_tickets.count_documents({"guild_id": gid, "status": {"$in": open_statuses}, "first_response_at": None, "created_at": {"$lt": now - 3600}})
        rows = await self.bot.db.rsl_tickets.find({"guild_id":gid}).to_list(length=5000)
        responded=[r for r in rows if r.get("first_response_at") and r.get("created_at")]
        resolved=[r for r in rows if r.get("closed_at") and r.get("created_at")]
        response_avg=round(sum(float(r["first_response_at"])-float(r["created_at"]) for r in responded)/len(responded)/60,1) if responded else None
        resolution_avg=round(sum(float(r["closed_at"])-float(r["created_at"]) for r in resolved)/len(resolved)/3600,1) if resolved else None
        ratings=[r.get("rating",{}).get("score") for r in rows if isinstance(r.get("rating"),dict) and r.get("rating",{}).get("score")]
        rating_avg=round(sum(ratings)/len(ratings),2) if ratings else None
        by_staff={}
        for r in rows:
            staff=str(r.get("claimed_by") or "")
            if staff: by_staff[staff]=by_staff.get(staff,0)+1
        return web.json_response({"counts": counts, "total": total, "assigned": assigned, "sla_at_risk": sla, "metrics":{"avg_first_response_minutes":response_avg,"avg_resolution_hours":resolution_avg,"avg_rating":rating_avg,"ratings_count":len(ratings),"staff_workload":by_staff}})

    async def admin_ticket_action(self, request: web.Request) -> web.Response:
        user, guild_id, guild = await self.require_admin(request)
        payload = await self._json_object(request)
        ticket_id = str(payload.get("ticket_id") or "")
        action = str(payload.get("action") or "").lower()
        if not ticket_id:
            raise web.HTTPBadRequest(text="ticket_id is required.")
        from bson import ObjectId
        if not ObjectId.is_valid(ticket_id):
            raise web.HTTPBadRequest(text="Invalid ticket_id.")
        row = await self.bot.db.rsl_tickets.find_one({"_id": ObjectId(ticket_id), "guild_id": str(guild_id)})
        if not row:
            raise web.HTTPNotFound(text="Ticket not found.")
        channel_id = str(row.get("channel_id") or "")
        channel = guild.get_channel(int(channel_id)) if channel_id.isdigit() else None
        if channel is not None and int(channel.guild.id) != int(guild_id):
            raise web.HTTPForbidden(text="Ticket channel is outside the selected server.")
        cog = self.bot.get_cog("TicketCog")
        if cog is None:
            raise web.HTTPServiceUnavailable(text="Ticket center is not loaded.")
        status=str(row.get("status") or "")
        if action=="reopen" and status!="closed":
            raise web.HTTPConflict(text="Only closed tickets can be reopened.")
        if action=="recover" and status not in {"orphaned","failed"}:
            raise web.HTTPConflict(text="Only orphaned or failed tickets can be recovered.")
        if action=="close" and status in {"closed","failed","provisioning"}:
            raise web.HTTPConflict(text="This ticket is not in a closable state.")
        if action in {"claim","unclaim","priority","lock","unlock"} and status in {"closed","failed","provisioning","orphaned"}:
            raise web.HTTPConflict(text="This ticket is not in an actionable state.")
        if action == "reopen":
            ok = await cog.reopen(str(guild_id), ticket_id, str(user.user_id))
        elif action == "recover":
            ok = await cog.recover(str(guild_id), ticket_id, str(user.user_id))
        elif action == "close":
            ok = await cog._close_ticket(str(guild_id), ticket_id, str(user.user_id), "admin_dashboard")
        elif action in {"claim","unclaim","priority","lock","unlock"}:
            # Ticket was already loaded with an explicit guild scope above.
            active_states={"open","assigned","investigating","awaiting_player","escalated"}
            if action == "claim":
                result = await self.bot.db.rsl_tickets.update_one({"_id": row["_id"], "guild_id": str(guild_id), "status": {"$in":list(active_states)}, "claimed_by": None}, {"$set":{"claimed_by":str(user.user_id),"status":"assigned","updated_at":time.time(),"last_activity_at":time.time()}})
                ok = bool(result.modified_count)
            elif action == "unclaim":
                result = await self.bot.db.rsl_tickets.update_one({"_id": row["_id"], "guild_id": str(guild_id), "status": {"$in":list(active_states)}, "claimed_by": str(user.user_id)}, {"$set":{"claimed_by":None,"status":"open","updated_at":time.time(),"last_activity_at":time.time()}})
                ok = bool(result.modified_count)
            elif action == "priority":
                order=["low","normal","high","urgent"]; current=str(row.get("priority") or "normal"); nxt=order[(order.index(current)+1)%4] if current in order else "normal"
                result=await self.bot.db.rsl_tickets.update_one({"_id":row["_id"],"guild_id":str(guild_id),"status":{"$in":list(active_states)}},{"$set":{"priority":nxt,"updated_at":time.time(),"last_activity_at":time.time()}})
                ok=bool(result.modified_count)
            else:
                locked = action == "lock"
                result=await self.bot.db.rsl_tickets.update_one({"_id":row["_id"],"guild_id":str(guild_id),"status":{"$in":list(active_states)},"locked":not locked},{"$set":{"locked":locked,"updated_at":time.time(),"last_activity_at":time.time()}})
                ok=bool(result.modified_count)
                if ok:
                    updated=await self.bot.db.rsl_tickets.find_one({"_id":row["_id"],"guild_id":str(guild_id)})
                    if updated:
                        try:
                            await cog.reconcile_ticket_permissions(guild, updated, closed=False, locked=locked)
                        except Exception:
                            logging.getLogger(__name__).exception(
                                "Unable to reconcile ticket permissions after admin ticket action: ticket=%s",
                                ticket_id,
                            )
            if ok:
                from ..cogs.tickets import log_event
                await log_event(str(guild_id), ticket_id, action, str(user.user_id))
        else:
            raise web.HTTPBadRequest(text="Unsupported ticket action.")
        return web.json_response({"ok": ok, "ticket_id": ticket_id, "action": action})

    async def admin_ticket_panel(self, request: web.Request) -> web.Response:
        _, guild_id, guild = await self.require_admin(request)
        payload = await self._json_object(request)
        channel_id = str(payload.get("channel_id") or "")
        if not channel_id.isdigit():
            raise web.HTTPBadRequest(text="A Discord channel ID is required.")
        cog = self.bot.get_cog("TicketCog")
        channel = self.bot.get_channel(int(channel_id))
        if cog is None or not isinstance(channel, discord.TextChannel):
            raise web.HTTPBadRequest(text="Ticket center or target text channel is unavailable.")
        if int(channel.guild.id) != int(guild_id):
            raise web.HTTPForbidden(text="Target channel must belong to the selected server.")
        settings = await cog.settings_for(str(guild_id)) if hasattr(cog, "settings_for") else await __import__("ALU_Gauntlet.cogs.tickets", fromlist=["settings_for"]).settings_for(str(guild_id))
        embed = discord.Embed(title="🎫 RACING SYNDICATE LEAGUE • SUPPORT CENTER", description="Choose the type of help you need below. Your ticket will be private to you and routed to the appropriate RSL support team.", color=discord.Color.blurple())
        panel_view=__import__("ALU_Gauntlet.cogs.tickets", fromlist=["TicketPanelView"]).TicketPanelView(cog, settings["types"])
        existing_id=str(settings.get("panel_message_id") or "")
        message=None
        if existing_id.isdigit() and str(settings.get("panel_channel_id") or "")==channel_id:
            try:
                message=await channel.fetch_message(int(existing_id))
                await message.edit(embed=embed, view=panel_view)
            except (discord.NotFound, discord.HTTPException):
                message=None
        if message is None:
            message=await channel.send(embed=embed, view=panel_view)
        await self.bot.db.rsl_ticket_settings.update_one(
            {"_id":str(guild_id)},
            {"$set":{"panel_channel_id":channel_id,"panel_message_id":str(message.id)}}
        )
        return web.json_response({"ok": True, "message_id": str(message.id), "channel_id": channel_id, "refreshed": existing_id==str(message.id)})

    async def admin_ticket_transcript(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        payload = await self._json_object(request)
        ticket_id = str(payload.get("ticket_id") or "")
        from bson import ObjectId
        if not ObjectId.is_valid(ticket_id):
            raise web.HTTPBadRequest(text="Invalid ticket_id.")
        row = await self.bot.db.rsl_tickets.find_one({"_id": ObjectId(ticket_id), "guild_id": str(guild_id)})
        if not row:
            raise web.HTTPNotFound(text="Ticket not found.")
        rate_key=f"{guild_id}:{user.user_id}:{ticket_id}"
        now=time.time()
        last=self._ticket_transcript_rate.get(rate_key,0.0)
        if now-last < 15:
            raise web.HTTPTooManyRequests(text="Please wait a few seconds before generating this transcript again.")
        self._ticket_transcript_rate[rate_key]=now
        channel = self.bot.get_channel(int(row.get("channel_id", 0)))
        if not channel:
            raise web.HTTPNotFound(text="Ticket channel is unavailable.")
        if int(channel.guild.id) != int(guild_id):
            raise web.HTTPForbidden(text="Ticket channel is outside the selected server.")
        lines = [f"RSL Ticket #{ticket_id}", f"Type: {row.get('type')}", f"Opened by: {row.get('user_id')}", f"Status: {row.get('status')}", ""]
        max_transcript_bytes=2_000_000
        transcript_bytes=len(lines[0].encode("utf-8"))+sum(len(line.encode("utf-8")) for line in lines[1:])
        truncated=False
        async for msg in channel.history(limit=500, oldest_first=True):
            stamp = msg.created_at.astimezone(timezone.utc).isoformat()
            text_body = msg.content or ""
            if msg.attachments:
                attachment_meta = " ".join(
                    f"[attachment:{str(a.filename).replace(chr(10),' ').replace(chr(13),' ')[:200]}|{max(0,min(int(a.size or 0),2147483647))} bytes|{str(a.content_type or 'unknown')[:128]}]"
                    for a in msg.attachments[:10]
                )
                text_body += " " + attachment_meta
            line=f"[{stamp}] {msg.author} ({msg.author.id}): {text_body}"
            candidate_bytes=len((line+"\\n").encode("utf-8"))
            if transcript_bytes+candidate_bytes>max_transcript_bytes:
                truncated=True
                break
            lines.append(line)
            transcript_bytes+=candidate_bytes
        if truncated:
            lines.append("[Transcript truncated at 2 MB; older messages are complete up to this point.]")
        data = "\n".join(lines).encode("utf-8")
        settings = await __import__("ALU_Gauntlet.cogs.tickets", fromlist=["settings_for"]).settings_for(str(guild_id))
        target = self.bot.get_channel(int(settings.get("transcript_channel_id") or 0)) if settings.get("transcript_channel_id") else None
        if isinstance(target, discord.TextChannel) and int(target.guild.id) == int(guild_id):
            everyone_can_view=target.permissions_for(target.guild.default_role).view_channel
            if not everyone_can_view:
                await target.send(content=f"📄 Transcript generated by <@{user.user_id}> for ticket #{ticket_id}.", file=discord.File(BytesIO(data), filename=f"rsl-ticket-{ticket_id}.txt"))
        return web.Response(body=data, content_type="text/plain", headers={"Content-Disposition": f'attachment; filename="rsl-ticket-{ticket_id}.txt"'})

    async def admin_revert_gauntlet_match(self, request: web.Request) -> web.Response:
        """Staff-only safe Gauntlet match rollback using the shared settlement service."""
        user, guild_id, _ = await self.require_admin(request)
        payload = await self._json_object(request)
        match_id = str(payload.get("match_id") or "").strip()
        if not match_id:
            raise web.HTTPBadRequest(text="match_id is required.")
        from ...core.core import revert_match_settlement
        try:
            match = await revert_match_settlement(str(guild_id), match_id, str(user.user_id))
        except RuntimeError as exc:
            messages = {
                "MATCH_ALREADY_REVERTED_OR_MISSING": "This match was already reverted or is no longer available.",
                "LATER_MATCH_EXISTS": "This match cannot be automatically reverted because a later match exists for one of these players.",
                "LEGACY_MATCH_NO_SNAPSHOT": "This legacy match lacks safe rollback snapshots.",
                "PLAYER_PROFILE_MISSING": "Player profiles required for rollback were not found.",
                "PLAYER_STATE_CHANGED": "Player state changed after this match; rollback was cancelled for safety.",
                "TRANSACTIONS_REQUIRED": "Automatic rollback requires the connected MongoDB transaction mode.",
            }
            reason = str(exc)
            if reason in {"MATCH_ALREADY_REVERTED_OR_MISSING", "LATER_MATCH_EXISTS", "LEGACY_MATCH_NO_SNAPSHOT", "PLAYER_PROFILE_MISSING", "PLAYER_STATE_CHANGED"}:
                raise web.HTTPConflict(text=messages[reason])
            raise web.HTTPServiceUnavailable(text=messages.get(reason, "The match could not be reverted safely.")) from exc
        await self._audit(str(guild_id), str(user.user_id), f"Web Gauntlet match reverted: {match_id}")
        return web.json_response({
            "ok": True,
            "status": "reverted",
            "match_id": str(match.get("_id", match_id)),
            "challenger_id": str(match.get("challenger_id", "")),
            "opponent_id": str(match.get("opponent_id", "")),
        })

    async def _is_live_guild_staff(self, user: Any, guild_id: str, guild: Any) -> bool:
        """Check staff/admin access against the live Discord member for one guild."""
        if user.user_id in self.auth.allowed_staff_ids:
            return True
        try:
            member = guild.get_member(int(user.user_id))
        except Exception:
            member = None
        if member is None:
            try:
                member = await guild.fetch_member(int(user.user_id))
            except Exception:
                member = None
        if member is None:
            return False
        if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
            return True
        settings = await self.bot.db.settings.find_one({"_id": guild_id}) or {}
        admin_role_id = str(settings.get("admin_role_id", "")).strip()
        return bool(
            admin_role_id
            and any(str(role.id) == admin_role_id for role in getattr(member, "roles", []))
        )

    async def require_admin(self, request: web.Request) -> tuple[Any, str, Any]:
        # The standalone /setup page may be opened without ?guild_id. In that
        # case choose the first connected guild where the signed-in user is
        # actually staff/admin. Explicit guild_id still has priority.
        user = await self.require_user(request)
        explicit = request.query.get("guild_id", "").strip()
        if not explicit:
            connected = await self._connected_guilds_for_user(user)
            preferred = [
                request.cookies.get("rsl_guild_id", "").strip(),
                *[str(x) for x in getattr(user, "admin_guild_ids", [])],
                *connected.keys(),
            ]
            for guild_id in preferred:
                guild = connected.get(guild_id)
                if guild is not None and await self._is_live_guild_staff(user, guild_id, guild):
                    return user, guild_id, guild
            raise web.HTTPForbidden(text="Administrator access is required for a connected server.")
        user, guild_id, guild = await self.require_guild_member(request)

        # Always re-check the live Discord member for the selected guild.
        if not await self._is_live_guild_staff(user, guild_id, guild):
            raise web.HTTPForbidden(text="Administrator access is required for this server.")
        return user, guild_id, guild

    async def require_staff(self, request: web.Request) -> Any:
        """Require live staff access on at least one connected Discord guild.

        The persisted OAuth session's `staff` flag is only a convenience snapshot;
        authorization must be re-checked against current Discord membership/permissions.
        """
        user = await self.require_user(request)
        connected = await self._connected_guilds_for_user(user)
        for guild_id, guild in connected.items():
            if await self._is_live_guild_staff(user, guild_id, guild):
                return user
        raise web.HTTPForbidden(text="Staff access is required.")

    async def admin_club_leadership(self, request: web.Request) -> web.Response:
        user, guild_id, _guild = await self.require_admin(request)
        clubs = await self.bot.db.clubs.find({"guild_id": str(guild_id)}).sort("name_ci", 1).to_list(length=500)
        rows = []
        for club in clubs:
            members = await self.bot.db.club_members.find(
                {"club_id": str(club["_id"]), "guild_id": str(guild_id)}
            ).sort("joined_at", 1).to_list(length=20)
            rows.append({
                "id": str(club["_id"]),
                "name": str(club.get("name") or "Club"),
                "leader_id": str(club.get("leader_id") or ""),
                "members": [
                    {
                        "user_id": str(m.get("user_id") or ""),
                        "username": str(m.get("username") or m.get("user_id") or ""),
                        "role": str(m.get("role") or "member").casefold(),
                    }
                    for m in members
                ],
            })
        return web.json_response({"guild_id": str(guild_id), "clubs": rows})

    async def admin_club_leadership_action(self, request: web.Request) -> web.Response:
        user, guild_id, _guild = await self.require_admin(request)
        try:
            payload = await self._json_object(request)
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        club_id = str(payload.get("club_id") or "").strip()
        target_id = str(payload.get("target_user_id") or "").strip()
        if not club_id or not target_id:
            raise web.HTTPBadRequest(text="Club and replacement leader are required.")
        try:
            oid = ObjectId(club_id)
        except Exception as exc:
            raise web.HTTPBadRequest(text="Invalid club ID.") from exc
        club = await self.bot.db.clubs.find_one({"_id": oid, "guild_id": str(guild_id)})
        if not club:
            raise web.HTTPNotFound(text="Club not found.")
        target = await self.bot.db.club_members.find_one({
            "club_id": club_id,
            "guild_id": str(guild_id),
            "user_id": target_id,
        })
        if not target:
            raise web.HTTPNotFound(text="The replacement leader must already be a club member.")
        old_leader_id = str(club.get("leader_id") or "")
        if target_id == old_leader_id:
            raise web.HTTPConflict(text="That driver is already the club leader.")
        now = datetime.now(timezone.utc).isoformat()
        client = getattr(self.bot.db, "client", None)
        if client is not None:
            async with await client.start_session() as session:
                async with session.start_transaction():
                    result = await self.bot.db.clubs.update_one(
                        {"_id": oid, "guild_id": str(guild_id), "leader_id": old_leader_id},
                        {"$set": {"leader_id": target_id, "updated_at": now}},
                        session=session,
                    )
                    if not result.modified_count:
                        raise web.HTTPConflict(text="The club leadership changed before this action completed.")
                    old_role = await self.bot.db.club_members.update_one(
                        {"club_id": club_id, "user_id": old_leader_id},
                        {"$set": {"role": "officer", "updated_at": now}},
                        session=session,
                    )
                    new_role = await self.bot.db.club_members.update_one(
                        {"club_id": club_id, "user_id": target_id},
                        {"$set": {"role": "leader", "updated_at": now}},
                        session=session,
                    )
                    if not old_role.modified_count or not new_role.modified_count:
                        raise web.HTTPConflict(text="Club membership changed before this action completed.")
        else:
            result = await self.bot.db.clubs.update_one(
                {"_id": oid, "guild_id": str(guild_id), "leader_id": old_leader_id},
                {"$set": {"leader_id": target_id, "updated_at": now}},
            )
            if not result.modified_count:
                raise web.HTTPConflict(text="The club leadership changed before this action completed.")
            old_role = await self.bot.db.club_members.update_one(
                {"club_id": club_id, "user_id": old_leader_id},
                {"$set": {"role": "officer", "updated_at": now}},
            )
            new_role = await self.bot.db.club_members.update_one(
                {"club_id": club_id, "user_id": target_id},
                {"$set": {"role": "leader", "updated_at": now}},
            )
            if not old_role.modified_count or not new_role.modified_count:
                await self.bot.db.clubs.update_one(
                    {"_id": oid, "guild_id": str(guild_id), "leader_id": target_id},
                    {"$set": {"leader_id": old_leader_id, "updated_at": now}},
                )
                await self.bot.db.club_members.update_one(
                    {"club_id": club_id, "user_id": old_leader_id},
                    {"$set": {"role": "leader", "updated_at": now}},
                )
                await self.bot.db.club_members.update_one(
                    {"club_id": club_id, "user_id": target_id},
                    {"$set": {"role": "member", "updated_at": now}},
                )
                raise web.HTTPConflict(text="Club leadership transfer could not be completed safely.")
        await self._audit(
            str(guild_id),
            str(user.user_id),
            f"Staff transferred club leadership: {club.get('name', 'Club')} {old_leader_id} -> {target_id}",
        )
        return web.json_response({
            "ok": True,
            "club_id": club_id,
            "old_leader_id": old_leader_id,
            "new_leader_id": target_id,
            "message": "Club leadership transferred. The previous leader is now an Officer.",
        })

    async def admin_server_control(self, request: web.Request) -> web.Response:
        _, guild_id, guild = await self.require_admin(request)
        me = guild.me
        permissions = getattr(me, "guild_permissions", None)
        return web.json_response({
            "guild": {"id": guild_id, "name": str(getattr(guild, "name", guild_id))},
            "bot": {
                "id": str(self.bot.user.id) if self.bot.user else "",
                "name": str(self.bot.user.name) if self.bot.user else "RSL Bot",
                "avatar_url": str(self.bot.user.display_avatar.url) if self.bot.user else "",
            },
            "permissions": {
                "manage_roles": bool(permissions and (permissions.manage_roles or permissions.administrator)),
                "manage_channels": bool(permissions and (permissions.manage_channels or permissions.administrator)),
            },
            "roles": [
                {"id": str(role.id), "name": role.name, "managed": bool(role.managed), "position": int(role.position)}
                for role in guild.roles if not role.is_default()
            ],
            "channels": [
                {"id": str(channel.id), "name": channel.name, "type": str(getattr(channel, "type", "")), "category_id": str(channel.category_id) if channel.category_id else ""}
                for channel in guild.channels
            ],
        })

    async def admin_create_role(self, request: web.Request) -> web.Response:
        user, guild_id, guild = await self.require_admin(request)
        try:
            payload = await self._json_object(request)
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        name = str(payload.get("name", "")).strip()[:100]
        if not name:
            raise web.HTTPBadRequest(text="Role name is required.")
        me = guild.me
        permissions = getattr(me, "guild_permissions", None)
        if not permissions or not (permissions.manage_roles or permissions.administrator):
            raise web.HTTPForbidden(text="The bot needs Manage Roles permission.")
        colour_value = str(payload.get("colour", "")).strip().lstrip("#")
        colour = discord.Colour.default()
        if colour_value:
            if not re.fullmatch(r"[0-9a-fA-F]{6}", colour_value):
                raise web.HTTPBadRequest(text="Role colour must be a six-digit hex value.")
            colour = discord.Colour(int(colour_value, 16))
        try:
            role = await guild.create_role(name=name, colour=colour, reason="RSL web server control")
        except discord.Forbidden as exc:
            raise web.HTTPForbidden(text="Discord denied role creation. Check bot role hierarchy and permissions.") from exc
        await self._audit(guild_id, user.user_id, f"Created Discord role: {name}")
        return web.json_response({"ok": True, "role": {"id": str(role.id), "name": role.name}})

    async def admin_create_channel(self, request: web.Request) -> web.Response:
        user, guild_id, guild = await self.require_admin(request)
        try:
            payload = await self._json_object(request)
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        name = str(payload.get("name", "")).strip()[:100]
        channel_type = str(payload.get("type", "text")).strip().lower()
        category_id = str(payload.get("category_id", "")).strip()
        if not name:
            raise web.HTTPBadRequest(text="Channel name is required.")
        me = guild.me
        permissions = getattr(me, "guild_permissions", None)
        if not permissions or not (permissions.manage_channels or permissions.administrator):
            raise web.HTTPForbidden(text="The bot needs Manage Channels permission.")
        category = None
        if category_id:
            try:
                category = guild.get_channel(int(category_id))
            except (TypeError, ValueError):
                category = None
            if category is None or not isinstance(category, discord.CategoryChannel):
                raise web.HTTPBadRequest(text="Invalid category.")
        try:
            if channel_type == "voice":
                channel = await guild.create_voice_channel(name=name, category=category, reason="RSL web server control")
            else:
                channel = await guild.create_text_channel(name=name, category=category, reason="RSL web server control")
        except discord.Forbidden as exc:
            raise web.HTTPForbidden(text="Discord denied channel creation. Check bot permissions.") from exc
        await self._audit(guild_id, user.user_id, f"Created Discord channel: {name}")
        return web.json_response({"ok": True, "channel": {"id": str(channel.id), "name": channel.name, "type": str(getattr(channel, "type", ""))}})

    async def admin_bot_identity(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_admin(request)
        if not self.bot.user:
            raise web.HTTPServiceUnavailable(text="Discord bot identity is not ready.")
        username = ""
        avatar_bytes = None
        if request.content_type.startswith("multipart/"):
            try:
                reader = await request.multipart()
                while True:
                    field = await reader.next()
                    if field is None:
                        break
                    if field.name == "username":
                        username = (await field.text()).strip()[:80]
                    elif field.name == "avatar":
                        data = await field.read(decode=False)
                        if len(data) > 8 * 1024 * 1024:
                            raise web.HTTPRequestEntityTooLarge(max_size=8 * 1024 * 1024, actual_size=len(data))
                        if data:
                            try:
                                with Image.open(BytesIO(data)) as source:
                                    source.load()
                                    if source.width > 2048 or source.height > 2048:
                                        source.thumbnail((2048, 2048))
                                    output = BytesIO()
                                    source.convert("RGBA").save(output, format="PNG")
                                    avatar_bytes = output.getvalue()
                            except (UnidentifiedImageError, OSError) as exc:
                                raise web.HTTPBadRequest(text="Avatar must be a valid image.") from exc
            except web.HTTPException:
                raise
            except Exception as exc:
                raise web.HTTPBadRequest(text=f"Invalid identity upload: {str(exc)[:180]}") from exc
        else:
            try:
                payload = await self._json_object(request)
            except Exception:
                raise web.HTTPBadRequest(text="Invalid JSON body.")
            username = str(payload.get("username", "")).strip()[:80]
        if not username and avatar_bytes is None:
            raise web.HTTPBadRequest(text="Provide a new username and/or avatar.")
        changed = []
        try:
            if username:
                await self.bot.user.edit(username=username)
                changed.append("username")
            if avatar_bytes is not None:
                await self.bot.user.edit(avatar=avatar_bytes)
                changed.append("avatar")
        except discord.HTTPException as exc:
            raise web.HTTPBadRequest(text=f"Discord rejected the identity update: {exc}") from exc
        await self._audit(guild_id, user.user_id, "Updated Discord bot identity: " + ", ".join(changed))
        return web.json_response({"ok": True, "changed": changed, "bot": {"name": self.bot.user.name, "avatar_url": str(self.bot.user.display_avatar.url)}})

    async def setup_options(self, request: web.Request) -> web.Response:
        _, _, guild = await self.require_admin(request)
        channels = [{"id": str(c.id), "name": c.name, "type": str(getattr(c, "type", "text"))} for c in guild.text_channels]
        roles = [{"id": str(role.id), "name": role.name} for role in guild.roles if not role.is_default() and not role.managed]
        return web.json_response({"channels": channels, "roles": roles, "timezones": [{"label": label, "value": value} for label, value in TIMEZONE_LABELS]})

    async def setup_settings(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_admin(request)
        settings = await self.bot.db.settings.find_one({"_id": guild_id}) or {}
        fields = tuple(key for key, _ in SETUP_CHANNELS + SETUP_ROLES) + (
            "tournament_main_channel_id", "tournament_log_channel_id", "tournament_bracket_channel_id",
            "tournament_admin_channel_id", "tournament_announcement_channel_id",
            "tournament_admin_role_id", "tournament_player_announcement_role_id",
        )
        return web.json_response({"settings": {key: settings.get(key) for key in fields} | {"timezone": settings.get("timezone", "UTC"), "achievement_role_names": settings.get("achievement_role_names", {}), "achievement_role_ids": settings.get("achievement_role_ids", {})}})

    async def season(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_guild_member(request)
        state = await self.bot.db.season_state.find_one({"_id": f"guild_{guild_id}"}) or {}
        return web.json_response({"season": state})

    async def admin_security_events(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_admin(request)
        limit = max(1, min(100, int(request.query.get("limit", "50") or 50)))
        rows = await self.bot.db.system_events.find(
            {"guild_id": str(guild_id), "event_type": {"$in": sorted(SUSPICIOUS_EVENT_TYPES)}},
            {"_id": 1, "timestamp": 1, "event_type": 1, "actor_id": 1, "target_type": 1, "target_id": 1, "details": 1},
        ).sort("timestamp", -1).limit(limit).to_list(length=limit)
        return web.json_response({"rows": [redact_document(x) for x in rows]})

    async def admin_readiness(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_admin(request)
        settings = await self.bot.db.settings.find_one({"_id": str(guild_id)}) or {}
        heartbeat = await self.bot.db.system_events.find_one({"_id": "production_heartbeat"}) or {}
        checks = {
            "guild_settings": bool(settings),
            "discord_ready": bool(getattr(self.bot, "is_ready", lambda: False)()),
            "database_reachable": True,
            "production_heartbeat": bool(heartbeat),
            "maintenance_not_blocking": not bool((settings.get("maintenance_mode") or {}).get("enabled")),
        }
        try:
            await self.bot.db.command("ping")
        except Exception:
            checks["database_reachable"] = False
        return web.json_response(readiness_check(checks))

    async def admin_performance(self, request: web.Request) -> web.Response:
        _, guild_id, _ = await self.require_admin(request)
        rows = await self.bot.db.system_events.find(
            {"guild_id": str(guild_id), "event_type": "REQUEST_SLOW"},
            {"_id": 0, "timestamp": 1, "path": 1, "method": 1, "milliseconds": 1, "bucket": 1},
        ).sort("timestamp", -1).limit(100).to_list(length=100)
        return web.json_response({"rows": rows})
