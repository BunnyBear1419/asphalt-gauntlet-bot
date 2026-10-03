"""RSL web player route family."""
from .._web_context import *

class PlayerRoutesMixin:
    async def profile_tournaments(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        uid = str(user.user_id)
        guild_ids = set(str(x) for x in user.guild_ids)
        rows = []
        total_matches = total_wins = total_losses = 0
        async for t in self.bot.db.tournaments.find({"guild_id": {"$in": list(guild_ids)}}).sort("start_time", -1):
            tid = str(t.get("_id"))
            team_size = int(t.get("team_size", 1))
            entrant_ids = {uid}
            registration = await self.bot.db.tournament_registrations.find_one({"tournament_id": tid, "user_id": uid}) if team_size == 1 else None
            participant = bool(registration and registration.get("status") not in {"withdrawn", "cancelled", "rejected"})
            club_regs = []
            if team_size > 1:
                async for reg in self.bot.db.tournament_club_registrations.find({"tournament_id": tid, "status": {"$nin": ["withdrawn", "cancelled", "rejected"]}}):
                    if uid in {str(x) for x in (reg.get("lineup") or [])}:
                        participant = True
                        club_regs.append(reg)
                        entrant_ids.add(str(reg.get("club_id", "")))
            if not participant:
                continue
            bracket = t.get("bracket") or {}
            groups = []
            for key in ("rounds", "winners", "losers"):
                groups.extend(bracket.get(key) or [])
            for key in ("grand_final", "grand_final_reset"):
                if isinstance(bracket.get(key), dict):
                    groups.append({"matches": [bracket[key]]})
            matches = [m for group in groups for m in group.get("matches", [])]
            wins = losses = played = highest_round = 0
            for m in matches:
                slots = {str(x) for x in (m.get("player_slots") or []) if x}
                if not slots.intersection(entrant_ids):
                    continue
                highest_round = max(highest_round, int(m.get("round") or 0))
                if m.get("status") == "completed" or m.get("result_status") == "verified":
                    played += 1
                    if str(m.get("winner_id", "")) in entrant_ids: wins += 1
                    elif m.get("winner_id"): losses += 1
            total_matches += played; total_wins += wins; total_losses += losses
            status = str(t.get("status", "draft"))
            finish = "Champion" if str(t.get("champion_id", "")) in entrant_ids else ("Eliminated" if status == "completed" else "In progress")
            placement = None
            if status == "completed":
                result_payload = await self._tournament_result_payload({**t, "_id": t.get("_id")})
                placement = next((int(x.get("placement")) for x in result_payload.get("standings", []) if str(x.get("entrant_id")) in entrant_ids and x.get("placement") is not None), None)
            rows.append({"id":tid,"name":t.get("name","Tournament"),"status":status,"format_label":{"single_elimination":"Single Elimination","double_elimination":"Double Elimination","round_robin":"Round Robin"}.get(t.get("format"),str(t.get("format","Tournament")).replace("_"," ").title()),"team_size":team_size,"start_time":t.get("start_time"),"wins":wins,"losses":losses,"matches_played":played,"current_round":highest_round,"finish":finish,"placement":placement,"champion":bool(str(t.get("champion_id","")) in entrant_ids),"registration_status":(registration or {}).get("status") if registration else (club_regs[0].get("status") if club_regs else None)})
        rows.sort(key=lambda x: str(x.get("start_time") or ""), reverse=True)
        history = [r for r in rows if r["status"] == "completed"][:12]
        return web.json_response({"tournaments":rows[:20],"upcoming":[r for r in rows if r["status"] in {"registration_open","open","live"}][:5],"history":history,"stats":{"entered":len(rows),"completed":len(history),"championships":sum(1 for r in rows if r.get("champion")),"matches_played":total_matches,"wins":total_wins,"losses":total_losses,"win_rate":round((total_wins/total_matches)*100,1) if total_matches else 0}})

    async def my_tournaments_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("my-tournaments.html", request)

    async def players_page(self, request: web.Request) -> web.StreamResponse:
        # The Players page is staff-only, but the page URL itself does not need
        # to force users to manually append ?guild_id=. Resolve the selected
        # admin server from the existing guild cookie, or fall back to the
        # first server where the signed-in user has admin access.
        if not request.query.get("guild_id", "").strip():
            cookie_guild_id = request.cookies.get("rsl_guild_id", "").strip()
            if cookie_guild_id:
                request = request.clone(rel_url=request.rel_url.with_query({**request.query, "guild_id": cookie_guild_id}))
            else:
                user = await self.require_user(request)
                rows = await self._admin_guilds_data(user)
                if not rows:
                    raise web.HTTPForbidden(text="Administrator access is required for this server.")
                request = request.clone(rel_url=request.rel_url.with_query({**request.query, "guild_id": rows[0]["id"]}))
        await self.require_admin(request)
        return await self._page_response("players.html", request)

    async def player_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("player.html", request)

    async def player_profile_page(self, request: web.Request) -> web.StreamResponse:
        user = await self.require_user(request)
        return web.Response(status=302, headers={"Location": f"/profile?user_id={user.user_id}"})

    async def player_settings_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("player.html", request)

    async def profile_page(self, request: web.Request) -> web.StreamResponse:
        user = await self.require_user(request)
        user_id = str(request.query.get("user_id") or "").strip()
        if user_id == "me" or not user_id:
            return web.Response(status=302, headers={"Location": f"/profile?user_id={user.user_id}"})
        return await self._page_response("public-profile.html", request)

    async def player_me(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        player = await self.players.get_player(guild_id, user.user_id)
        preferences = await self.bot.db.web_preferences.find_one({"_id": f"{guild_id}_{user.user_id}"}) or {}
        today = datetime.now(timezone.utc).date().isoformat()
        raw = player or {}
        if raw.get("gauntlet_ticket_date") == today:
            remaining = min(MAX_DAILY_TICKETS, max(0, int(raw.get("gauntlet_tickets", FREE_DAILY_TICKETS) or 0)))
            purchased = min(5, max(0, int(raw.get("gauntlet_purchased_tickets", 0) or 0)))
        else:
            remaining, purchased = FREE_DAILY_TICKETS, 0
        ticket_state = next_ticket_purchase(purchased, int(raw.get("rsl_coins", 0) or 0))
        ticket_state.update({
            "date": today,
            "tickets_remaining": remaining,
            "free_remaining": min(FREE_DAILY_TICKETS, remaining),
            "purchased_remaining": max(0, remaining - min(FREE_DAILY_TICKETS, remaining)),
        })
        return web.json_response({
            "player": player,
            "user": {"id": user.user_id, "username": user.username, "global_name": user.global_name},
            "preferences": {key: preferences.get(key) for key in ("timezone", "web_notifications", "dm_notifications", "game_name", "about", "location", "platform", "driver_type", "links", "rsl_display_name", "rsl_avatar_url", "asphalt_connection")},
            "tickets": ticket_state,
        })

    async def player_ticket_purchase(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        today = datetime.now(timezone.utc).date().isoformat()
        result = await purchase_daily_ticket(
            self.bot.db,
            guild_id=str(guild_id),
            user_id=str(user.user_id),
            today=today,
        )
        if not result.get("ok"):
            messages = {
                "profile_not_found": "Register your RSL driver profile before buying an extra ticket.",
                "purchase_limit": "You have reached the 5 purchased-ticket limit for today.",
                "insufficient_coins": f"You need {int(result.get('cost', 0)):,} RSL Coins for your next ticket.",
                "purchase_race_or_state_changed": "Your ticket state changed before the purchase completed. Refresh and try again.",
            }
            return web.json_response(
                {"ok": False, "error": messages.get(result.get("reason"), "Ticket purchase could not be completed."), "reason": result.get("reason"), "cost": result.get("cost", 0)},
                status=409,
            )
        player = await self.players.get_player(str(guild_id), str(user.user_id)) or {}
        purchased = min(5, max(0, int(player.get("gauntlet_purchased_tickets", 0) or 0)))
        remaining = min(MAX_DAILY_TICKETS, max(0, int(player.get("gauntlet_tickets", 0) or 0)))
        ticket_state = next_ticket_purchase(purchased, int(player.get("rsl_coins", 0) or 0))
        ticket_state.update({
            "date": today,
            "tickets_remaining": remaining,
            "free_remaining": min(FREE_DAILY_TICKETS, remaining),
            "purchased_remaining": max(0, remaining - min(FREE_DAILY_TICKETS, remaining)),
        })
        return web.json_response({"ok": True, "cost": int(result.get("cost", 0)), "tickets": ticket_state})

    async def player_economy_history(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_guild_member(request)
        rows = await recent_coin_transactions(
            self.bot.db, guild_id=str(guild_id), user_id=str(user.user_id), limit=20
        )
        return web.json_response({"transactions": rows})

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
            payload = await self._json_object(request)
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        action = str(payload.get("action", "generate")).strip().casefold()
        driver_id = f"{guild_id}_{user.user_id}"
        profile = await self.bot.db.drivers.find_one({"_id": driver_id})
        if not profile:
            raise web.HTTPConflict(text="Register your driver for the current season before setting a defense.")
        current_season = await get_current_season_number(str(guild_id))
        if not profile.get("season_registered") or int(profile.get("season_number", 0) or 0) != int(current_season):
            raise web.HTTPConflict(text=f"Register your driver for Season {current_season} before setting a defense.")
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
            payload = await self._json_object(request)
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        game_id = str(payload.get("game_id", "")).strip()
        proof_url = str(payload.get("proof_url", "")).strip()
        control_raw = str(payload.get("control", "")).strip().casefold()
        if not game_id or len(game_id) > 100:
            raise web.HTTPBadRequest(text="Game ID is required and must be 100 characters or fewer.")
        raw_ranks = payload.get("top_five_car_ranks")
        if not isinstance(raw_ranks, list) or len(raw_ranks) != 5:
            raise web.HTTPBadRequest(text="Exactly five top-car performance ratings are required.")
        try:
            top_five_car_ranks = [int(x) for x in raw_ranks]
        except (TypeError, ValueError):
            raise web.HTTPBadRequest(text="Top-car performance ratings must be whole numbers.")
        if any(x <= 0 for x in top_five_car_ranks):
            raise web.HTTPBadRequest(text="Top-car performance ratings must all be positive.")
        garage_pi = sum(top_five_car_ranks)
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
        await submit_registration_application(interaction, game_id, garage_pi, _Proof(), _ControlType(), top_five_car_ranks=top_five_car_ranks)
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
            payload = await self._json_object(request)
        except Exception:
            raise web.HTTPBadRequest(text="Invalid JSON body.")
        game_name = str(payload.get("game_name", "")).strip()[:100]
        rsl_display_name = str(payload.get("rsl_display_name", "")).strip()[:32]
        rsl_avatar_url = str(payload.get("rsl_avatar_url", "")).strip()[:500]
        if rsl_avatar_url and not rsl_avatar_url.lower().startswith(("http://", "https://")):
            raise web.HTTPBadRequest(text="RSL avatar must be an http:// or https:// image URL.")
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
            {"$set": {"guild_id": guild_id, "user_id": user.user_id, "game_name": game_name, "about": about, "location": location, "platform": platform, "driver_type": driver_type, "timezone": timezone, "links": clean_links, "rsl_display_name": rsl_display_name, "rsl_avatar_url": rsl_avatar_url}},
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
            payload = await self._json_object(request)
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
            payload = await self._json_object(request)
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
        """Return only safe public-facing fields for a guild driver's profile."""
        _, guild_id, _ = await self.require_guild_member(request)
        user_id = str(request.match_info["user_id"]).strip()
        if not user_id.isdigit():
            raise web.HTTPNotFound(text="Driver not found.")
        player = await self.players.get_player(guild_id, user_id)
        prefs = await self.bot.db.web_preferences.find_one({"_id": f"{guild_id}_{user_id}"}) or {}
        connection = prefs.get("asphalt_connection") or {}
        guild = next((g for g in self.bot.guilds if str(g.id) == str(guild_id)), None)
        member = guild.get_member(int(user_id)) if guild else None
        if member is None and guild:
            try:
                member = await guild.fetch_member(int(user_id))
            except Exception:
                log.exception(
                    "Unable to resolve public profile member %s in guild %s",
                    user_id,
                    guild_id,
                )
                member = None
        if player is None and member is None:
            raise web.HTTPNotFound(text="Driver not found.")
        player = player or {}
        discord_name = str(getattr(member, "global_name", None) or getattr(member, "display_name", None) or player.get("username") or player.get("game_id") or "Driver")
        profile_name = str(prefs.get("rsl_display_name") or discord_name)
        discord_username = str(getattr(member, "name", None) or player.get("username") or "")
        avatar_url = str(prefs.get("rsl_avatar_url") or getattr(getattr(member, "display_avatar", None), "url", "") or "")
        elo = int(player.get("elo", 1000) or 1000)
        season = await get_current_season_number(str(guild_id))
        season_number = int(player.get("season_number", 0) or 0)
        season_registered = bool(player.get("season_registered")) and season_number == season
        rank = None
        if season_registered:
            higher = await self.bot.db.drivers.count_documents({"guild_id": str(guild_id), "season_registered": True, "season_number": season, "elo": {"$gt": elo}})
            rank = higher + 1
        try:
            from ..core.rsl_xp import get_settings, progress_for_xp, leaderboard as xp_leaderboard
            xp = int(player.get("rsl_xp", 0) or 0)
            progress = progress_for_xp(xp, await get_settings(self.bot.db, guild_id))
            xp_rows = await xp_leaderboard(self.bot.db, guild_id, period="all")
            xp_rank = next((i + 1 for i,row in enumerate(xp_rows) if str(row.get("user_id")) == user_id), None)
        except Exception:
            log.exception("Unable to build XP profile data for %s in guild %s", user_id, guild_id)
            xp, progress, xp_rank = 0, {"level": 1}, None
        public_player = {
            "user_id": user_id, "discord_name": profile_name, "discord_username": discord_username, "avatar_url": avatar_url, "discord_original_name": discord_name, "discord_avatar_url": str(getattr(getattr(member, "display_avatar", None), "url", "") or ""),
            "game_name": str(prefs.get("game_name") or connection.get("game_name") or player.get("game_name") or player.get("game_id") or ""),
            "platform": str(prefs.get("platform") or player.get("platform") or ""),
            "driver_type": str(prefs.get("driver_type") or player.get("driver_type") or ""),
            "location": str(prefs.get("location") or player.get("location") or ""),
            "about": str(prefs.get("about") or player.get("about") or ""),
            "links": list(prefs.get("links") or player.get("links") or [])[:5],
            "asphalt_verified": connection.get("status") == "verified", "competition_rank": rank, "elo": elo,
            "season_number": season_number or season, "season_registered": season_registered,
            "career_wins": int(player.get("career_wins", 0) or 0), "career_played": int(player.get("career_played", 0) or 0), "streak": int(player.get("streak", 0) or 0),
            "xp_level": progress.get("level", 1), "xp_total": xp, "xp_rank": xp_rank,
        }
        return web.json_response({"player": public_player})

    async def platform_status_page(self, request: web.Request) -> web.Response:
        return await self._page_response("status.html", request)
