"""RSL web clubs route family."""
from datetime import timedelta
from bson import ObjectId
from .._web_context import *

class ClubsRoutesMixin:
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
            user, _live_guild_id, _ = await self.require_guild_member(request)
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
    
    
    async def transfer_club_leadership(self, request: web.Request) -> web.Response:
        user, _live_guild_id, _ = await self.require_guild_member(request)
        payload = await request.json()
        try:
            club_id = ObjectId(str(payload.get("club_id", "")))
        except Exception:
            raise web.HTTPBadRequest(text="Invalid club ID.")
        target_id = str(payload.get("user_id", "")).strip()
        if not target_id:
            raise web.HTTPBadRequest(text="A replacement leader is required.")
        club = await self.bot.db.clubs.find_one({"_id": club_id})
        if not club or str(club.get("guild_id")) not in {str(x) for x in user.guild_ids}:
            raise web.HTTPNotFound(text="Club not found.")
        if str(club.get("leader_id")) != str(user.user_id):
            raise web.HTTPForbidden(text="Only the current club leader can transfer leadership.")
        if target_id == str(user.user_id):
            raise web.HTTPBadRequest(text="You are already the club leader.")
        target = await self.bot.db.club_members.find_one({"club_id": str(club_id), "user_id": target_id})
        if not target:
            raise web.HTTPBadRequest(text="The replacement leader must already be a club member.")
        now = datetime.now(timezone.utc).isoformat()
        updated = await self.bot.db.clubs.update_one(
            {"_id": club_id, "leader_id": str(user.user_id)},
            {"$set": {"leader_id": target_id, "updated_at": now}},
        )
        if not updated.modified_count:
            raise web.HTTPConflict(text="Club leadership changed before your transfer completed.")
        await self.bot.db.club_members.update_one(
            {"club_id": str(club_id), "user_id": str(user.user_id)},
            {"$set": {"role": "officer"}},
        )
        await self.bot.db.club_members.update_one(
            {"club_id": str(club_id), "user_id": target_id},
            {"$set": {"role": "leader"}},
        )
        await self._club_notify_user(target_id, "Club leadership transferred", f"You are now the Leader of {club.get('name', 'the club')}.")
        return web.json_response({"ok": True, "message": "Club leadership transferred. You are now an Officer."})

    async def delete_club(self, request: web.Request) -> web.Response:
        user, _live_guild_id, _ = await self.require_guild_member(request)
        payload = await request.json()
        try:
            club_id = ObjectId(str(payload.get("club_id", "")))
        except Exception:
            raise web.HTTPBadRequest(text="Invalid club ID.")
        club = await self.bot.db.clubs.find_one({"_id": club_id})
        if not club or str(club.get("guild_id")) not in {str(x) for x in user.guild_ids}:
            raise web.HTTPNotFound(text="Club not found.")
        if str(club.get("leader_id")) != str(user.user_id):
            raise web.HTTPForbidden(text="Only the club leader can delete the club.")
        registrations = await self.bot.db.tournament_club_registrations.count_documents({"club_id": str(club_id)})
        if registrations:
            raise web.HTTPConflict(text="This club has tournament history or registrations and cannot be deleted. Contact staff if the club needs to be retired.")
        await self.bot.db.club_invitations.delete_many({"club_id": str(club_id)})
        await self.bot.db.club_join_requests.delete_many({"club_id": str(club_id)})
        await self.bot.db.club_members.delete_many({"club_id": str(club_id)})
        result = await self.bot.db.clubs.delete_one({"_id": club_id, "leader_id": str(user.user_id)})
        if not result.deleted_count:
            raise web.HTTPConflict(text="Club changed before deletion completed.")
        return web.json_response({"ok": True, "message": "Club deleted."})

    async def update_club(self, request: web.Request) -> web.Response:
            user, _live_guild_id, _ = await self.require_guild_member(request)
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
            user, _live_guild_id, _ = await self.require_guild_member(request)
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
    
    
    async def leave_club(self, request: web.Request) -> web.Response:
            user, _live_guild_id, _ = await self.require_guild_member(request)
            payload = await request.json()
            from bson import ObjectId
            try:
                oid = ObjectId(str(payload.get("club_id", "")))
            except Exception as exc:
                raise web.HTTPBadRequest(text="Invalid club ID.") from exc
            club = await self.bot.db.clubs.find_one({"_id": oid})
            if not club or str(club.get("guild_id")) not in {str(x) for x in user.guild_ids}:
                raise web.HTTPNotFound(text="Club not found.")
            if str(club.get("leader_id")) == str(user.user_id):
                raise web.HTTPConflict(text="Club leaders must transfer leadership before leaving.")
            removed = await self.bot.db.club_members.delete_one({"club_id": str(oid), "user_id": str(user.user_id)})
            if not removed.deleted_count:
                raise web.HTTPConflict(text="You are not a member of this club.")
            await self.bot.db.clubs.update_one({"_id": oid, "member_count": {"$gt": 0}}, {"$inc": {"member_count": -1}})
            return web.json_response({"ok": True, "message": "You left the club."})
    
    
    async def _club_member_role(self, club_id: str, user_id: str):
        member = await self.bot.db.club_members.find_one({"club_id": str(club_id), "user_id": str(user_id)})
        return str(member.get("role", "member")).casefold() if member else None

    async def _club_is_manager(self, club_id: str, user_id: str) -> bool:
        return (await self._club_member_role(club_id, user_id)) in {"leader", "officer"}

    async def manage_club_member(self, request: web.Request) -> web.Response:
            user, _live_guild_id, _ = await self.require_guild_member(request)
            payload = await request.json()
            from bson import ObjectId
            try:
                oid = ObjectId(str(payload.get("club_id", "")))
            except Exception:
                raise web.HTTPBadRequest(text="Invalid club ID.")
            club = await self.bot.db.clubs.find_one({"_id": oid})
            if not club or str(club.get("guild_id")) not in {str(x) for x in user.guild_ids}:
                raise web.HTTPNotFound(text="Club not found.")
            actor_role = await self._club_member_role(str(oid), str(user.user_id))
            if actor_role not in {"leader", "officer"}:
                raise web.HTTPForbidden(text="Only the club leader or an Officer can manage members.")
            target = str(payload.get("user_id", "")).strip()
            if target == str(user.user_id):
                raise web.HTTPBadRequest(text="You cannot manage your own membership.")
            member = await self.bot.db.club_members.find_one({"club_id": str(oid), "user_id": target})
            if not member:
                raise web.HTTPNotFound(text="Club member not found.")
            target_role = str(member.get("role", "member")).casefold()
            action = str(payload.get("action", "")).casefold()
            if action in {"promote", "demote"}:
                if actor_role != "leader":
                    raise web.HTTPForbidden(text="Only the club leader can promote or demote Officers.")
                if target_role == "leader":
                    raise web.HTTPForbidden(text="The club leader cannot be changed through member management.")
                value = "officer" if action == "promote" else "member"
                await self.bot.db.club_members.update_one({"_id": member["_id"]}, {"$set": {"role": value}})
                return web.json_response({"ok": True, "message": "Member promoted to Officer." if value == "officer" else "Officer demoted to Member."})
            if action == "kick":
                # Officers may remove regular Members. Only the Leader may remove an Officer.
                if target_role == "leader":
                    raise web.HTTPForbidden(text="The club leader cannot be kicked.")
                if target_role == "officer" and actor_role != "leader":
                    raise web.HTTPForbidden(text="Officers cannot kick another Officer.")
                removed = await self.bot.db.club_members.delete_one({"_id": member["_id"]})
                if removed.deleted_count:
                    await self.bot.db.clubs.update_one({"_id": oid, "member_count": {"$gt": 0}}, {"$inc": {"member_count": -1}})
                return web.json_response({"ok": True, "message": "Member removed from the club."})
            raise web.HTTPBadRequest(text="Unsupported member action.")
    
    
    async def club_member_search(self, request: web.Request) -> web.Response:
        user, _live_guild_id, _ = await self.require_guild_member(request)
        guild_id = str(request.query.get("guild_id", "")).strip()
        query = str(request.query.get("q", "")).strip().casefold()
        if guild_id not in {str(x) for x in user.guild_ids}:
            raise web.HTTPForbidden(text="You are not a member of that server.")
        guild = self.bot.get_guild(int(guild_id))
        if guild is None:
            raise web.HTTPNotFound(text="Discord server is not available.")
        existing = {str(x.get("user_id")) for x in await self.bot.db.club_members.find({"guild_id": guild_id}, {"user_id": 1}).to_list(length=5000)}
        rows = []
        for member in list(getattr(guild, "members", []) or []):
            if str(member.id) == str(user.user_id) or str(member.id) in existing:
                continue
            label = f"{member.display_name} {member.name} {member.id}".casefold()
            if query and query not in label:
                continue
            rows.append({"user_id": str(member.id), "username": str(member.display_name or member.name or member.id)})
            if len(rows) >= 25:
                break
        return web.json_response({"members": rows})

    async def _club_notify_user(self, user_id: str, title: str, message: str) -> None:
        try:
            target = self.bot.get_user(int(user_id))
            if target is None:
                target = await self.bot.fetch_user(int(user_id))
            await target.send(f"**{title}**\n{message}")
        except Exception:
            log.exception("Unable to deliver club membership notification to %s", user_id)

    async def club_invitations(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        now = datetime.now(timezone.utc).isoformat()
        await self.bot.db.club_invitations.update_many(
            {"invitee_id": str(user.user_id), "status": "pending", "expires_at": {"$lte": now}},
            {"$set": {"status": "expired", "updated_at": now}},
        )
        rows = await self.bot.db.club_invitations.find(
            {"invitee_id": str(user.user_id), "status": "pending"},
        ).sort("created_at", -1).to_list(length=50)
        return web.json_response({"invitations": [{"id": str(row.pop("_id")), **row} for row in rows]})

    async def club_join_requests(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        now = datetime.now(timezone.utc).isoformat()
        memberships = await self.bot.db.club_members.find({"user_id": str(user.user_id), "role": {"$in": ["leader", "officer"]}}, {"club_id": 1}).to_list(length=100)
        club_ids = [str(x.get("club_id")) for x in memberships if x.get("club_id")]
        clubs = await self.bot.db.clubs.find({"_id": {"$in": [ObjectId(x) for x in club_ids if ObjectId.is_valid(x)]}}).to_list(length=100)
        club_ids = [str(x["_id"]) for x in clubs]
        await self.bot.db.club_join_requests.update_many(
            {"club_id": {"$in": club_ids}, "status": "pending", "expires_at": {"$lte": now}},
            {"$set": {"status": "expired", "updated_at": now}},
        )
        rows = await self.bot.db.club_join_requests.find(
            {"club_id": {"$in": club_ids}, "status": "pending"},
        ).sort("created_at", -1).to_list(length=100)
        names = {str(x["_id"]): str(x.get("name") or "") for x in clubs}
        return web.json_response({"requests": [{"id": str(row.pop("_id")), **row, "club_name": names.get(str(row.get("club_id", "")), "Club")} for row in rows]})

    async def create_club_invite(self, request: web.Request) -> web.Response:
        user, _live_guild_id, _ = await self.require_guild_member(request)
        payload = await request.json()
        from bson import ObjectId
        try:
            oid = ObjectId(str(payload.get("club_id", "")))
        except Exception as exc:
            raise web.HTTPBadRequest(text="Invalid club ID.") from exc
        club = await self.bot.db.clubs.find_one({"_id": oid})
        if not club or str(club.get("guild_id")) not in {str(x) for x in user.guild_ids}:
            raise web.HTTPNotFound(text="Club not found.")
        actor_role = await self._club_member_role(str(oid), str(user.user_id))
        if actor_role not in {"leader", "officer"}:
            raise web.HTTPForbidden(text="Only the club leader or an Officer can invite drivers.")
        target = str(payload.get("user_id", "")).strip()
        if not target or target == str(user.user_id) or not target.isdigit():
            raise web.HTTPBadRequest(text="Select a valid Discord member.")
        if await self.bot.db.club_members.find_one({"guild_id": str(club["guild_id"]), "user_id": target}):
            raise web.HTTPConflict(text="That driver is already in a club in this server.")
        if await self.bot.db.club_join_requests.find_one({"club_id": str(oid), "user_id": target, "status": "pending"}):
            raise web.HTTPConflict(text="That driver already has a pending join request for this club.")
        if int(club.get("member_count", 0) or 0) >= 20:
            raise web.HTTPConflict(text="That club is full.")
        guild = self.bot.get_guild(int(club["guild_id"]))
        if guild is None:
            raise web.HTTPNotFound(text="Discord server is not available.")
        member = guild.get_member(int(target))
        if member is None:
            try:
                member = await guild.fetch_member(int(target))
            except Exception as exc:
                raise web.HTTPNotFound(text="That Discord member could not be found in this server.") from exc
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=7)
        doc = {
            "guild_id": str(club["guild_id"]),
            "club_id": str(oid),
            "club_name": str(club.get("name") or "Club"),
            "inviter_id": str(user.user_id),
            "invitee_id": target,
            "invitee_name": str(member.display_name or member.name or target),
            "status": "pending",
            "created_at": now.isoformat(),
            "expires_at": expires.isoformat(),
            "updated_at": now.isoformat(),
        }
        try:
            await self.bot.db.club_invitations.insert_one(doc)
        except Exception as exc:
            if exc.__class__.__name__ == "DuplicateKeyError":
                raise web.HTTPConflict(text="That driver already has a pending invitation.")
            raise
        await self._club_notify_user(target, "RSL Club Invitation", f"You have been invited to join **{club.get('name', 'this club')}**. Open the Clubs page to accept or decline the invitation.")
        return web.json_response({"ok": True, "message": f"Invitation sent to {member.display_name or member.name}."})

    async def club_invitation_action(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        payload = await request.json()
        action = str(payload.get("action", "")).casefold()
        if action not in {"accept", "decline"}:
            raise web.HTTPBadRequest(text="Unsupported invitation action.")
        invitation_id = str(payload.get("invitation_id", "")).strip()
        invite = await self.bot.db.club_invitations.find_one({"_id": ObjectId(invitation_id), "invitee_id": str(user.user_id), "status": "pending"}) if ObjectId.is_valid(invitation_id) else None
        if not invite:
            raise web.HTTPNotFound(text="Invitation not found or already handled.")
        now = datetime.now(timezone.utc)
        if str(invite.get("expires_at", "")) <= now.isoformat():
            await self.bot.db.club_invitations.update_one({"_id": invite["_id"], "status": "pending"}, {"$set": {"status": "expired", "updated_at": now.isoformat()}})
            raise web.HTTPConflict(text="That invitation has expired.")
        if action == "decline":
            await self.bot.db.club_invitations.update_one({"_id": invite["_id"], "status": "pending"}, {"$set": {"status": "declined", "updated_at": now.isoformat()}})
            return web.json_response({"ok": True, "message": "Club invitation declined."})
        club = await self.bot.db.clubs.find_one({"_id": ObjectId(str(invite["club_id"]))})
        if not club:
            raise web.HTTPNotFound(text="Club no longer exists.")
        if await self.bot.db.club_members.find_one({"guild_id": str(club["guild_id"]), "user_id": str(user.user_id)}):
            raise web.HTTPConflict(text="You are already in a club in this server.")
        reservation = await self.bot.db.clubs.update_one(
            {"_id": club["_id"], "$or": [{"member_count": {"$lt": 20}}, {"member_count": {"$exists": False}}]},
            {"$inc": {"member_count": 1}},
        )
        if not reservation.modified_count:
            raise web.HTTPConflict(text="That club is full.")
        try:
            await self.bot.db.club_members.insert_one({
                "club_id": str(club["_id"]), "guild_id": str(club["guild_id"]),
                "user_id": str(user.user_id), "username": str(user.global_name or user.username or user.user_id),
                "role": "member", "joined_at": now.isoformat(),
            })
        except Exception as exc:
            await self.bot.db.clubs.update_one({"_id": club["_id"], "member_count": {"$gt": 0}}, {"$inc": {"member_count": -1}})
            if exc.__class__.__name__ == "DuplicateKeyError":
                raise web.HTTPConflict(text="You are already in a club in this server.")
            raise
        await self.bot.db.club_invitations.update_one({"_id": invite["_id"], "status": "pending"}, {"$set": {"status": "accepted", "updated_at": now.isoformat()}})
        await self.bot.db.club_join_requests.update_many({"club_id": str(club["_id"]), "user_id": str(user.user_id), "status": "pending"}, {"$set": {"status": "withdrawn", "updated_at": now.isoformat()}})
        await self._club_notify_user(str(club["leader_id"]), "RSL Club Invitation Accepted", f"{user.global_name or user.username} accepted the invitation to join **{club.get('name', 'your club')}**.")
        return web.json_response({"ok": True, "message": f"You joined {club.get('name', 'the club')}."})

    async def create_club_join_request(self, request: web.Request) -> web.Response:
        user, _live_guild_id, _ = await self.require_guild_member(request)
        payload = await request.json()
        from bson import ObjectId
        try:
            oid = ObjectId(str(payload.get("club_id", "")))
        except Exception as exc:
            raise web.HTTPBadRequest(text="Invalid club ID.") from exc
        club = await self.bot.db.clubs.find_one({"_id": oid})
        if not club or str(club.get("guild_id")) not in {str(x) for x in user.guild_ids}:
            raise web.HTTPNotFound(text="Club not found.")
        if await self.bot.db.club_members.find_one({"guild_id": str(club["guild_id"]), "user_id": str(user.user_id)}):
            raise web.HTTPConflict(text="You are already in a club in this server.")
        if int(club.get("member_count", 0) or 0) >= 20:
            raise web.HTTPConflict(text="That club is full.")
        if await self.bot.db.club_invitations.find_one({"club_id": str(oid), "invitee_id": str(user.user_id), "status": "pending"}):
            raise web.HTTPConflict(text="You already have a pending invitation from this club.")
        now = datetime.now(timezone.utc)
        doc = {
            "guild_id": str(club["guild_id"]), "club_id": str(oid), "club_name": str(club.get("name") or "Club"),
            "user_id": str(user.user_id), "username": str(user.global_name or user.username or user.user_id),
            "message": str(payload.get("message", "")).strip()[:500], "status": "pending",
            "created_at": now.isoformat(), "expires_at": (now + timedelta(days=7)).isoformat(), "updated_at": now.isoformat(),
        }
        try:
            await self.bot.db.club_join_requests.insert_one(doc)
        except Exception as exc:
            if exc.__class__.__name__ == "DuplicateKeyError":
                raise web.HTTPConflict(text="You already have a pending request for this club.")
            raise
        await self._club_notify_user(str(club["leader_id"]), "RSL Club Join Request", f"{user.global_name or user.username} requested to join **{club.get('name', 'your club')}**. Open Clubs to accept or decline.")
        return web.json_response({"ok": True, "message": "Join request sent to the club leader."})

    async def club_join_request_action(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        payload = await request.json()
        action = str(payload.get("action", "")).casefold()
        if action not in {"accept", "decline"}:
            raise web.HTTPBadRequest(text="Unsupported join request action.")
        request_id = str(payload.get("request_id", "")).strip()
        if not ObjectId.is_valid(request_id):
            raise web.HTTPBadRequest(text="Invalid request ID.")
        join_request = await self.bot.db.club_join_requests.find_one({"_id": ObjectId(request_id), "status": "pending"})
        if not join_request:
            raise web.HTTPNotFound(text="Join request not found or already handled.")
        club = await self.bot.db.clubs.find_one({"_id": ObjectId(str(join_request["club_id"]))})
        if not club:
            raise web.HTTPNotFound(text="Club not found.")
        actor_role = await self._club_member_role(str(join_request["club_id"]), str(user.user_id))
        if actor_role not in {"leader", "officer"}:
            raise web.HTTPForbidden(text="Only the club leader or an Officer can manage join requests.")
        now = datetime.now(timezone.utc)
        if str(join_request.get("expires_at", "")) <= now.isoformat():
            await self.bot.db.club_join_requests.update_one({"_id": join_request["_id"], "status": "pending"}, {"$set": {"status": "expired", "updated_at": now.isoformat()}})
            raise web.HTTPConflict(text="That join request has expired.")
        if action == "decline":
            await self.bot.db.club_join_requests.update_one({"_id": join_request["_id"], "status": "pending"}, {"$set": {"status": "declined", "updated_at": now.isoformat()}})
            await self._club_notify_user(str(join_request["user_id"]), "RSL Club Join Request", f"Your request to join **{club.get('name', 'the club')}** was declined.")
            return web.json_response({"ok": True, "message": "Join request declined."})
        if await self.bot.db.club_members.find_one({"guild_id": str(club["guild_id"]), "user_id": str(join_request["user_id"])}):
            raise web.HTTPConflict(text="That driver is already in a club in this server.")
        reservation = await self.bot.db.clubs.update_one(
            {"_id": club["_id"], "$or": [{"member_count": {"$lt": 20}}, {"member_count": {"$exists": False}}]},
            {"$inc": {"member_count": 1}},
        )
        if not reservation.modified_count:
            raise web.HTTPConflict(text="That club is full.")
        try:
            await self.bot.db.club_members.insert_one({
                "club_id": str(club["_id"]), "guild_id": str(club["guild_id"]),
                "user_id": str(join_request["user_id"]), "username": str(join_request.get("username") or join_request["user_id"]),
                "role": "member", "joined_at": now.isoformat(),
            })
        except Exception as exc:
            await self.bot.db.clubs.update_one({"_id": club["_id"], "member_count": {"$gt": 0}}, {"$inc": {"member_count": -1}})
            if exc.__class__.__name__ == "DuplicateKeyError":
                raise web.HTTPConflict(text="That driver is already in a club in this server.")
            raise
        await self.bot.db.club_join_requests.update_one({"_id": join_request["_id"], "status": "pending"}, {"$set": {"status": "accepted", "updated_at": now.isoformat()}})
        await self.bot.db.club_invitations.update_many({"club_id": str(club["_id"]), "invitee_id": str(join_request["user_id"]), "status": "pending"}, {"$set": {"status": "withdrawn", "updated_at": now.isoformat()}})
        await self._club_notify_user(str(join_request["user_id"]), "RSL Club Join Request", f"Your request to join **{club.get('name', 'the club')}** was accepted.")
        return web.json_response({"ok": True, "message": f"{join_request.get('username', 'Driver')} joined the club."})

    async def club_action_status(self, request: web.Request) -> web.Response:
        user = await self.require_user(request)
        now = datetime.now(timezone.utc).isoformat()
        await self.bot.db.club_invitations.update_many({"invitee_id": str(user.user_id), "status": "pending", "expires_at": {"$lte": now}}, {"$set": {"status": "expired", "updated_at": now}})
        memberships = await self.bot.db.club_members.find({"user_id": str(user.user_id), "role": {"$in": ["leader", "officer"]}}, {"club_id": 1}).to_list(length=100)
        club_ids = [str(x.get("club_id")) for x in memberships if x.get("club_id")]
        clubs = await self.bot.db.clubs.find({"_id": {"$in": [ObjectId(x) for x in club_ids if ObjectId.is_valid(x)]}}).to_list(length=100)
        club_ids = [str(x["_id"]) for x in clubs]
        await self.bot.db.club_join_requests.update_many({"club_id": {"$in": club_ids}, "status": "pending", "expires_at": {"$lte": now}}, {"$set": {"status": "expired", "updated_at": now}})
        invitations = await self.bot.db.club_invitations.find({"invitee_id": str(user.user_id), "status": "pending"}, {"_id": 1, "club_id": 1, "club_name": 1, "inviter_id": 1, "created_at": 1, "expires_at": 1}).sort("created_at", -1).to_list(length=50)
        requests = await self.bot.db.club_join_requests.find({"club_id": {"$in": club_ids}, "status": "pending"}, {"_id": 1, "club_id": 1, "club_name": 1, "user_id": 1, "username": 1, "message": 1, "created_at": 1, "expires_at": 1}).sort("created_at", -1).to_list(length=100)
        return web.json_response({
            "invitations": [{"id": str(x["_id"]), **{k: v for k, v in x.items() if k != "_id"}} for x in invitations],
            "requests": [{"id": str(x["_id"]), **{k: v for k, v in x.items() if k != "_id"}} for x in requests],
        })

    async def club_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("club.html", request)


    async def clubs_page(self, request: web.Request) -> web.StreamResponse:
            await self.require_user(request)
            return await self._page_response("clubs.html", request)
