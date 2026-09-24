import discord
from discord.ext import commands
from discord import app_commands
from ..core.core import bot

MAX_MATCH_BUTTONS = 5

def _matches(tournament):
    bracket = tournament.get("bracket") or {}
    return [m for group in (bracket.get("rounds") or bracket.get("winners") or []) for m in group.get("matches", [])]

async def _entrant_name(tournament, entrant_id):
    sid = str(entrant_id)
    if int(tournament.get("team_size", 1)) > 1:
        from bson import ObjectId
        club = await bot.db.clubs.find_one({"_id": ObjectId(sid)}) if ObjectId.is_valid(sid) else None
        return str(club.get("name", sid)) if club else sid
    member = None
    try:
        member = bot.get_user(int(sid)) or await bot.fetch_user(int(sid))
    except Exception:
        pass
    return str(getattr(member, "display_name", None) or getattr(member, "name", None) or sid)

async def _claim_action(tournament_id, match_id, action):
    """Claim a short-lived match action so Discord and web actions cannot double-process it."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    doc = {
        "tournament_id": str(tournament_id),
        "match_id": str(match_id),
        "action": str(action),
        "claimed_at": now,
        "expires_at": now + timedelta(seconds=60),
    }
    try:
        await bot.db.tournament_action_locks.insert_one(doc)
        return True
    except Exception as exc:
        if exc.__class__.__name__ != "DuplicateKeyError":
            raise
        replaced = await bot.db.tournament_action_locks.find_one_and_replace(
            {"tournament_id": str(tournament_id), "match_id": str(match_id), "expires_at": {"$lt": now}},
            doc,
        )
        return replaced is not None


async def _release_action(tournament_id, match_id):
    await bot.db.tournament_action_locks.delete_one(
        {"tournament_id": str(tournament_id), "match_id": str(match_id)}
    )


async def _is_participant(tournament, match, user_id):
    uid = str(user_id)
    slots = [str(x) for x in (match.get("player_slots") or []) if x]
    if int(tournament.get("team_size", 1)) > 1:
        return bool(await bot.db.tournament_club_registrations.find_one(
            {"tournament_id": str(tournament["_id"]), "club_id": {"$in": slots}, "lineup": uid}
        ))
    return uid in slots

async def _is_tournament_staff(interaction):
    """Return whether the interacting member has tournament-specific staff access."""
    if not interaction.guild:
        return False
    member = interaction.guild.get_member(interaction.user.id)
    if member is None:
        try:
            member = await interaction.guild.fetch_member(interaction.user.id)
        except Exception:
            return False
    permissions = getattr(member, "guild_permissions", None)
    if permissions and (permissions.administrator or permissions.manage_guild):
        return True
    settings = await bot.db.settings.find_one({"_id": str(interaction.guild.id)}) or {}
    role_id = settings.get("tournament_admin_role_id")
    if role_id:
        try:
            role = interaction.guild.get_role(int(role_id))
            if role and any(r.id == role.id for r in getattr(member, "roles", [])):
                return True
        except (TypeError, ValueError):
            pass
    return False

class TournamentResultModal(discord.ui.Modal, title="Submit Match Result"):
    proof = discord.ui.TextInput(label="Proof URL (optional)", required=False, max_length=500, placeholder="https://...")
    notes = discord.ui.TextInput(label="Notes (optional)", required=False, max_length=500, style=discord.TextStyle.paragraph)

    def __init__(self, tournament_id, match_id, winner_id):
        super().__init__()
        self.tournament_id = str(tournament_id)
        self.match_id = str(match_id)
        self.winner_id = str(winner_id)

    async def on_submit(self, interaction):
        from bson import ObjectId
        tournament = await bot.db.tournaments.find_one({"_id": ObjectId(self.tournament_id)}) if ObjectId.is_valid(self.tournament_id) else None
        if not tournament or tournament.get("status") != "live":
            await interaction.response.send_message("❌ This tournament is not live.", ephemeral=True)
            return
        bracket = tournament.get("bracket") or {}
        match = next((m for m in _matches(tournament) if str(m.get("id")) == self.match_id), None)
        if not match:
            await interaction.response.send_message("❌ Match not found.", ephemeral=True)
            return
        if not await _is_participant(tournament, match, interaction.user.id) and not await _is_tournament_staff(interaction):
            await interaction.response.send_message("❌ Only a participant in this match can submit the result.", ephemeral=True)
            return
        if match.get("result_status") == "pending":
            await interaction.response.send_message("❌ This match already has a result waiting for staff verification.", ephemeral=True)
            return
        if match.get("status") == "completed":
            await interaction.response.send_message("❌ This match is already completed.", ephemeral=True)
            return
        if not await _claim_action(self.tournament_id, self.match_id, "submit"):
            await interaction.response.send_message("❌ Another result submission is already being processed for this match.", ephemeral=True)
            return
        proof = str(self.proof.value).strip()
        if proof and not proof.lower().startswith(("http://", "https://")):
            await interaction.response.send_message("❌ Proof must be a valid URL.", ephemeral=True)
            return
        try:
            match.update({"result_status":"pending","submitted_by":str(interaction.user.id),"submitted_at":discord.utils.utcnow().isoformat(),"winner_id":self.winner_id,"proof_url":proof,"result_notes":str(self.notes.value).strip()})
            await bot.db.tournaments.update_one({"_id":tournament["_id"]},{"$set":{"bracket":bracket,"updated_at":discord.utils.utcnow().isoformat()}})
        finally:
            await _release_action(self.tournament_id, self.match_id)
        cfg=await bot.db.settings.find_one({"_id":str(tournament.get("guild_id"))}) or {}
        channel=bot.get_channel(int(cfg["match_results_channel_id"])) if cfg.get("match_results_channel_id") else None
        if channel:
            await channel.send("🏁 **Tournament Result Pending Verification**\n**"+str(tournament.get("name","Tournament"))+"** • "+self.match_id+"\nWinner: <@"+self.winner_id+">\nSubmitted by: <@"+str(interaction.user.id)+">")
        await interaction.response.send_message("📥 Result submitted. Staff verification is required before the bracket advances.", ephemeral=True)

class MatchResultView(discord.ui.View):
    def __init__(self, tournament_id, match):
        super().__init__(timeout=900)
        self.tournament_id=str(tournament_id)
        self.match_id=str(match.get("id"))
        self.slots=[str(x) for x in (match.get("player_slots") or []) if x]
        self._add_buttons()

    def _add_buttons(self):
        for index, entrant in enumerate(self.slots[:2]):
            button=discord.ui.Button(label=f"Winner: {entrant[:70]}", style=discord.ButtonStyle.primary, custom_id=f"alu_tourney_win_{self.match_id}_{index}")
            async def callback(interaction, entrant=entrant):
                from bson import ObjectId
                tournament=await bot.db.tournaments.find_one({"_id":ObjectId(self.tournament_id)}) if ObjectId.is_valid(self.tournament_id) else None
                match=next((m for m in _matches(tournament or {}) if str(m.get("id"))==self.match_id),None)
                if not tournament or not match:
                    await interaction.response.send_message("❌ Match not found.",ephemeral=True); return
                if not await _is_participant(tournament,match,interaction.user.id) and not await _is_tournament_staff(interaction):
                    await interaction.response.send_message("❌ You are not a participant in this match.",ephemeral=True); return
                await interaction.response.send_modal(TournamentResultModal(self.tournament_id,self.match_id,entrant))
            button.callback=callback
            self.add_item(button)

class TournamentSelect(discord.ui.Select):
    def __init__(self, tournaments):
        options=[discord.SelectOption(label=str(t.get("name","Tournament"))[:100],value=str(t["_id"]),description=str(t.get("status","draft")).replace("_"," ")[:100]) for t in tournaments[:25]]
        super().__init__(placeholder="Choose a tournament…",min_values=1,max_values=1,options=options)

    async def callback(self, interaction):
        await interaction.response.edit_message(embed=await build_tournament_embed(self.values[0]),view=await build_tournament_view(self.values[0],interaction.user))

class TournamentPickerView(discord.ui.View):
    def __init__(self,tournaments):
        super().__init__(timeout=900)
        self.add_item(TournamentSelect(tournaments))

class TournamentDashboardView(discord.ui.View):
    def __init__(self,tournament,user):
        super().__init__(timeout=900)
        self.tournament_id=str(tournament["_id"])
        for match in _matches(tournament):
            if match.get("status")=="ready" and len([x for x in (match.get("player_slots") or []) if x])==2:
                self.add_item(discord.ui.Button(label=f"Match {match.get('id')}",style=discord.ButtonStyle.secondary,disabled=True))
        self.add_item(discord.ui.Button(label="Refresh",style=discord.ButtonStyle.secondary,custom_id="alu_tourney_refresh"))

async def build_tournament_embed(tournament_id):
    from bson import ObjectId
    t=await bot.db.tournaments.find_one({"_id":ObjectId(str(tournament_id))}) if ObjectId.is_valid(str(tournament_id)) else None
    if not t:
        return discord.Embed(title="🏆 Tournament",description="Tournament not found.")
    embed=discord.Embed(title=f"🏆 {t.get('name','Tournament')}",color=0x7C4DFF)
    embed.description=str(t.get("description","Tournament Center"))
    embed.add_field(name="Status",value=str(t.get("status","draft")).replace("_"," ").title(),inline=True)
    embed.add_field(name="Format",value=str(t.get("format","")).replace("_"," ").title(),inline=True)
    if t.get("champion_id"):
        embed.add_field(name="🏆 Champion",value=f"<@{t['champion_id']}>",inline=False)
    matches=_matches(t)
    live=[m for m in matches if m.get("status") in {"ready","pending"}]
    lines=[]
    for m in live[:8]:
        names=[await _entrant_name(t,x) for x in (m.get("player_slots") or [])]
        if len(names)==2:
            state="⏳ Pending Review" if m.get("result_status")=="pending" else "🏁 Ready"
            lines.append(f"**{m.get('id')}** — {names[0]} vs {names[1]} • {state}")
    embed.add_field(name="🎮 Match Center",value="\n".join(lines) or "No active matches.",inline=False)
    return embed

async def verify_match_on_discord(tournament_id, match_id, action, user_id):
    from bson import ObjectId
    t=await bot.db.tournaments.find_one({"_id":ObjectId(str(tournament_id))}) if ObjectId.is_valid(str(tournament_id)) else None
    if not t:
        return False, "Tournament not found."
    bracket=t.get("bracket") or {}
    groups=bracket.get("rounds") or bracket.get("winners") or []
    match=next((m for group in groups for m in group.get("matches",[]) if str(m.get("id"))==str(match_id)),None)
    if not match:
        return False, "Match not found."
    if t.get("status") != "live":
        return False, "Tournament is not live."
    if match.get("result_status")!="pending":
        return False, "This match has no pending result."
    if not await _claim_action(tournament_id, str(match_id), "verify"):
        return False, "Another staff action is already processing this match."
    try:
        if action=="reject":
            for key in ("result_status","winner_id","submitted_by","submitted_at","proof_url","result_notes"):
                match.pop(key,None)
            match["status"]="ready"
            message="Result rejected. The match is ready for another submission."
        else:
            winner=str(match.get("winner_id",""))
            if winner not in [str(x) for x in (match.get("player_slots") or []) if x]:
                return False, "Pending result has no valid winner."
            match.update({"result_status":"verified","verified_by":str(user_id),"verified_at":discord.utils.utcnow().isoformat(),"status":"completed"})
            target=match.get("winner_to")
            if target:
                target_match = next(
                    (nxt for group in groups for nxt in group.get("matches", []) if str(nxt.get("id")) == str(target)),
                    None,
                )
                if target_match is None:
                    return False, "Bracket advancement target is invalid."
                slots = list(target_match.get("player_slots") or [None, None])
                while len(slots) < 2:
                    slots.append(None)
                if winner in [str(x) for x in slots if x is not None]:
                    return False, "Winner has already advanced to the target match."
                if all(slots):
                    return False, "Bracket advancement target is already occupied."
                empty_index = slots.index(None)
                slots[empty_index] = winner
                target_match["player_slots"] = slots
                if all(slots):
                    target_match["status"] = "ready"
            else:
                if str(match.get("bracket","winners"))=="winners" and (match.get("round") or 0)==len(groups):
                    t["status"]="completed"
                    t["champion_id"]=winner
                    t["completed_at"]=discord.utils.utcnow().isoformat()
            message="Result approved and winner advanced."
        await bot.db.tournaments.update_one(
            {"_id":t["_id"]},
            {"$set":{"bracket":bracket,"status":t.get("status","live"),"champion_id":t.get("champion_id"),"updated_at":discord.utils.utcnow().isoformat()}}
        )
        return True, message
    finally:
        await _release_action(tournament_id, str(match_id))


async def build_tournament_view(tournament_id,user):
    from bson import ObjectId
    t=await bot.db.tournaments.find_one({"_id":ObjectId(str(tournament_id))}) if ObjectId.is_valid(str(tournament_id)) else None
    view=discord.ui.View(timeout=900)
    if not t: return view
    ready=[m for m in _matches(t) if m.get("status")=="ready" and len([x for x in (m.get("player_slots") or []) if x])==2]
    for m in ready[:MAX_MATCH_BUTTONS]:
        names=[await _entrant_name(t,x) for x in m["player_slots"]]
        b=discord.ui.Button(label=f"{names[0][:30]} vs {names[1][:30]}",style=discord.ButtonStyle.primary)
        async def cb(interaction,match=m):
            if not await _is_participant(t,match,interaction.user.id) and not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ You are not a participant in this match.",ephemeral=True); return
            await interaction.response.send_message("Choose the winner:",view=MatchResultView(tournament_id,match),ephemeral=True)
        b.callback=cb
        view.add_item(b)
    if await _is_tournament_staff(type("StaffContext", (), {"guild": getattr(user, "guild", None), "user": user})()):
        pending=[m for m in _matches(t) if m.get("result_status")=="pending"]
        for m in pending[:MAX_MATCH_BUTTONS]:
            b=discord.ui.Button(label=f"Review {m.get('id')}",style=discord.ButtonStyle.success)
            async def review_cb(interaction,match=m):
                if not await _is_tournament_staff(interaction):
                    await interaction.response.send_message("❌ Tournament staff access required.",ephemeral=True); return
                ok,msg=await verify_match_on_discord(tournament_id,match.get("id"),"approve",interaction.user.id)
                await interaction.response.send_message(("✅ " if ok else "❌ ")+msg,ephemeral=True)
            b.callback=review_cb
            view.add_item(b)
    return view

class TournamentCog(commands.Cog):
    """Tournament backend/UI helpers.

    Tournament access is dashboard-driven; the cog intentionally does not expose
    a standalone /tournament slash command so the public command surface stays
    limited to /dashboard and /staff.
    """


async def setup(bot):
    await bot.add_cog(TournamentCog(bot))
