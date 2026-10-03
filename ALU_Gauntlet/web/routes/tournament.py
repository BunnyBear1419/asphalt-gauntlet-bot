"""RSL web tournament route family."""
from .._web_context import *

class TournamentRoutesMixin:
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

    async def tournaments_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("tournaments.html", request)

    async def tournaments(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        guild_ids = await self._live_guild_ids_for_user(user)
        rows = []
        async for item in self.bot.db.tournaments.find({"guild_id": {"$in": list(guild_ids)}}).sort("start_time", 1):
            item["id"] = str(item.get("_id"))
            item.pop("_id", None)
            if int(item.get("team_size", 1)) > 1:
                count = await self.bot.db.tournament_club_registrations.count_documents(
                    {"tournament_id": item["id"], "guild_id": str(item.get("guild_id")), "status": {"$in": ["pending", "accepted", "checked_in"]}}
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
        if not item or str(item.get("guild_id")) not in await self._live_guild_ids_for_user(user):
            raise web.HTTPNotFound(text="Tournament not found.")
        detail_guild = next((g for g in getattr(self.bot, "guilds", []) if str(getattr(g, "id", "")) == str(item.get("guild_id"))), None)
        item["can_manage_results"] = bool(
            detail_guild and await self._is_live_tournament_staff(user, str(item.get("guild_id")), detail_guild)
        )
        item["result_submission_mode"] = str(item.get("result_submission_mode") or "player_review")
        item["result_submission_mode_label"] = "Admin Only" if item["result_submission_mode"] == "admin_only" else "Player Submission + Admin Verification"
        item["id"] = tournament_id
        item.pop("_id", None)
        registrations = []
        async for row in self.bot.db.tournament_registrations.find(
            {"tournament_id": tournament_id, "guild_id": str(item.get("guild_id")) if "item" in locals() else None, "status": {"$in": ["pending", "accepted", "checked_in"]}}
        ).sort("registered_at", 1):
            row["registration_id"] = str(row.get("_id", ""))
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
                club = await self.bot.db.clubs.find_one({"_id": ObjectId(reg["club_id"]), "guild_id": str(item.get("guild_id"))})
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
                clubs.append({"id": reg["club_id"], "registration_id": str(reg.get("_id", "")), "name": club.get("name", "Club"), "image": club.get("image", ""), "about": club.get("about", ""), "status": reg.get("status", "pending"), "lineup": reg.get("lineup", []), "members": members, "registered_by": reg.get("registered_by"), "leader_id": club.get("leader_id")})
            item["clubs"] = clubs
            item["teams"] = []
        else:
            item["clubs"] = []
            item["teams"] = []
        return web.json_response(item)

    async def tournament_registration_action(self, request: web.Request) -> web.Response:
        """Approve or reject one pending tournament registration as tournament staff."""
        user, guild_id, _ = await self.require_tournament_admin(request)
        from bson import ObjectId

        try:
            payload = await self._json_object(request)
        except Exception as exc:
            raise web.HTTPBadRequest(text="Invalid JSON body.") from exc

        tournament_id = str(payload.get("tournament_id", "")).strip()
        registration_id = str(payload.get("registration_id", "")).strip()
        action = str(payload.get("action", "")).strip().casefold()

        if not ObjectId.is_valid(tournament_id) or not ObjectId.is_valid(registration_id):
            raise web.HTTPBadRequest(text="Invalid tournament or registration ID.")
        if action not in {"approve", "reject"}:
            raise web.HTTPBadRequest(text="Action must be approve or reject.")

        tournament = await self.bot.db.tournaments.find_one(
            {"_id": ObjectId(tournament_id), "guild_id": guild_id}
        )
        if not tournament:
            raise web.HTTPNotFound(text="Tournament not found.")

        if tournament.get("status") not in {"registration_open", "open"}:
            raise web.HTTPConflict(text="Registration decisions are closed once the tournament is live.")

        team_size = int(tournament.get("team_size", 1))
        collection = (
            self.bot.db.tournament_club_registrations
            if team_size > 1
            else self.bot.db.tournament_registrations
        )
        registration = await collection.find_one(
            {"_id": ObjectId(registration_id), "tournament_id": tournament_id}
        )
        if not registration:
            raise web.HTTPNotFound(text="Tournament registration not found.")

        current_status = str(registration.get("status", "pending"))
        if current_status != "pending":
            raise web.HTTPConflict(
                text=f"This registration has already been {current_status.replace('_', ' ')}."
            )

        if action == "approve":
            accepted_statuses = {"accepted", "checked_in"}
            accepted_count = await collection.count_documents(
                {"tournament_id": tournament_id, "status": {"$in": list(accepted_statuses)}}
            )
            if accepted_count >= int(tournament.get("max_players", 32)):
                raise web.HTTPConflict(text="The tournament has reached its entrant capacity.")

            # Team entries must have a complete lineup before staff approval.
            if team_size > 1:
                lineup = registration.get("lineup") or []
                if len(lineup) != team_size or len(set(map(str, lineup))) != team_size:
                    raise web.HTTPConflict(
                        text="The club must save a complete tournament lineup before approval."
                    )

            result = await collection.update_one(
                {"_id": registration["_id"], "status": "pending"},
                {"$set": {
                    "status": "accepted",
                    "approved_by": str(user.user_id),
                    "approved_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
            if not result.modified_count:
                raise web.HTTPConflict(text="This registration was already processed.")
            await self._audit(
                guild_id,
                user.user_id,
                f"Tournament registration approved: {tournament_id}/{registration_id}",
            )
            return web.json_response({"ok": True, "status": "accepted", "message": "Registration approved."})

        result = await collection.update_one(
            {"_id": registration["_id"], "status": "pending"},
            {"$set": {
                "status": "rejected",
                "rejected_by": str(user.user_id),
                "rejected_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        if not result.modified_count:
            raise web.HTTPConflict(text="This registration was already processed.")
        await self._audit(
            guild_id,
            user.user_id,
            f"Tournament registration rejected: {tournament_id}/{registration_id}",
        )
        return web.json_response({"ok": True, "status": "rejected", "message": "Registration rejected."})

    async def tournament_club_lineup(self, request: web.Request) -> web.Response:
        user, _live_guild_id, _ = await self.require_guild_member(request)
        from bson import ObjectId
        payload = await self._json_object(request)
        tournament_id = str(payload.get("tournament_id", "")).strip()
        club_id = str(payload.get("club_id", "")).strip()
        try:
            ObjectId(tournament_id)
            ObjectId(club_id)
        except Exception:
            raise web.HTTPBadRequest(text="Invalid tournament or club ID.")
        tournament = await self.bot.db.tournaments.find_one({"_id": ObjectId(tournament_id)})
        club = await self.bot.db.clubs.find_one({"_id": ObjectId(club_id)})
        if not tournament or not club or str(tournament.get("guild_id")) not in await self._live_guild_ids_for_user(user) or str(club.get("guild_id")) != str(tournament.get("guild_id")):
            raise web.HTTPNotFound(text="Tournament or club not found.")
        if str(club.get("leader_id")) != str(user.user_id):
            raise web.HTTPForbidden(text="Only the club leader can set the tournament lineup.")
        if tournament.get("status") not in {"registration_open", "open"}:
            raise web.HTTPConflict(text="Tournament lineups are locked once the tournament starts.")
        reg = await self.bot.db.tournament_club_registrations.find_one({"tournament_id": tournament_id, "guild_id": str(tournament.get("guild_id")), "club_id": club_id})
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

    async def tournament_match_result(self, request: web.Request) -> web.Response:
        """Submit a participant result for staff verification."""
        user = await self.require_user(request)
        from bson import ObjectId
        payload = await self._json_object(request)
        try:
            oid = ObjectId(str(payload.get("tournament_id", "")))
        except Exception:
            raise web.HTTPBadRequest(text="Invalid tournament ID.")
        t = await self.bot.db.tournaments.find_one({"_id": oid})
        if not t or str(t.get("guild_id")) not in await self._live_guild_ids_for_user(user):
            raise web.HTTPNotFound(text="Tournament not found.")
        if t.get("status") != "live":
            raise web.HTTPConflict(text="Tournament is not live.")
        match_id = str(payload.get("match_id", "")).strip()
        winner_id = str(payload.get("winner_id", "")).strip()
        proof_url = str(payload.get("proof_url", "")).strip()
        notes = str(payload.get("notes", "")).strip()[:500]
        bracket = t.get("bracket") or {}
        groups = []
        for key in ("rounds", "winners", "losers"):
            groups.extend(bracket.get(key) or [])
        for key in ("grand_final", "grand_final_reset"):
            if isinstance(bracket.get(key), dict):
                groups.append({"matches": [bracket[key]]})
        matches = [m for group in groups for m in group.get("matches", [])]
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
                {"tournament_id": str(oid), "guild_id": str(t.get("guild_id")), "club_id": {"$in": slots}, "lineup": str(user.user_id), "status": {"$in": ["accepted", "checked_in"]}}
            )
            participant_ok = bool(reg)
        else:
            participant_ok = str(user.user_id) in slots
        match_guild = next((g for g in getattr(self.bot, "guilds", []) if str(getattr(g, "id", "")) == str(t.get("guild_id"))), None)
        is_staff = bool(
            match_guild is not None and await self._is_live_guild_staff(user, str(t.get("guild_id")), match_guild)
        )
        result_mode = str(t.get("result_submission_mode") or "player_review").casefold()
        if result_mode == "admin_only" and not is_staff:
            raise web.HTTPForbidden(text="This tournament is configured for Admin Only result submission.")
        if not participant_ok and not is_staff:
            raise web.HTTPForbidden(text="Only a participant or staff member for this server can submit its result.")
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
            await self._release_tournament_action(str(oid), match_id, "submit")
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
        """Tournament-admin verification endpoint for all supported tournament formats."""
        user, guild_id, _ = await self.require_tournament_admin(request)
        from bson import ObjectId
        payload = await self._json_object(request)
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
        groups = []
        for key in ("rounds", "winners", "losers"):
            groups.extend(bracket.get(key) or [])
        for key in ("grand_final", "grand_final_reset"):
            if isinstance(bracket.get(key), dict):
                groups.append({"matches": [bracket[key]]})
        match = next((m for group in groups for m in group.get("matches", []) if str(m.get("id")) == match_id), None)
        if not match:
            raise web.HTTPNotFound(text="Match not found.")
        if match.get("result_status") != "pending":
            raise web.HTTPConflict(text="This match does not have a pending result.")
        if not await self._claim_tournament_action(str(oid), match_id, "verify"):
            raise web.HTTPConflict(text="Another staff action is already processing this match.")
        try:
            if action == "reject":
                for key in ("result_status", "winner_id", "submitted_by", "submitted_at", "proof_url", "result_notes"):
                    match.pop(key, None)
                match["status"] = "ready"
                await self.bot.db.tournaments.update_one(
                    {"_id": oid},
                    {"$set": {"bracket": bracket, "updated_at": datetime.now(timezone.utc).isoformat()}},
                )
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
                    target_match = next((n for g in groups for n in g.get("matches", []) if str(n.get("id")) == str(target)), None)
                    if target_match is None:
                        raise web.HTTPConflict(text="Bracket advancement target is invalid.")
                    ns = list(target_match.get("player_slots") or [None, None])
                    while len(ns) < 2:
                        ns.append(None)
                    if all(ns) and winner_id not in [str(x) for x in ns]:
                        raise web.HTTPConflict(text="Bracket advancement target is already occupied.")
                    if winner_id not in [str(x) for x in ns]:
                        ns[0 if ns[0] is None else 1] = winner_id
                    target_match["player_slots"] = ns
                    if all(ns):
                        target_match["status"] = "ready"

                loser_to = match.get("loser_to")
                if loser_to and str(match.get("bracket")) == "winners":
                    loser_id = next((x for x in slots if x != winner_id), None)
                    if loser_id:
                        target_match = next((n for g in groups for n in g.get("matches", []) if str(n.get("id")) == str(loser_to)), None)
                        if target_match is None:
                            raise web.HTTPConflict(text="Losers-bracket destination is invalid.")
                        ns = list(target_match.get("player_slots") or [None, None])
                        while len(ns) < 2:
                            ns.append(None)
                        if loser_id not in [str(x) for x in ns]:
                            if all(ns):
                                raise web.HTTPConflict(text="Losers-bracket destination is already occupied.")
                            ns[0 if ns[0] is None else 1] = loser_id
                        target_match["player_slots"] = ns
                        if all(ns):
                            target_match["status"] = "ready"

                fmt = str(t.get("format") or bracket.get("type") or "single_elimination").casefold()
                if fmt == "round_robin":
                    rr_matches = [m for g in bracket.get("rounds", []) for m in g.get("matches", [])]
                    if rr_matches and all(m.get("status") == "completed" for m in rr_matches):
                        wins = {}
                        losses = {}
                        seed_order = {}
                        for idx, m in enumerate(rr_matches):
                            pair = [str(x) for x in (m.get("player_slots") or []) if x]
                            if len(pair) != 2:
                                continue
                            seed_order.setdefault(pair[0], idx)
                            seed_order.setdefault(pair[1], idx)
                            w = str(m.get("winner_id") or "")
                            if w in pair:
                                l = pair[1] if w == pair[0] else pair[0]
                                wins[w] = wins.get(w, 0) + 1
                                losses[l] = losses.get(l, 0) + 1
                        entrants = sorted(set(wins) | set(losses), key=lambda x: (-wins.get(x, 0), losses.get(x, 0), seed_order.get(x, 10**9), x))
                        t["standings"] = [{"entrant_id": x, "wins": wins.get(x, 0), "losses": losses.get(x, 0)} for x in entrants]
                        if entrants:
                            t["status"] = "completed"
                            t["champion_id"] = entrants[0]
                            t["completed_at"] = datetime.now(timezone.utc).isoformat()
                elif fmt == "double_elimination":
                    if match.get("id") == "GF-M1":
                        protected = str(bracket.get("protected_finalist") or "")
                        if winner_id == protected:
                            t["status"] = "completed"
                            t["champion_id"] = winner_id
                            t["completed_at"] = datetime.now(timezone.utc).isoformat()
                            loser = next((str(x) for x in (match.get("player_slots") or []) if str(x) != str(winner_id)), None)
                            lb_final = next((
                                m for group in (bracket.get("losers") or [])
                                for m in (group.get("matches") or [])
                                if m.get("winner_to") == "GF-M1" and m.get("status") == "completed"
                            ), None)
                            lb_loser = None
                            if lb_final:
                                lb_winner = str(lb_final.get("winner_id") or "")
                                lb_loser = next(
                                    (str(x) for x in (lb_final.get("player_slots") or []) if str(x) != lb_winner),
                                    None,
                                )
                            t["standings"] = ([{"entrant_id": str(winner_id)}] +
                                              ([{"entrant_id": loser}] if loser else []) +
                                              ([{"entrant_id": lb_loser}] if lb_loser else []))
                        else:
                            reset = bracket.get("grand_final_reset")
                            if isinstance(reset, dict):
                                reset["player_slots"] = [protected, winner_id]
                                reset["status"] = "ready"
                                bracket["grand_final_reset"] = reset
                    elif match.get("id") == "GF-M2":
                        t["status"] = "completed"
                        t["champion_id"] = winner_id
                        t["completed_at"] = datetime.now(timezone.utc).isoformat()
                        loser = next((str(x) for x in (match.get("player_slots") or []) if str(x) != str(winner_id)), None)
                        lb_final = next((
                            m for group in (bracket.get("losers") or [])
                            for m in (group.get("matches") or [])
                            if m.get("winner_to") == "GF-M1" and m.get("status") == "completed"
                        ), None)
                        lb_loser = None
                        if lb_final:
                            lb_winner = str(lb_final.get("winner_id") or "")
                            lb_loser = next(
                                (str(x) for x in (lb_final.get("player_slots") or []) if str(x) != lb_winner),
                                None,
                            )
                        t["standings"] = ([{"entrant_id": str(winner_id)}] +
                                          ([{"entrant_id": loser}] if loser else []) +
                                          ([{"entrant_id": lb_loser}] if lb_loser else []))
                    elif match.get("bracket") == "winners" and match.get("winner_to") == "GF-M1" and winner_id:
                        # The Winners Final feeds the first Grand Final match, so its
                        # winner is the protected finalist for the double-elimination
                        # reset rule. The Winners Final always has winner_to=GF-M1;
                        # checking for a missing winner_to here would never fire.
                        bracket["protected_finalist"] = winner_id

                await self.bot.db.tournaments.update_one(
                    {"_id": oid},
                    {"$set": {
                        "bracket": bracket,
                        "status": t.get("status", "live"),
                        "champion_id": t.get("champion_id"),
                        "standings": t.get("standings"),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }},
                )
                message = "Result verified and tournament state advanced."
        finally:
            await self._release_tournament_action(str(oid), match_id, "verify")

        if t.get("status") == "completed":
            try:
                from ...core.rsl_tournament_rewards import settle_tournament_rewards
                await settle_tournament_rewards(self.bot.db, t)
            except Exception:
                log.exception("Failed to settle tournament rewards for %s", t.get("_id"))
            await self._sync_completed_tournament_roles(t)
        cfg = await self.bot.db.settings.find_one({"_id": guild_id}) or {}
        channel_id = cfg.get("match_results_channel_id")
        channel = self.bot.get_channel(int(channel_id)) if channel_id else None
        if channel is not None:
            try:
                await channel.send("🏆 **Tournament Result " + ("Approved" if action != "reject" else "Rejected") + "** • " + str(t.get("name", "Tournament")) + " • " + match_id)
            except Exception:
                log.exception("Unable to post tournament verification notice")
        return web.json_response({"ok": True, "message": message, "bracket": bracket, "champion_id": t.get("champion_id"), "standings": t.get("standings")})

    async def _sync_completed_tournament_roles(self, tournament: dict[str, Any]) -> None:
        """Best-effort Discord recognition after a tournament becomes completed."""
        guild_id = str(tournament.get("guild_id") or "")
        guild = next((g for g in getattr(self.bot, "guilds", []) if str(getattr(g, "id", "")) == guild_id), None)
        if guild is None:
            return
        try:
            from ...core.rsl_tournament_rewards import sync_completed_tournament_roles
            settings = await self.bot.db.settings.find_one({"_id": guild_id}) or {}
            await sync_completed_tournament_roles(
                self.bot.db,
                guild,
                tournament,
                role_names=settings.get("achievement_role_names"),
                role_ids=settings.get("achievement_role_ids"),
            )
        except Exception:
            log.exception("Failed to synchronize tournament roles for completed tournament %s", tournament.get("_id"))
    async def _tournament_result_payload(self, tournament: dict[str, Any]) -> dict[str, Any]:
        """Build normalized standings/history from the verified tournament bracket."""
        bracket = tournament.get("bracket") or {}
        groups = []
        for key in ("rounds", "winners", "losers"):
            groups.extend(bracket.get(key) or [])
        for key in ("grand_final", "grand_final_reset"):
            if isinstance(bracket.get(key), dict):
                groups.append({"name": "Grand Final", "matches": [bracket[key]]})
        matches = [m for group in groups for m in group.get("matches", [])]
        entrant_ids, seen = [], set()
        for m in matches:
            for entrant in (m.get("player_slots") or []):
                if entrant and str(entrant) not in seen:
                    seen.add(str(entrant)); entrant_ids.append(str(entrant))
        wins = {x: 0 for x in entrant_ids}; losses = {x: 0 for x in entrant_ids}; played = {x: 0 for x in entrant_ids}
        last_loss, last_round = {}, {x: 0 for x in entrant_ids}
        for m in matches:
            if m.get("status") != "completed" and m.get("result_status") != "verified": continue
            slots = [str(x) for x in (m.get("player_slots") or []) if x]; winner = str(m.get("winner_id") or "")
            if winner not in slots: continue
            round_no = int(m.get("round") or 0); when = str(m.get("verified_at") or m.get("submitted_at") or "")
            for entrant in slots:
                played[entrant] = played.get(entrant, 0) + 1
                last_round[entrant] = max(last_round.get(entrant, 0), round_no)
            wins[winner] = wins.get(winner, 0) + 1
            loser = next((x for x in slots if x != winner), None)
            if loser:
                losses[loser] = losses.get(loser, 0) + 1
                last_loss[loser] = (round_no, when, str(m.get("id") or ""))
        champion_id = str(tournament.get("champion_id") or "")
        ordered = list(entrant_ids)
        ordered.sort(key=lambda x: (0 if x == champion_id else 1, -wins.get(x, 0), losses.get(x, 0), -last_round.get(x, 0), str(last_loss.get(x, ("", "", ""))[1]), x))
        placements = {}
        if champion_id: placements[champion_id] = 1
        placement = 2
        grouped = {}
        for x in [x for x in ordered if x != champion_id]:
            grouped.setdefault(last_loss.get(x, (0, "", ""))[0], []).append(x)
        for key in sorted(grouped, reverse=True):
            for x in grouped[key]: placements[x] = placement
            placement += len(grouped[key])
        rows = []
        for x in ordered:
            name = x
            if int(tournament.get("team_size", 1)) > 1:
                from bson import ObjectId
                club = await self.bot.db.clubs.find_one({"_id": ObjectId(x)}) if ObjectId.is_valid(x) else None
                name = str(club.get("name", x)) if club else x
            else:
                try:
                    member = self.bot.get_user(int(x)) or await self.bot.fetch_user(int(x))
                    name = str(getattr(member, "display_name", None) or getattr(member, "name", None) or x)
                except Exception:
                    name = x
            rows.append({"entrant_id": x, "name": name, "placement": placements.get(x), "wins": wins.get(x, 0), "losses": losses.get(x, 0), "matches_played": played.get(x, 0)})
        rows.sort(key=lambda x: (x["placement"] if x["placement"] is not None else 9999, -x["wins"], x["name"].casefold()))
        name_map = {x["entrant_id"]: x["name"] for x in rows}
        return {"tournament_id": str(tournament.get("_id") or ""), "name": tournament.get("name", "Tournament"), "status": tournament.get("status", "draft"), "format": tournament.get("format", "single_elimination"), "team_size": int(tournament.get("team_size", 1)), "champion_id": champion_id or None, "champion_name": next((x["name"] for x in rows if x["entrant_id"] == champion_id), None), "standings": rows, "matches": [{"id": str(m.get("id") or ""), "round": int(m.get("round") or 0), "bracket": m.get("bracket", "winners"), "player_slots": [str(x) for x in (m.get("player_slots") or []) if x], "entrant_names": [name_map.get(str(x), str(x)) for x in (m.get("player_slots") or []) if x], "winner_id": str(m.get("winner_id") or ""), "winner_name": name_map.get(str(m.get("winner_id") or ""), str(m.get("winner_id") or "")), "status": m.get("status", "waiting"), "result_status": m.get("result_status", ""), "proof_url": m.get("proof_url", ""), "verified_at": m.get("verified_at", "")} for m in matches if m.get("status") == "completed" or m.get("result_status") == "verified"]}

    async def tournament_results(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        guild_ids = {str(x) for x in getattr(user, "guild_ids", [])}
        requested = str(request.query.get("tournament_id", "")).strip()
        query = {"guild_id": {"$in": list(guild_ids)}, "status": "completed"}
        if requested:
            from bson import ObjectId
            if not ObjectId.is_valid(requested): raise web.HTTPBadRequest(text="Invalid tournament ID.")
            query["_id"] = ObjectId(requested)
        rows = []
        async for tournament in self.bot.db.tournaments.find(query).sort("completed_at", -1).limit(50):
            result = await self._tournament_result_payload(tournament)
            result["media_count"] = await self.bot.db.tournament_media.count_documents({"tournament_id": str(tournament["_id"]), "status": "approved"})
            result["completed_at"] = tournament.get("completed_at")
            rows.append(result)
        if requested and not rows: raise web.HTTPNotFound(text="Completed tournament not found.")
        return web.json_response({"tournaments": rows, "selected": rows[0] if requested and rows else None})

    async def tournament_media(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        tournament_id = str(request.match_info.get("tournament_id", "")).strip()
        from bson import ObjectId
        if not ObjectId.is_valid(tournament_id): raise web.HTTPBadRequest(text="Invalid tournament ID.")
        tournament = await self.bot.db.tournaments.find_one({"_id": ObjectId(tournament_id)})
        if not tournament or str(tournament.get("guild_id")) not in await self._live_guild_ids_for_user(user): raise web.HTTPNotFound(text="Tournament not found.")
        guild = next((g for g in getattr(self.bot, "guilds", []) if str(getattr(g, "id", "")) == str(tournament.get("guild_id"))), None)
        staff = bool(guild and await self._is_live_tournament_staff(user, str(tournament.get("guild_id")), guild))
        statuses = ["approved", "pending"] if staff and request.query.get("include_pending") == "1" else ["approved"]
        rows = []
        async for item in self.bot.db.tournament_media.find({"tournament_id": tournament_id, "guild_id": str(tournament.get("guild_id")), "status": {"$in": statuses}}).sort("created_at", -1).limit(100):
            rows.append({"id": str(item["_id"]), "type": item.get("type", "image"), "mime_type": item.get("mime_type", ""), "filename": item.get("filename", "Tournament Media"), "title": item.get("title", ""), "caption": item.get("caption", ""), "status": item.get("status", "approved"), "uploaded_by": item.get("uploaded_by", ""), "created_at": item.get("created_at", ""), "url": f"/assets/tournament-media/{item['_id']}"})
        return web.json_response({"tournament_id": tournament_id, "media": rows, "can_manage_media": staff})

    async def _tournament_media_participant(self, user: Any, tournament: dict[str, Any]) -> bool:
        tid = str(tournament["_id"]); uid = str(user.user_id)
        if int(tournament.get("team_size", 1)) > 1:
            async for reg in self.bot.db.tournament_club_registrations.find({"tournament_id": tid, "status": {"$in": ["accepted", "checked_in"]}}):
                if uid in {str(x) for x in (reg.get("lineup") or [])}: return True
            return False
        return bool(await self.bot.db.tournament_registrations.find_one({"tournament_id": tid, "user_id": uid, "status": {"$in": ["pending", "accepted", "checked_in"]}}))

    async def tournament_media_upload(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        max_size = 12 * 1024 * 1024
        reader = await request.multipart()
        fields, file_field = {}, None
        while True:
            field = await reader.next()
            if field is None: break
            if field.name == "file": file_field = field
            else: fields[field.name] = (await field.text())[:500]
        tournament_id = str(fields.get("tournament_id", "")).strip()
        from bson import ObjectId
        if not ObjectId.is_valid(tournament_id): raise web.HTTPBadRequest(text="Invalid tournament ID.")
        tournament = await self.bot.db.tournaments.find_one({"_id": ObjectId(tournament_id)})
        if not tournament or str(tournament.get("guild_id")) not in await self._live_guild_ids_for_user(user): raise web.HTTPNotFound(text="Tournament not found.")
        guild = next((g for g in getattr(self.bot, "guilds", []) if str(getattr(g, "id", "")) == str(tournament.get("guild_id"))), None)
        staff = bool(guild and await self._is_live_tournament_staff(user, str(tournament.get("guild_id")), guild))
        if not staff and not await self._tournament_media_participant(user, tournament): raise web.HTTPForbidden(text="Only tournament participants or tournament staff can upload media.")
        if file_field is None: raise web.HTTPBadRequest(text="Choose an image or video to upload.")
        content_type = str(file_field.headers.get("Content-Type", "")).lower().split(";", 1)[0]
        allowed = {"image/jpeg": "image", "image/png": "image", "image/webp": "image", "image/gif": "image", "video/mp4": "video", "video/webm": "video", "video/quicktime": "video"}
        media_type = allowed.get(content_type)
        if not media_type: raise web.HTTPBadRequest(text="Supported media: JPG, PNG, WEBP, GIF, MP4, WEBM, or MOV.")
        data = bytes(await file_field.read())
        if not data: raise web.HTTPBadRequest(text="The selected file is empty.")
        if len(data) > max_size: raise web.HTTPRequestEntityTooLarge(max_size=max_size, actual_size=len(data))

        # Bound both per-user and per-tournament submissions so repeated uploads
        # cannot grow storage without limit. Production Mongo stores binary media in GridFS;
        # lightweight test databases may retain the inline fallback.
        max_user_media = 20
        max_tournament_media = 100
        user_media_count = await self.bot.db.tournament_media.count_documents({
            "tournament_id": tournament_id,
            "uploaded_by": str(user.user_id),
            "status": {"$ne": "rejected"},
        })
        if user_media_count >= max_user_media:
            raise web.HTTPConflict(
                text="You have reached the tournament media submission limit for this tournament."
            )
        tournament_media_count = await self.bot.db.tournament_media.count_documents({
            "tournament_id": tournament_id,
        })
        if tournament_media_count >= max_tournament_media:
            raise web.HTTPConflict(
                text="This tournament has reached its media submission limit."
            )

        filename = Path(file_field.filename or ("tournament-media." + ("mp4" if media_type == "video" else "png"))).name[:160]
        # Browser MIME types are advisory. Require a matching file signature.
        signatures = {
            "image/jpeg": data[:3] == bytes.fromhex("ffd8ff"),
            "image/png": data[:8] == bytes.fromhex("89504e470d0a1a0a"),
            "image/webp": len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP",
            "image/gif": data[:6] in {b"GIF87a", b"GIF89a"},
            "video/webm": data[:4] == bytes.fromhex("1a45dfa3"),
            "video/mp4": len(data) >= 12 and data[4:8] == b"ftyp",
            "video/quicktime": len(data) >= 12 and data[4:8] == b"ftyp",
        }
        if not signatures.get(content_type, False):
            raise web.HTTPBadRequest(text="The uploaded file does not match its declared media type.")
        if media_type == "image":
            try:
                with Image.open(BytesIO(data)) as image:
                    image.verify()
                    if image.width > 4096 or image.height > 4096:
                        raise ValueError("image dimensions are too large")
                    if image.width * image.height > 16_777_216:
                        raise ValueError("image pixel count is too large")
            except Image.DecompressionBombError as exc:
                raise web.HTTPBadRequest(text="The selected image exceeds the safe pixel limit.") from exc
            except (OSError, ValueError) as exc:
                raise web.HTTPBadRequest(text="The selected image could not be validated.") from exc
        media_id = hashlib.sha256(f"{tournament_id}:{user.user_id}:{time.time()}".encode() + data).hexdigest()[:32]
        status = "approved" if staff else "pending"; now = datetime.now(timezone.utc).isoformat()
        document = {"_id": media_id, "tournament_id": tournament_id, "guild_id": str(tournament.get("guild_id")), "type": media_type, "mime_type": content_type, "filename": filename, "title": str(fields.get("title", "")).strip()[:120], "caption": str(fields.get("caption", "")).strip()[:500], "status": status, "uploaded_by": str(user.user_id), "created_at": now, "approved_by": str(user.user_id) if staff else None, "approved_at": now if staff else None}
        client = getattr(self.bot.db, "client", None)
        gridfs_id = None
        if client is not None:
            from gridfs.asynchronous import AsyncGridFSBucket
            bucket = AsyncGridFSBucket(self.bot.db, bucket_name="rsl_tournament_media")
            gridfs_id = await bucket.upload_from_stream(filename, data, metadata={"tournament_id": tournament_id, "media_id": media_id, "guild_id": str(tournament.get("guild_id")), "content_type": content_type})
            document.update({"storage": "gridfs", "gridfs_id": str(gridfs_id)})
        else:
            document.update({"storage": "inline", "data": data})
        try:
            await self.bot.db.tournament_media.insert_one(document)
        except Exception:
            if gridfs_id is not None:
                try:
                    await bucket.delete(gridfs_id)
                except Exception:
                    log.exception("Failed to clean up orphaned tournament media GridFS file %s", gridfs_id)
            raise
        if not staff:
            cfg = await self.bot.db.settings.find_one({"_id": str(tournament.get("guild_id"))}) or {}
            channel_id = cfg.get("review_channel_id") or cfg.get("match_results_channel_id")
            channel = self.bot.get_channel(int(channel_id)) if channel_id else None
            if channel is not None:
                try:
                    from .tournament import TournamentMediaModerationView
                    await channel.send(f"📸 **Tournament Media Pending Approval**\n**{tournament.get('name','Tournament')}** • {filename}\nSubmitted by: <@{user.user_id}>\nUse the buttons below to publish or reject this media.", view=TournamentMediaModerationView(media_id))
                except Exception: log.exception("Unable to post tournament media moderation notice")
        return web.json_response({"ok": True, "status": status, "message": "Media uploaded and published." if staff else "Media uploaded for staff approval."})

    async def tournament_media_action(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_tournament_admin(request)
        payload = await self._json_object(request); media_id = str(payload.get("media_id", "")).strip(); action = str(payload.get("action", "")).strip().casefold()
        if action not in {"approve", "reject"}: raise web.HTTPBadRequest(text="Action must be approve or reject.")
        media = await self.bot.db.tournament_media.find_one({"_id": media_id, "guild_id": guild_id})
        if not media: raise web.HTTPNotFound(text="Media submission not found.")
        if media.get("status") != "pending": raise web.HTTPConflict(text="This media submission has already been reviewed.")
        now = datetime.now(timezone.utc).isoformat()
        update = {"$set": {"status": "approved" if action == "approve" else "rejected", "approved_by": str(user.user_id) if action == "approve" else None, "approved_at": now if action == "approve" else None, "reviewed_by": str(user.user_id), "reviewed_at": now}}
        if action == "reject":
            # Rejected submissions remain auditable without retaining their
            # potentially large binary payload in MongoDB.
            update["$unset"] = {"data": ""}
        result = await self.bot.db.tournament_media.update_one({"_id": media_id, "guild_id": guild_id, "status": "pending"}, update)
        if not result.modified_count:
            raise web.HTTPConflict(text="This media submission was already reviewed.")
        if action == "reject":
            # Remove the GridFS (or legacy inline) payload; metadata stays for audit.
            # A failed purge never fails the review: the startup sweep retries it.
            try:
                from ...core.rsl_media_cleanup import purge_media_payload
                await purge_media_payload(self.bot.db, media)
            except Exception:
                log.exception("Unable to purge rejected tournament media payload for %s", media_id)
        return web.json_response({"ok": True, "message": "Media approved and published." if action == "approve" else "Media rejected."})

    async def tournament_checkin(self, request: web.Request) -> web.Response:
        user, _live_guild_id, _ = await self.require_guild_member(request)
        from bson import ObjectId
        try:
            payload = await self._json_object(request)
            oid = ObjectId(str(payload.get("tournament_id", "")))
        except web.HTTPBadRequest:
            raise
        except Exception as exc:
            raise web.HTTPBadRequest(text="Invalid tournament ID.") from exc
        t = await self.bot.db.tournaments.find_one({"_id": oid})
        if not t or str(t.get("guild_id")) not in await self._live_guild_ids_for_user(user):
            raise web.HTTPNotFound(text="Tournament not found.")
        if t.get("status") not in {"registration_open", "open"}:
            raise web.HTTPConflict(text="Check-in is closed once the tournament is live or completed.")
        tid = str(oid)
        if int(t.get("team_size", 1)) > 1:
            checkin_payload = await self._json_object(request)
            requested_club_id = str(checkin_payload.get("club_id", "")).strip()
            reg_query = {"tournament_id": tid, "guild_id": str(tournament.get("guild_id")), "status": {"$in": ["pending", "accepted", "checked_in"]}}
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
                {"tournament_id": tid, "guild_id": str(t.get("guild_id")), "user_id": str(user.user_id), "status": {"$in": ["pending", "accepted"]}},
                {"$set": {"status": "checked_in", "checked_in_at": datetime.now(timezone.utc).isoformat()}},
            )
            if not result.modified_count:
                raise web.HTTPConflict(text="You must be registered before checking in.")
        return web.json_response({"ok": True, "message": "You are checked in."})

    async def tournament_start(self, request: web.Request) -> web.Response:
        user, guild_id, _ = await self.require_tournament_admin(request)
        from bson import ObjectId
        from ALU_Gauntlet.core.tournament import generate_tournament_bracket
        try:
            payload = await self._json_object(request)
            oid = ObjectId(str(payload.get("tournament_id", "")))
        except web.HTTPBadRequest:
            raise
        except Exception as exc:
            raise web.HTTPBadRequest(text="Invalid tournament ID.") from exc
        t = await self.bot.db.tournaments.find_one({"_id": oid, "guild_id": guild_id})
        if not t:
            raise web.HTTPNotFound(text="Tournament not found.")
        if t.get("status") not in {"registration_open", "open"}:
            raise web.HTTPConflict(text="Only a tournament still in registration can be started.")
        players = []
        if int(t.get("team_size", 1)) > 1:
            async for row in self.bot.db.tournament_club_registrations.find({"tournament_id": str(oid), "status": {"$in": ["accepted", "checked_in"]}}).sort("registered_at", 1):
                lineup = row.get("lineup") or []
                if len(lineup) != int(t.get("team_size", 1)):
                    raise web.HTTPConflict(text="Every registered club must save a complete tournament lineup before the tournament starts.")
                players.append(str(row["club_id"]))
        else:
            async for row in self.bot.db.tournament_registrations.find({"tournament_id": str(oid), "status": {"$in": ["accepted", "checked_in"]}}).sort("registered_at", 1):
                players.append(str(row["user_id"]))
        if len(players) < 2:
            raise web.HTTPConflict(text="At least 2 accepted entrants are required to start.")
        max_players = int(t.get("max_players", 32))
        fmt = str(t.get("format") or "single_elimination").casefold()
        if len(players) > max_players:
            raise web.HTTPConflict(text="Too many entrants for this tournament.")
        if fmt == "double_elimination":
            entrant_count = len(players)
            if entrant_count < 4 or entrant_count > 256 or (entrant_count & (entrant_count - 1)):
                raise web.HTTPConflict(
                    text="Double Elimination requires 4, 8, 16, 32, 64, 128, or 256 accepted entrants."
                )
            bracket = generate_tournament_bracket(fmt, entrant_count)
            for i, match in enumerate(bracket["winners"][0]["matches"]):
                match["player_slots"] = [players[i * 2], players[i * 2 + 1]]
                match["status"] = "ready"
        elif fmt == "round_robin":
            bracket = generate_tournament_bracket(fmt, len(players))
            seed_map = {i + 1: player for i, player in enumerate(players)}
            for group in bracket["rounds"]:
                for match in group["matches"]:
                    match["player_slots"] = [seed_map.get(x) for x in match.get("seed_slots", [])]
                    match.pop("seed_slots", None)
                    match["status"] = "ready"
        else:
            bracket = generate_tournament_bracket("single_elimination", max_players)
            slots = players + [None] * (max_players - len(players))
            for i, match in enumerate(bracket["rounds"][0]["matches"]):
                match["player_slots"] = [slots[i * 2], slots[i * 2 + 1]]
                match["status"] = "ready" if all(match["player_slots"]) else "bye" if any(match["player_slots"]) else "waiting"
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
                                for next_group in bracket["rounds"]:
                                    for nxt in next_group["matches"]:
                                        if nxt.get("id") == target:
                                            ns = nxt.setdefault("player_slots", [None, None])
                                            ns[0 if ns[0] is None else 1] = winner
                                            nxt["status"] = "ready" if all(ns) else "bye"
                                            changed = True
                                            break
                        elif match.get("status") == "bye" and not slots_now:
                            match["status"] = "waiting"
        if not await self._claim_tournament_action(str(oid), "START", "start"):
            raise web.HTTPConflict(text="Another tournament start operation is already being processed.")
        try:
            started_at = datetime.now(timezone.utc).isoformat()
            transition = await self.bot.db.tournaments.update_one(
            {"_id": oid, "status": {"$in": ["registration_open", "open"]}},
            {"$set": {"status": "live", "started_at": started_at, "bracket": bracket, "started_by": str(user.user_id), "updated_at": started_at}},
        )
            if not transition.modified_count:
                raise web.HTTPConflict(text="Tournament start was already completed by another staff action.")
            return web.json_response({"ok": True, "message": "Tournament started.", "bracket": bracket})
        finally:
            await self._release_tournament_action(str(oid), "START")
