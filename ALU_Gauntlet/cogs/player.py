import uuid
from discord.ext import commands
from discord import app_commands
from ..core.core import *

class PlayerCog(commands.Cog):

    @app_commands.command(name='gauntlet', description='Open your ALU Gauntlet player dashboard.')
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
            msg = '1️⃣ Run `/register` to open the guided registration form'
        elif not p.get('season_registered') or int(p.get('season_number', 0)) != season:
            msg = f'1️⃣ Re-register for Season {season}: `/register`'
        elif not p.get('defense_locked'):
            msg = '1️⃣ Open `/gauntlet` → **Defense** → **Set Defense**\n2️⃣ Complete the guided defense wizard'
        else:
            active = await bot.db.active_challenges.find_one({'_id': f'{guild_id}_{user_id}', 'guild_id': str(guild_id), 'status': 'active'})
            msg = '1️⃣ Open `/gauntlet` → **Challenges** → **Submit Match**' if active else "✅ You're ready — open `/gauntlet` → **Challenges** → **Find Challenge**"
        await interaction.response.send_message(embed=discord.Embed(title='🏁 WHAT NEXT?', description=msg, color=ASPHALT_THEME_COLOR), ephemeral=True)

    @app_commands.command(name='profile', description='Inspects driver file card.')
    async def profile_cmd(self, interaction: discord.Interaction, driver: discord.Member=None):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        await interaction.response.defer()
        target_user = driver or interaction.user
        profile = await bot.db.drivers.find_one({'_id': f'{str(interaction.guild_id)}_{str(target_user.id)}'})
        if not profile:
            await interaction.followup.send('❌ Profile card missing. Open `/register` first.')
            return
        embed = discord.Embed(title='🏁 ALU GAUNTLET DRIVER DOSSIER CARD', color=ASPHALT_THEME_COLOR)
        embed.set_thumbnail(url=ASPHALT_MEDIA['thumb_profile'])
        stats_matrix = f"• **League Elo Rating:** `{profile.get('elo', 1000)} ELO`\n• **Performance Group:** `{profile.get('garage_pi', 0):,} PI Value`\n• **Career Victories:** `{profile.get('career_wins', 0)} Wins`\n• **Total Matches:** `{profile.get('career_played', 0)} Played`\n• **Active Win Streak:** `{profile.get('streak', 0)} Streak`"
        embed.add_field(name='👤 Pilot Credentials', value=f"• **User:** {target_user.mention}\n• **Game ID Node:** `{profile.get('game_id')}`", inline=True)
        embed.add_field(name='📊 Operational Statistics Ledger', value=stats_matrix, inline=False)
        if has_5_course_defense(profile):
            courses = profile['defense_locked'].get('courses', [])
            if courses:
                def_lines = ''
                for i, course in enumerate(courses):
                    def_lines += f"🏁 **Course {i + 1}:** `{course['track']}` | 🚗 `{course['car']}` | 📈 `{course.get('car_rank', 'N/A')}` | ⏱️ `{course['lap_time']}`\n"
                total_rank = get_car_rank_total(courses)
                def_lines += f'\n📊 **Total Car Performance Rating:** `{total_rank:,}`'
                embed.add_field(name='🛡️ Deployed Ghost Defense Framework', value=def_lines, inline=False)
        embed.set_footer(text='System Terminal Sync Matrix v2.0', icon_url=target_user.display_avatar.url)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name='register', description='Open the guided ALU Gauntlet registration form.')
    async def register_launcher_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        await interaction.response.send_modal(RegistrationModal())

    @app_commands.command(name='register_direct', description='[Advanced] Submit registration fields directly.')
    @app_commands.describe(game_id='Your Asphalt Legends unique Player ID string', garage_pi='Your current Garage PI value, as shown in-game', proof_screenshot='Attachment file proving garage level and ratings', control_type='Your input driving mechanics style')
    @app_commands.choices(control_type=[app_commands.Choice(name='TouchDrive Auto Pilot', value='touchdrive'), app_commands.Choice(name='Manual Tilt / Tap Controls', value='manual')])
    async def register_cmd(self, interaction: discord.Interaction, game_id: str, garage_pi: int, proof_screenshot: discord.Attachment, control_type: app_commands.Choice[str]):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        guild_id, user_id = (str(interaction.guild_id), str(interaction.user.id))
        cfg = await bot.db.settings.find_one({'_id': guild_id})
        if not cfg or not cfg.get('review_channel_id'):
            await interaction.followup.send('❌ **System Configurations Incomplete:** Ask an administrator to execute `/setup` first.', ephemeral=True)
            return
        if garage_pi <= 0:
            await interaction.followup.send('❌ **Invalid Value:** Garage PI must be a positive number.', ephemeral=True)
            return
        if not proof_screenshot.content_type or not proof_screenshot.content_type.startswith('image/'):
            await interaction.followup.send('❌ **Invalid Proof:** Please attach an image screenshot of your current Garage PI.', ephemeral=True)
            return
        state = await bot.db.season_state.find_one({'_id': f'guild_{guild_id}'})
        season_number = int(state.get('season_number', 1)) if state else 1
        existing = await bot.db.drivers.find_one({'_id': f'{guild_id}_{user_id}'})
        if existing and existing.get('season_registered') and (int(existing.get('season_number', 0)) == season_number):
            await interaction.followup.send('⚠️ **Already Registered:** Your Garage is already registered for the current season. Your career stats are safe; open `/gauntlet` → **My Gauntlet** → **Profile** to view them.', ephemeral=True)
            return
        pending_id = f'{guild_id}_{user_id}'
        submission_id = uuid.uuid4().hex
        review_chan = bot.get_channel(int(cfg['review_channel_id']))
        if not review_chan:
            await interaction.followup.send('❌ Staff review channel could not be found. Ask an administrator to run `/setup`.', ephemeral=True)
            return
        is_rereg = bool(existing)
        previous_pi = existing.get('garage_pi') if existing else None
        division = get_division_for_pi(garage_pi)['name']
        emb = discord.Embed(title='🔄 Garage Re-Registration' if is_rereg else '👤 New Driver Registration Application', description=f'Season **{season_number}** Garage verification packet. This is a **re-registration**; lifetime career statistics must be preserved.\n**Staff:** compare the declared Garage PI against the screenshot before approving.' if is_rereg else 'Incoming driver verification packet submitted by user.\n**Staff:** please compare the declared Garage PI against the attached screenshot before approving.', color=ASPHALT_ADMIN_COLOR)
        emb.add_field(name='Applicant User', value=interaction.user.mention, inline=True)
        emb.add_field(name='Declared Game ID', value=f'`{game_id}`', inline=True)
        emb.add_field(name='Declared Garage PI', value=f'`{garage_pi:,} PI`', inline=True)
        emb.add_field(name='Projected Division', value=division, inline=True)
        emb.add_field(name='Season', value=f'`{season_number}`', inline=True)
        if previous_pi is not None:
            emb.add_field(name='Previous Season PI', value=f'`{int(previous_pi):,} PI`', inline=True)
        emb.add_field(name='Dynamic Driving Layout', value=f'`{control_type.name}`', inline=False)
        emb.set_image(url=proof_screenshot.url)
        claim = await bot.db.pending.update_one(
            {'_id': pending_id, 'season_number': {'$ne': season_number}},
            {'$set': {'guild_id': guild_id, 'user_id': user_id, 'game_id': game_id, 'rank': garage_pi, 'control': control_type.value, 'season_number': season_number, 'is_reregistration': is_rereg, 'submitted_at': time.time(), 'proof_url': proof_screenshot.url, 'delivery_status': 'sending', 'submission_id': submission_id}},
            upsert=True,
        )
        if getattr(claim, 'modified_count', 0) != 1 and getattr(claim, 'upserted_id', None) is None:
            await interaction.followup.send('⚠️ **Application Already Pending:** Your current-season Garage registration is awaiting staff review.', ephemeral=True)
            return
        emb.set_footer(text=f'ALU Registration Submission: {pending_id}')
        try:
            review_message = await review_chan.send(embed=emb, view=VerificationView(user_id, guild_id, game_id, garage_pi, control_type.value, submission_id))
            await bot.db.pending.update_one({'_id': pending_id, 'season_number': season_number, 'submission_id': submission_id}, {'$set': {'review_channel_id': int(review_chan.id), 'review_message_id': int(review_message.id), 'delivery_status': 'delivered'}})
        except Exception:
            logging.exception('Registration review message delivery failed')
            found = await find_recent_bot_message(review_chan, f'ALU Registration Submission: {pending_id}', limit=20)
            if found:
                await bot.db.pending.update_one({'_id': pending_id, 'season_number': season_number, 'submission_id': submission_id}, {'$set': {'review_channel_id': int(review_chan.id), 'review_message_id': int(found.id), 'delivery_status': 'delivered'}})
            else:
                await bot.db.pending.delete_one({'_id': pending_id, 'season_number': season_number, 'submission_id': submission_id})
                await interaction.followup.send('❌ Staff review message could not be delivered. Your registration was safely rolled back; please try again.', ephemeral=True)
                return
        await interaction.followup.send(f'📥 **Season {season_number} Garage Registration Submitted:** Staff can approve your `{garage_pi:,} PI` projected **{division}** placement. Career stats are retained.', ephemeral=True)

    @app_commands.command(name='notifications', description='Turn your Gauntlet reminder DMs on or off.')
    @app_commands.describe(setting='Choose whether ALU Gauntlet reminder DMs are enabled')
    @app_commands.choices(setting=[app_commands.Choice(name='On — receive reminder DMs', value="on"), app_commands.Choice(name='Off — stop reminder DMs', value="off")])
    async def notifications_cmd(self, interaction: discord.Interaction, setting: app_commands.Choice[str]):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        guild_id, user_id = (str(interaction.guild_id), str(interaction.user.id))
        profile = await bot.db.drivers.find_one({'_id': f'{guild_id}_{user_id}', 'guild_id': guild_id})
        if not profile:
            await interaction.response.send_message('❌ You need a player profile first. Run `/register` to join the league.', ephemeral=True)
            return
        enabled = setting.value == 'on'
        await bot.db.drivers.update_one({'_id': f'{guild_id}_{user_id}', 'guild_id': guild_id}, {'$set': {'dm_notifications_enabled': enabled}})
        if enabled:
            message = '🔔 **Gauntlet reminder DMs are ON.** You can change this anytime from `/gauntlet` → **My Gauntlet** → **Notifications**.'
        else:
            message = '🔕 **Gauntlet reminder DMs are OFF.** You will no longer receive automated reminder DMs. Server-wide season announcements are not affected.'
        await interaction.response.send_message(message, ephemeral=True)

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
        await interaction.followup.send(f'🔄 **Season {season_number} Re-Registration Required.** Your career record remains safe (`{career}` wins / `{played}` matches). Open `/register` with your current Garage PI to enter this season.', ephemeral=True)

    @app_commands.command(name='delete_me', description='Permanently delete your ALU Gauntlet data from this server.')
    async def delete_me_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)
        profile = await bot.db.drivers.find_one({'_id': f'{guild_id}_{user_id}'})
        pending = await bot.db.pending.find_one({'_id': f'{guild_id}_{user_id}'})
        if not profile and (not pending):
            await interaction.response.send_message('ℹ️ You do not have an active ALU Gauntlet record in this server.', ephemeral=True)
            return
        await interaction.response.send_message('⚠️ **Permanently delete your ALU Gauntlet data?**\n\nThis removes your driver profile, current/past match records, active challenges, pending submissions, and your archived season-standing entries from **this server**. This cannot be undone.\n\nIf you join again, you will start as a new player.', view=ConfirmDeleteMeView(guild_id, user_id), ephemeral=True)

async def setup(bot):
    await bot.add_cog(PlayerCog(bot))
