"""RSL web clubs route family."""
from .._web_context import *

class ClubsRoutesMixin:
    async def clubs_page(self, request: web.Request) -> web.StreamResponse:
            await self.require_user(request)
            return await self._page_response("clubs.html", request)
    
    
    async def club_page(self, request: web.Request) -> web.StreamResponse:
            await self.require_user(request)
            return await self._page_response("club.html", request)
    
    
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
    
    
    async def manage_club_member(self, request: web.Request) -> web.Response:
            user, _live_guild_id, _ = await self.require_guild_member(request)
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
    
    
    async def clubs_page(self, request: web.Request) -> web.StreamResponse:
            await self.require_user(request)
            return await self._page_response("clubs.html", request)
