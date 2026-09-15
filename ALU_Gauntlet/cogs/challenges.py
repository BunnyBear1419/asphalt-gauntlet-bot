from discord.ext import commands
from discord import app_commands
from ..core.core import *

class ChallengesCog(commands.Cog):

    @app_commands.command(name='challenge', description='Fetches active 5-course defense ghosts for matchmaking (5 per day).')
    @app_commands.checks.cooldown(1, 45.0, key=lambda i: (i.guild_id, i.user.id))
    async def challenge_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        await interaction.response.defer()
        guild_id, user_id = (str(interaction.guild_id), str(interaction.user.id))
        user_profile = await bot.db.drivers.find_one({'_id': f'{guild_id}_{user_id}'})
        if not user_profile:
            await interaction.followup.send('❌ Open `/register` first.')
            return
        state = await bot.db.season_state.find_one({'_id': f'guild_{guild_id}'})
        season_number = int(state.get('season_number', 1)) if state else 1
        if not user_profile.get('season_registered') or int(user_profile.get('season_number', 0)) != season_number:
            await interaction.followup.send(f'🔄 You must re-register your Garage for Season {season_number} before challenging.')
            return
        if not has_5_course_defense(user_profile):
            await interaction.followup.send('❌ You need a locked 5-course defense before challenging. Open `/gauntlet` → **Defense** to finish your defense setup.')
            return
        today = await get_guild_local_date(guild_id)
        challenge_date = user_profile.get('challenge_date')
        challenge_count = user_profile.get('challenge_count', 0)
        if challenge_date == today and challenge_count >= 5:
            await interaction.followup.send("⏳ **Daily Limit Reached:** You've used all 5 of your daily challenges. Come back tomorrow!", ephemeral=True)
            return
        user_pi = user_profile.get('garage_pi', 15500)
        pi_query = division_mongo_query(get_division_for_pi(user_pi))
        cursor = bot.db.drivers.find({'guild_id': guild_id, 'user_id': {'$ne': user_id}, 'garage_pi': pi_query, 'defense_locked.courses.4': {'$exists': True}}).limit(10)
        candidates = await cursor.to_list(length=10)
        if not candidates:
            await interaction.followup.send('⚠️ No matching opponents are qualified with active 5-course defenses yet inside your performance tier bracket.')
            return
        remaining = 5 - (challenge_count + 1 if challenge_date == today else 1)
        selected_opponents = random.sample(candidates, min(len(candidates), 3))
        defender_data_map = {opp['user_id']: {'courses': opp['defense_locked']['courses'], 'proof_url': opp['defense_locked'].get('proof_url'), 'car_rank_total': opp['defense_locked'].get('car_rank_total', get_car_rank_total(opp['defense_locked']['courses']))} for opp in selected_opponents}
        options_list = [discord.SelectOption(label=f"{opp.get('game_id', 'Driver')} | {opp.get('elo', 1000)} ELO", description=f"{get_division_for_pi(int(opp.get('garage_pi', 0)))['name'][:55]} • Car Rating {opp.get('defense_locked', {}).get('car_rank_total', get_car_rank_total(opp.get('defense_locked', {}).get('courses', []))):,} • 5 courses", value=opp['user_id'], emoji='🏎️') for opp in selected_opponents]
        match_embed = discord.Embed(title='⚡ AUTOMATED MATCHMAKING MATRIX ONLINE', description=f'A competitive matchmaking target window has stabilized. Choose your opponent from the terminal menu dropdown below!\n\n⚠️ *Each opponent has a locked 5-course defense. You will see their exact routes, cars, and times, then race those same 5 routes with your own attack cars. Win 3 out of 5 races to win the match.*\n\n📊 **Daily challenges remaining:** `{remaining}/5`', color=ASPHALT_THEME_COLOR)
        match_embed.set_image(url=ASPHALT_MEDIA['banner_match'])
        await interaction.followup.send(embed=match_embed, view=ChallengeView(options_list, defender_data_map, guild_id, user_id))

    @app_commands.command(name='submitmatch_direct', description='[Advanced] Submit an active challenge with all five results and proof.')
    @app_commands.describe(lap1='Course 1 lap time', lap2='Course 2 lap time', lap3='Course 3 lap time', lap4='Course 4 lap time', lap5='Course 5 lap time', car1='Course 1 attack car', car2='Course 2 attack car', car3='Course 3 attack car', car4='Course 4 attack car', car5='Course 5 attack car', rank1='Course 1 car performance rating', rank2='Course 2 car performance rating', rank3='Course 3 car performance rating', rank4='Course 4 car performance rating', rank5='Course 5 car performance rating', proof='Discord race-proof image URL')
    @app_commands.autocomplete(car1=car_autocomplete, car2=car_autocomplete, car3=car_autocomplete, car4=car_autocomplete, car5=car_autocomplete)
    async def submitmatch_cmd(self, interaction: discord.Interaction, lap1: str, lap2: str, lap3: str, lap4: str, lap5: str, car1: str, car2: str, car3: str, car4: str, car5: str, rank1: int, rank2: int, rank3: int, rank4: int, rank5: int, proof: str):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        guild_id, user_id = (str(interaction.guild_id), str(interaction.user.id))
        active = await claim_active_challenge(guild_id, user_id)
        if not active:
            await interaction.followup.send('❌ You have no active challenge, or it is already being submitted. Open `/gauntlet` → **Challenges** → **Find Challenge** first.', ephemeral=True)
            return
        laps = [lap1, lap2, lap3, lap4, lap5]
        cars = [car1, car2, car3, car4, car5]
        ranks = [rank1, rank2, rank3, rank4, rank5]
        lookup = {c.casefold(): c for c in ALU_CARS}
        canonical = []
        for i, c in enumerate(cars):
            if c.casefold() not in lookup:
                await release_active_challenge(active['_id'])
                await interaction.followup.send(f'❌ Car {i + 1} is not in the approved ALU roster.', ephemeral=True)
                return
            canonical.append(lookup[c.casefold()])
        if len({c.casefold() for c in canonical}) != 5:
            await release_active_challenge(active['_id'])
            await interaction.followup.send('❌ All 5 attack cars must be different.', ephemeral=True)
            return
        if any((int(r) <= 0 for r in ranks)):
            await release_active_challenge(active['_id'])
            await interaction.followup.send('❌ All 5 car performance ratings must be greater than 0.', ephemeral=True)
            return
        challenger_times = []
        for i, l in enumerate(laps):
            ms = parse_lap_time(l.strip())
            if ms <= 0:
                await release_active_challenge(active['_id'])
                await interaction.followup.send(f'❌ Lap {i + 1} is invalid. Use a positive `MM:SS.MS` time.', ephemeral=True)
                return
            challenger_times.append({'lap_time_str': l.strip(), 'ms': ms, 'car': canonical[i], 'car_rank': int(ranks[i])})
        proof = proof.strip()
        if not proof.lower().startswith(('http://', 'https://')):
            await release_active_challenge(active['_id'])
            await interaction.followup.send('❌ Proof must be an image URL starting with `http://` or `https://`.', ephemeral=True)
            return
        current_season = await get_current_season_number(guild_id)
        if int(active.get('season_number', 0)) != current_season:
            await release_active_challenge(active['_id'])
            await interaction.followup.send('❌ This challenge belongs to an older season. Open `/gauntlet` → **Challenges** → **Find Challenge** to start a new one.', ephemeral=True)
            return
        defense = active.get('defense_courses', [])
        if len(defense) != 5:
            await release_active_challenge(active['_id'])
            await interaction.followup.send('❌ The saved challenge data is incomplete. Please start a new challenge from `/gauntlet` → **Challenges**.', ephemeral=True)
            return
        match_data = await process_match_result(guild_id, user_id, str(active['opponent_id']), defense, challenger_times, proof, active.get('defender_proof_url'), interaction.channel_id, settlement_id=f"{active['_id']}:match")
        if not match_data:
            # Do not blindly release an uncertain settlement. A completed/pending
            # reservation is reconciled by the scheduler; only release when no match
            # reservation exists for this challenge.
            reservation = await bot.db.matches.find_one({'_id': f"{active['_id']}:match", 'guild_id': guild_id})
            if reservation:
                await reconcile_processing_challenges(guild_id)
            else:
                await release_active_challenge(active['_id'])
            await interaction.followup.send('❌ Could not process this match. If a settlement reservation was created, the bot will reconcile it automatically.', ephemeral=True)
            return
        result = await bot.db.active_challenges.update_one({'_id': active['_id'], 'guild_id': guild_id, 'challenger_id': user_id, 'status': 'processing'}, {'$set': {'status': 'completed', 'completed_at': time.time(), 'match_id': match_data['_id']}, '$unset': {'processing_at': ''}})
        if getattr(result, 'modified_count', 0) != 1:
            logging.warning('Match %s settled but challenge %s could not be finalized immediately; scheduler will reconcile it.', match_data['_id'], active['_id'])
        season = current_season
        for i, c in enumerate(defense):
            x = dict(challenger_times[i])
            x['track'] = c['track']
            await save_driver_best_time(guild_id, user_id, x, season, source='match_attack')
        cfg = await bot.db.settings.find_one({'_id': guild_id})
        results = bot.get_channel(int(cfg['match_results_channel_id'])) if cfg and cfg.get('match_results_channel_id') else None
        result_emb = discord.Embed(title='🏁 Gauntlet Match Result', description=match_data['outcome_desc'], color=match_data['display_color'])
        result_emb.add_field(name='Challenger', value=f'<@{user_id}>', inline=True)
        result_emb.add_field(name='Defender', value=f"<@{active['opponent_id']}>", inline=True)
        result_emb.set_image(url=proof)
        result_emb.set_footer(text=f"Best-of-5: {match_data['courses_beat']}/5 races won")
        if results:
            await results.send(embed=result_emb, view=MatchResultPostView(match_data['_id']))
        await interaction.followup.send('✅ **Match submitted!** Results and ELO are updated.', ephemeral=True)
        try:
            defender_user = bot.get_user(int(active['opponent_id'])) or await bot.fetch_user(int(active['opponent_id']))
            await defender_user.send(f"🏁 **Gauntlet match complete**\nYour defense vs <@{user_id}> is complete: {match_data['courses_beat']}/5 courses beaten by the challenger.")
        except Exception:
            pass
        await dispatch_audit_log(guild_id, '🏁 Match Result Processed', f"Match between <@{user_id}> and <@{active['opponent_id']}>. Challenger won {match_data['courses_beat']}/5 races.", color=3066993)
        await dispatch_automated_announcement(guild_id, match_data['announce_title'], f"🏎️ <@{user_id}> vs <@{active['opponent_id']}> — {('Challenger won' if match_data['challenger_won'] else 'Defense held')} {match_data['courses_beat']}/5.", color=match_data['display_color'])

    async def challenge_cmd_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(f'⏳ **Slow down!** You can search for a new opponent again in `{error.retry_after:.0f}s`.', ephemeral=True)
        else:
            logging.exception('/challenge command error', exc_info=error)

    async def cog_load(self):
        self.challenge_cmd.error(self.challenge_cmd_error)

async def setup(bot):
    await bot.add_cog(ChallengesCog(bot))
