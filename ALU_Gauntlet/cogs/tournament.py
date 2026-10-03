            await interaction.response.send_message(
                await localize_text(bot, interaction.user.id, "❌ Proof must be a valid URL.", interaction.locale),
                ephemeral=True
            )
            return
        try:
            match.update({"result_status":"pending","submitted_by":str(interaction.user.id),"submitted_at":discord.utils.utcnow().isoformat(),"winner_id":self.winner_id,"proof_url":proof,"result_notes":str(self.notes.value).strip()})
            await bot.db.tournaments.update_one({"_id":tournament["_id"],"guild_id":str(tournament.get("guild_id") or "")},{"$set":{"bracket":bracket,"updated_at":discord.utils.utcnow().isoformat()}})
        finally:
            await _release_action(self.tournament_id, self.match_id, "submit", lock_token)
        if result_mode == "admin_only":
            ok, message = await verify_match_on_discord(
                self.tournament_id,