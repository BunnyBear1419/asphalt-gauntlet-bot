import re
from discord.ext import commands
from discord import app_commands
from ..core.core import *

async def send_dashboard(interaction: discord.Interaction):
    """Send the canonical player dashboard without removing player access for staff."""
    guild_id = str(interaction.guild_id)
    user_id = str(interaction.user.id)
    view = DashboardView(guild_id, user_id, False)
    embed = discord.Embed(
        title='🏁 RACING SYNDICATE LEAGUE • PLAYER DASHBOARD',
        description='Race. Compete. Unite.\n\nUse the controls below to manage your driver profile, defense, challenges, rankings, and season activity.',
        color=ASPHALT_THEME_COLOR,
    )
    embed.set_footer(text='Player controls • Staff players retain full player access')
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# Player dashboard access is intentionally independent of staff permissions:
# staff/admin players keep the full player dashboard and gain /staff separately.
class PlayerCog(commands.Cog):

    @app_commands.guild_only()
    @app_commands.command(name='dashboard', description='Open your Racing Syndicate League player dashboard.')
    async def gauntlet_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        await send_dashboard(interaction)

    @app_commands.command(name='whatnext', description='Show your next required Gauntlet step.')
    async def whatnext_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        guild_id, user_id = (str(interaction.guild_id), str(interaction.user.id))
        season = await get_current_season_number(guild_id)
        p = await bot.db.drivers.find_one({'_id': f'{guild_id}_{user_id}'})
        if not p:
            msg = '1️⃣ Open `/dashboard` → **My Gauntlet** → **Register** to open the guided registration form'
        elif not p.get('season_registered') or int(p.get('season_number', 0)) != season:
            msg = f'1️⃣ Re-register for Season {season}: `/dashboard` → **My Gauntlet** → **Register**'
        elif not p.get('defense_locked'):
            msg = '1️⃣ Open `/dashboard` → **Defense** → **Set Defense**\n2️⃣ Complete the guided defense wizard'
        else:
            active = await bot.db.active_challenges.find_one({'_id': f'{guild_id}_{user_id}', 'guild_id': str(guild_id), 'status': {'$in': ['active', 'processing']}})
            msg = '1️⃣ Open `/dashboard` → **Challenges** → **Submit Match**' if active else "✅ You're ready — open `/dashboard` → **Challenges** → **Find Challenge**"
        await interaction.response.send_message(embed=discord.Embed(title='🏁 WHAT NEXT?', description=msg, color=ASPHALT_THEME_COLOR), ephemeral=True)

    @app_commands.command(name='profile', description='Inspects driver file card.')
    async def profile_cmd(self, interaction: discord.Interaction, driver: discord.Member=None):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        await interaction.response.defer()
        target_user = driver or interaction.user
        profile = await bot.db.drivers.find_one({'_id': f'{str(interaction.guild_id)}_{str(target_user.id)}'})
        if not profile:
            await interaction.followup.send('❌ Profile card missing. Open `/dashboard` → **My Gauntlet** → **Register** first.')
            return
        embed = discord.Embed(title='🏁 RACING SYNDICATE LEAGUE DRIVER DOSSIER CARD', color=ASPHALT_THEME_COLOR)
        embed.set_thumbnail(url=ASPHALT_MEDIA['thumb_profile'])
        matches = await bot.db.matches.find({
            'guild_id': str(interaction.guild_id),
            'reverted': {'$ne': True},
            '$or': [{'challenger_id': str(target_user.id)}, {'opponent_id': str(target_user.id)}],
        }).sort('timestamp', -1).to_list(length=1000)
        wins = sum(1 for m in matches if str(m.get('w_id')) == str(target_user.id))
        losses = sum(1 for m in matches if str(m.get('l_id')) == str(target_user.id))
        played = wins + losses
        win_rate = (wins / played * 100) if played else 0.0
        current_season = await get_current_season_number(str(interaction.guild_id))
        rank_cursor = bot.db.drivers.find({'guild_id': str(interaction.guild_id), 'season_registered': True, 'season_number': current_season}).sort('elo', -1)
        ranked = await rank_cursor.to_list(length=5000)
        rank = next((i + 1 for i, row in enumerate(ranked) if str(row.get('user_id')) == str(target_user.id)), None)
        lap_rows = await bot.db.lap_times.find({'guild_id': str(interaction.guild_id), 'user_id': str(target_user.id)}).sort('best_ms', 1).to_list(length=100)
        records = 0
        for row in lap_rows:
            record_id = re.sub(r'[^a-z0-9]+', '_', str(row.get('track', '')).lower()).strip('_')
            global_rec = await bot.db.map_records.find_one({'_id': record_id})
            if global_rec and str(global_rec.get('user_id')) == str(target_user.id) and int(global_rec.get('best_ms', 10**18)) == int(row.get('best_ms', -1)):
                records += 1
        recent = []
        for m in matches[:5]:
            result = '🏆 Win' if str(m.get('w_id')) == str(target_user.id) else '❌ Loss'
            recent.append(f"{result} • `{m.get('courses_beat', 0)}/5` • <t:{int(m.get('timestamp', now_ts()))}:R>")
        embed.add_field(name='👤 Pilot Credentials', value=f'• **User:** {target_user.mention}\n• **Game ID Node:** `{profile.get("game_id")}`', inline=True)
        embed.add_field(name='📊 Rating & Rank', value=f"**{int(profile.get('elo', 1000))} ELO**\nRank: **#{rank or '—'}**\n{get_division_for_pi(int(profile.get('garage_pi', 0)))['name']}\nSeason {current_season}", inline=True)
        dominance = profile.get("rsl_dominance") or {}
        buckets = dominance.get("score_buckets") or {}
        race_wins = int(dominance.get("race_wins", 0) or 0)
        race_losses = int(dominance.get("race_losses", 0) or 0)
        embed.add_field(name='📈 Career Performance', value=f"**{wins}-{losses}**\nWin rate: **{win_rate:.1f}%**\nMatches: `{played}`\n🔥 Streak: `{int(profile.get('streak', 0))}`\n🏆 Career wins: `{int(profile.get('career_wins', 0))}`\n🏁 Track records: `{records}`\n🏎️ Race record: `{race_wins}-{race_losses}`", inline=True)
        if dominance:
            embed.add_field(name='⚖️ Match Dominance', value=f"**5-0:** `{buckets.get("5-0", 0)}` • **4-1:** `{buckets.get("4-1", 0)}`\n**3-2:** `{buckets.get("3-2", 0)}` • **2-3:** `{buckets.get("2-3", 0)}`\n**1-4:** `{buckets.get("1-4", 0)}` • **0-5:** `{buckets.get("0-5", 0)}`", inline=True)
        if lap_rows:
            embed.add_field(name='⚡ Best Saved Laps', value='\n'.join(f"`{r.get('best_lap_time', '?')}` — {r.get('track', 'Unknown')}" for r in lap_rows[:5]), inline=False)
        if recent:
            embed.add_field(name='🏁 Recent Matches', value='\n'.join(recent), inline=False)
        if has_5_course_defense(profile):
            courses = profile['defense_locked'].get('courses', [])
            if courses:
                def_lines = ''
                for i, course in enumerate(courses):
                    def_lines += f"🏁 **Course {i + 1}:** `{course['track']}` | 🚗 `{course['car']}` | 📈 `{course.get('car_rank', 'N/A')}` | ⏱️ `{course['lap_time']}`\n"
                total_rank = get_car_rank_total(courses)
                def_lines += f'\n📊 **Total Car Performance Rating:** `{total_rank:,}`'
                embed.add_field(name='🛡️ Deployed Ghost Defense Framework', value=def_lines, inline=False)
        embed.set_footer(text='Profile & Stats • Use /dashboard → Competition → Season History for archived seasons', icon_url=target_user.display_avatar.url)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name='register', description='Open the guided Racing Syndicate League registration form.')
    async def register_launcher_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        await interaction.response.send_modal(RegistrationModal())

    @app_commands.command(name='mystatus', description='Check your current-season driver registration status.')
    async def my_status_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        await interaction.response.defer(ephemeral=True)
        guild_id, user_id = (str(interaction.guild_id), str(interaction.user.id))
        state = await bot.db.season_state.find_one({'_id': f'guild_{guild_id}'})
        season_number = int(state.get('season_number', 1)) if state else 1
        profile = await bot.db.drivers.find_one({'_id': f'{guild_id}_{user_id}'})
        if profile and profile.get('season_registered') and (int(profile.get('season_number', 0)) == season_number):
            division = get_division_for_pi(int(profile.get('garage_pi', 0)))['name']
            defense = profile.get('defense_locked')
            defense_status = '5-course defense locked' if has_5_course_defense(profile) else 'defense still needs to be set'
            await interaction.followup.send(f"✅ **Season {season_number} Driver:** `{profile.get('elo', 1000)} ELO` / `{profile.get('garage_pi', 0):,} PI` → **{division}**. {defense_status}.", ephemeral=True)
            return
        pending = await bot.db.pending.find_one({'_id': f'{guild_id}_{user_id}'})
        if pending and int(pending.get('season_number', season_number)) == season_number:
            division = get_division_for_pi(int(pending.get('rank', 0)))['name']
            await interaction.followup.send(f"⏳ **Season {season_number} Pending Review:** Garage `{int(pending.get('rank', 0)):,} PI` → projected **{division}**. Staff approval is still required.", ephemeral=True)
            return
        career = profile.get('career_wins', 0) if profile else 0
        played = profile.get('career_played', 0) if profile else 0
        await interaction.followup.send(f'🔄 **Season {season_number} Re-Registration Required.** Your career record remains safe (`{career}` wins / `{played}` matches). Open `/dashboard` → **My Gauntlet** → **Register** with your current Garage PI to enter this season.', ephemeral=True)

    @app_commands.command(name='delete_me', description='Permanently delete your Racing Syndicate League data from this server.')
    async def delete_me_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)
        profile = await bot.db.drivers.find_one({'_id': f'{guild_id}_{user_id}'})
        pending = await bot.db.pending.find_one({'_id': f'{guild_id}_{user_id}'})
        if not profile and (not pending):
            await interaction.response.send_message('ℹ️ You do not have an active Racing Syndicate League record in this server.', ephemeral=True)
            return
        await interaction.response.send_message('⚠️ **Permanently delete your Racing Syndicate League data?**\n\nThis removes your driver profile, current/past match records, active challenges, pending submissions, and your archived season-standing entries from **this server**. This cannot be undone.\n\nIf you join again, you will start as a new player.', view=ConfirmDeleteMeView(guild_id, user_id), ephemeral=True)

async def setup(bot):
    await bot.add_cog(PlayerCog(bot))
