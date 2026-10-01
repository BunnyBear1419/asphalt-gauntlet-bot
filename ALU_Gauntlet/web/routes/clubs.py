"""RSL web clubs route family."""
from .._web_context import *

class ClubsRoutesMixin:
    async def clubs_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("clubs.html", request)

    async def club_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("club.html", request)

    async def club_page(self, request: web.Request) -> web.StreamResponse:
        await self.require_user(request)
        return await self._page_response("club.html", request)

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
