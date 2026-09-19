import hashlib
from discord.ext import commands
from discord import app_commands
from ..core.core import *

class DefenseStartView(discord.ui.View):
    """Player-facing handoff from generated courses to the defense submission step."""
    def __init__(self, user_id, tracks, is_change=False):
        super().__init__(timeout=300)
        self.user_id = str(user_id)
        self.tracks = list(tracks or [])
        self.is_change = bool(is_change)

    @discord.ui.button(label='📝 Enter Defense Results', style=discord.ButtonStyle.primary)
    async def enter_results(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message('❌ This defense setup belongs to another driver.', ephemeral=True)
            return
        await interaction.response.send_message(
            '🛡️ **Defense results are ready to submit.**\n\n'
            'Use /submitdefense to enter your 5 lap times, cars, performance ratings, and proof screenshots. '
            'Your current defense remains active until staff approves a change.',
            ephemeral=True,
        )

class DefenseView(discord.ui.View):
    """Staff review controls for a submitted 5-course defense."""
    def __init__(self, user_id, guild_id, courses, proof_url=None, is_change=False):
        super().__init__(timeout=None)
        self.user_id = str(user_id)
        self.guild_id = str(guild_id)
        self.courses = list(courses or [])
        self.proof_url = proof_url
        self.is_change = bool(is_change)

    async def _authorized(self, interaction):
        if interaction.guild is None:
            return False
        if interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_guild:
            return True
        try:
            return bool(await check_admin_privileges(interaction))
        except Exception:
            return False

    async def _finish_message(self, interaction, title, description, color):
        for child in self.children:
            child.disabled = True
        embed = interaction.message.embeds[0].copy() if interaction.message and interaction.message.embeds else discord.Embed()
        embed.title = title
        embed.description = description
        embed.color = color
        embed.set_footer(text='ALU Gauntlet • Defense review completed')
        await interaction.message.edit(embed=embed, view=self)

    async def _notify_driver(self, text):
        try:
            user = bot.get_user(int(self.user_id)) or await bot.fetch_user(int(self.user_id))
            if user:
                await user.send(text)
        except Exception:
            logging.exception('Unable to DM defense review result to driver %s', self.user_id)

    @discord.ui.button(label='✅ Approve Defense', style=discord.ButtonStyle.success, custom_id='alu_defense_approve')
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._authorized(interaction):
            await interaction.response.send_message('❌ Staff/admin access is required to review defenses.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        driver_id = f'{self.guild_id}_{self.user_id}'
        profile = await bot.db.drivers.find_one({'_id': driver_id, 'defense_review_pending': True})
        if not profile:
            await interaction.followup.send('ℹ️ This defense review is already completed or no longer pending.', ephemeral=True)
            for child in self.children: child.disabled = True
            try: await interaction.message.edit(view=self)
            except Exception: pass
            return
        payload = profile.get('defense_review_payload') or {}
        submitted_courses = payload.get('courses') or self.courses
        if len(submitted_courses) != 5:
            await interaction.followup.send('❌ The pending defense payload is invalid and could not be approved.', ephemeral=True)
            return
        locked = {'courses': submitted_courses, 'proof_url': payload.get('proof_url') or self.proof_url, 'car_rank_total': get_car_rank_total(submitted_courses), 'locked_at': time.time(), 'approved_by': str(interaction.user.id), 'submission_id': payload.get('submission_id')}
        update = {'defense_locked': locked, 'pending_tracks': None, 'pending_is_change': False}
        if payload.get('is_change', self.is_change): update['last_defense_change'] = time.time()
        result = await bot.db.drivers.update_one({'_id': driver_id, 'defense_review_pending': True, 'defense_review_payload.submission_id': payload.get('submission_id')}, {'$set': update, '$unset': {'defense_review_pending': '', 'defense_review_payload': ''}})
        if getattr(result, 'modified_count', 0) != 1:
            await interaction.followup.send('⚠️ The review changed before approval could be recorded. Refresh the review and try again.', ephemeral=True)
            return
        await self._finish_message(interaction, '✅ Defense Approved', f'Approved by {interaction.user.mention}. The driver now has an active locked 5-course defense.', ASPHALT_VICTORY_COLOR)
        await self._notify_driver('🛡️ **Defense Approved!** Your 5-course defense has been approved by staff and is now active.')
        await interaction.followup.send('✅ Defense approved and locked.', ephemeral=True)

    @discord.ui.button(label='❌ Reject Defense', style=discord.ButtonStyle.danger, custom_id='alu_defense_reject')
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._authorized(interaction):
            await interaction.response.send_message('❌ Staff/admin access is required to review defenses.', ephemeral=True)
            return
        await interaction.response.send_modal(DefenseRejectModal(self))

class DefenseRejectModal(discord.ui.Modal, title='Reject Defense Submission'):
    reason = discord.ui.TextInput(label='Reason for rejection', placeholder='Explain what the driver needs to correct...', required=False, max_length=500, style=discord.TextStyle.paragraph)
    def __init__(self, review_view):
        super().__init__()
        self.review_view = review_view
    async def on_submit(self, interaction: discord.Interaction):
        view = self.review_view
        if not await view._authorized(interaction):
            await interaction.response.send_message('❌ Staff/admin access is required to review defenses.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        driver_id = f'{view.guild_id}_{view.user_id}'
        profile = await bot.db.drivers.find_one({'_id': driver_id, 'defense_review_pending': True})
        if not profile:
            await interaction.followup.send('ℹ️ This defense review is already completed or no longer pending.', ephemeral=True)
            return
        payload = profile.get('defense_review_payload') or {}
        reason_text = str(self.reason.value or '').strip() or 'Please review your lap times, cars, ratings, and proof screenshots and resubmit.'
        result = await bot.db.drivers.update_one({'_id': driver_id, 'defense_review_pending': True, 'defense_review_payload.submission_id': payload.get('submission_id')}, {'$unset': {'defense_review_pending': '', 'defense_review_payload': '', 'pending_tracks': '', 'pending_is_change': ''}})
        if getattr(result, 'modified_count', 0) != 1:
            await interaction.followup.send('⚠️ The review changed before rejection could be recorded. Refresh the review and try again.', ephemeral=True)
            return
        await view._finish_message(interaction, '❌ Defense Rejected', f'Rejected by {interaction.user.mention}.\n**Reason:** {reason_text}', ASPHALT_ADMIN_COLOR)
        await view._notify_driver(f'❌ **Defense Submission Rejected**\n\n{reason_text}\n\nPlease correct your results and submit your defense again.')
        await interaction.followup.send('❌ Defense rejected and returned to the driver for correction.', ephemeral=True)

class DefenseCog(commands.Cog):

    @app_commands.command(name='setdefense', description='🛡️ Assigns your 5 seasonal defense routes.')
    async def set_defense_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        profile = await bot.db.drivers.find_one({'_id': f'{str(interaction.guild_id)}_{str(interaction.user.id)}'})
        if not profile:
            await interaction.followup.send('❌ Open `/dashboard → **My Gauntlet** → **Register**` first.', ephemeral=True)
            return
        if has_5_course_defense(profile):
            await interaction.followup.send('ℹ️ You already have a defense. Use `/dashboard` → **Defense** → **Change Defense** to change it.', ephemeral=True)
            return
        if profile.get('defense_review_pending'):
            await interaction.followup.send('⏳ Your defense submission is already pending staff review. Wait for it to be approved or rejected.', ephemeral=True)
            return
        pending_tracks = profile.get('pending_tracks')
        if pending_tracks:
            courses = [{'track': t, 'car': 'TBD', 'lap_time': 'TBD'} for t in pending_tracks]
            embeds, files = build_course_embeds(courses, '🛡️ Your 5 Defense Courses (Already Generated)', 'Your five routes are ready. Race them, then press **📝 Enter Defense Results** below to continue.', ASPHALT_THEME_COLOR)
            embeds[-1].set_footer(text='Next step: press **📝 Enter Defense Results** to enter your five times, cars, ratings and proof.')
            await interaction.followup.send(embeds=embeds, files=files, view=DefenseStartView(interaction.user.id, pending_tracks, bool(profile.get('pending_is_change'))), ephemeral=True)
            return
        tracks = profile.get('season_defense_tracks')
        if not tracks or len(tracks) != 5:
            tracks = random.sample(ALU_TRACKS, 5)
            await bot.db.drivers.update_one({'_id': f'{str(interaction.guild_id)}_{str(interaction.user.id)}'}, {'$set': {'season_defense_tracks': tracks}})
        await bot.db.drivers.update_one({'_id': f'{str(interaction.guild_id)}_{str(interaction.user.id)}'}, {'$set': {'pending_tracks': tracks, 'pending_is_change': False}})
        courses = [{'track': t, 'car': 'TBD', 'lap_time': 'TBD'} for t in tracks]
        embeds, files = build_course_embeds(courses, '🛡️ Your 5 Defense Courses Generated', 'Race each of these five tracks and record your best lap times. When ready, press **📝 Enter Defense Results** below.', ASPHALT_THEME_COLOR)
        embeds[-1].set_footer(text='Next step: press **📝 Enter Defense Results** to enter your five times, cars, ratings and proof.')
        await interaction.followup.send(embeds=embeds, files=files, view=DefenseStartView(interaction.user.id, tracks, False), ephemeral=True)

    @app_commands.command(name='mydefense', description='View your currently locked ghost defense.')
    async def my_defense_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        await interaction.response.defer(ephemeral=True)
        guild_id, user_id = (str(interaction.guild_id), str(interaction.user.id))
        profile = await bot.db.drivers.find_one({'_id': f'{guild_id}_{user_id}'})
        if not profile:
            await interaction.followup.send('❌ Open `/dashboard → **My Gauntlet** → **Register**` first.', ephemeral=True)
            return
        defense = profile.get('defense_locked')
        if not defense or not defense.get('courses'):
            await interaction.followup.send('ℹ️ Your defense needs to be upgraded to the new 5-course format. Use `/dashboard` → **Defense** → **Set Defense** to generate new courses.', ephemeral=True)
            return
        courses = defense.get('courses', [])
        embeds, files = build_course_embeds(courses, '🛡️ Your Locked Ghost Defense (5 Courses)', 'Your currently approved 5-course defense lineup.', ASPHALT_THEME_COLOR)
        embeds[-1].set_footer(text='Use `/dashboard` → **Defense → Change Defense** to submit a replacement for staff review (once per day).')
        await interaction.followup.send(embeds=embeds, files=files, ephemeral=True)

    @app_commands.command(name='changedefense', description='🛡️ Re-submit your defense on the same 5 seasonal routes (once per 24 hours).')
    async def change_defense_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        profile = await bot.db.drivers.find_one({'_id': f'{str(interaction.guild_id)}_{str(interaction.user.id)}'})
        if not profile:
            await interaction.followup.send('❌ Open `/dashboard → **My Gauntlet** → **Register**` first.', ephemeral=True)
            return
        if not has_5_course_defense(profile):
            await interaction.followup.send("ℹ️ You don't have a valid 5-course defense yet. Use `/dashboard` → **Defense** → **Set Defense** to set up your first one.", ephemeral=True)
            return
        if profile.get('defense_review_pending'):
            await interaction.followup.send('⏳ Your defense change is already pending staff review. Wait for it to be approved or rejected.', ephemeral=True)
            return
        last_change = profile.get('last_defense_change')
        if last_change:
            elapsed = time.time() - last_change
            if elapsed < 86400:
                remaining = 86400 - elapsed
                hours = int(remaining // 3600)
                minutes = int(remaining % 3600 // 60)
                await interaction.followup.send(f'⏳ **Cooldown Active:** You can change your defense again in `{hours}h {minutes}m`. Defense changes are limited to once per day.', ephemeral=True)
                return
        pending_tracks = profile.get('pending_tracks')
        if pending_tracks:
            courses = [{'track': t, 'car': 'TBD', 'lap_time': 'TBD'} for t in pending_tracks]
            embeds, files = build_course_embeds(courses, '🛡️ Your 5 New Defense Courses (Already Generated)', 'You already have new courses generated. Race each track and use the guided **Defense** wizard to submit your times and cars.\n\nYour current defense remains active until the new one is approved.', ASPHALT_THEME_COLOR)
            embeds[-1].set_footer(text='Next step: press **📝 Enter Defense Results** to enter the replacement lineup and proof.')
            await interaction.followup.send(embeds=embeds, files=files, view=DefenseStartView(interaction.user.id, pending_tracks, True), ephemeral=True)
            return
        tracks = [course.get('track') for course in profile.get('defense_locked', {}).get('courses', [])]
        if len(tracks) != 5:
            tracks = profile.get('season_defense_tracks') or [course.get('track') for course in profile.get('defense_locked', {}).get('courses', [])]
        if len(tracks) != 5:
            await interaction.followup.send('❌ Your season route set is missing. Ask staff to repair your defense profile before changing it.', ephemeral=True)
            return
        await bot.db.drivers.update_one({'_id': f'{str(interaction.guild_id)}_{str(interaction.user.id)}'}, {'$set': {'season_defense_tracks': tracks, 'pending_tracks': tracks, 'pending_is_change': True}})
        courses = [{'track': t, 'car': 'TBD', 'lap_time': 'TBD'} for t in tracks]
        embeds, files = build_course_embeds(courses, '🛡️ Your 5 New Defense Courses Generated', 'Race each of these five tracks and record your best lap times. When ready, press **📝 Enter Defense Results** below.\n\nYour current defense remains active until the new one is approved.', ASPHALT_THEME_COLOR)
        embeds[-1].set_footer(text='Next step: press **📝 Enter Defense Results** to enter the replacement lineup and proof.')
        await interaction.followup.send(embeds=embeds, files=files, view=DefenseStartView(interaction.user.id, tracks, True), ephemeral=True)

    @app_commands.command(name='submitdefense', description='🛡️ Submit your times, cars, and proof screenshots for your generated defense courses.')
    @app_commands.autocomplete(car_1=car_autocomplete, car_2=car_autocomplete, car_3=car_autocomplete, car_4=car_autocomplete, car_5=car_autocomplete)
    @app_commands.describe(lap_time_1='Lap time for course 1 (MM:SS.MS)', lap_time_2='Lap time for course 2 (MM:SS.MS)', lap_time_3='Lap time for course 3 (MM:SS.MS)', lap_time_4='Lap time for course 4 (MM:SS.MS)', lap_time_5='Lap time for course 5 (MM:SS.MS)', car_1='Car for course 1', car_2='Car for course 2', car_3='Car for course 3', car_4='Car for course 4', car_5='Car for course 5', car_rank_1='Numeric car performance/rating for course 1', car_rank_2='Numeric car performance/rating for course 2', car_rank_3='Numeric car performance/rating for course 3', car_rank_4='Numeric car performance/rating for course 4', car_rank_5='Numeric car performance/rating for course 5', proof_screenshot_1='Screenshot proving lap time 1', proof_screenshot_2='Screenshot proving lap time 2', proof_screenshot_3='Screenshot proving lap time 3', proof_screenshot_4='Screenshot proving lap time 4', proof_screenshot_5='Screenshot proving lap time 5')
    async def submit_defense_cmd(self, interaction: discord.Interaction, lap_time_1: str, lap_time_2: str, lap_time_3: str, lap_time_4: str, lap_time_5: str, car_1: str, car_2: str, car_3: str, car_4: str, car_5: str, car_rank_1: int, car_rank_2: int, car_rank_3: int, car_rank_4: int, car_rank_5: int, proof_screenshot_1: discord.Attachment, proof_screenshot_2: discord.Attachment, proof_screenshot_3: discord.Attachment, proof_screenshot_4: discord.Attachment, proof_screenshot_5: discord.Attachment):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        profile = await bot.db.drivers.find_one({'_id': f'{str(interaction.guild_id)}_{str(interaction.user.id)}'})
        if not profile:
            await interaction.followup.send('❌ Open `/dashboard → **My Gauntlet** → **Register**` first.', ephemeral=True)
            return
        if profile.get('defense_review_pending'):
            await interaction.followup.send('⏳ Your defense submission is already pending staff review. Wait for it to be approved or rejected.', ephemeral=True)
            return
        pending_tracks = profile.get('pending_tracks')
        if not pending_tracks:
            await interaction.followup.send('❌ No pending courses. Use `/dashboard` → **Defense** to generate courses first.', ephemeral=True)
            return
        is_change = profile.get('pending_is_change', False)
        lap_times = [lap_time_1, lap_time_2, lap_time_3, lap_time_4, lap_time_5]
        cars = [car_1, car_2, car_3, car_4, car_5]
        car_ranks = [car_rank_1, car_rank_2, car_rank_3, car_rank_4, car_rank_5]
        proof_screenshots = [proof_screenshot_1, proof_screenshot_2, proof_screenshot_3, proof_screenshot_4, proof_screenshot_5]
        if any((int(rank) <= 0 for rank in car_ranks)):
            await interaction.followup.send('❌ **Invalid Car Performance:** All 5 car performance/rating values must be positive numbers.', ephemeral=True)
            return
        if len({c.strip().lower() for c in cars}) != len(cars):
            await interaction.followup.send('❌ **Duplicate Cars:** All 5 cars must be different. Please choose 5 unique cars.', ephemeral=True)
            return
        for i, shot in enumerate(proof_screenshots):
            if not shot.content_type or not shot.content_type.startswith('image/'):
                await interaction.followup.send(f'❌ **Invalid Proof:** The screenshot for lap {i + 1} must be an image file.', ephemeral=True)
                return
        courses = []
        for i in range(5):
            ms = parse_lap_time(lap_times[i])
            if ms <= 0:
                await interaction.followup.send(f'❌ **Invalid Lap Time:** Lap {i + 1} (`{lap_times[i]}`) must be a positive `MM:SS.MS` time with seconds from 00–59.', ephemeral=True)
                return
            courses.append({'track': pending_tracks[i], 'car': cars[i], 'car_rank': int(car_ranks[i]), 'lap_time': lap_times[i], 'ms': ms, 'proof_url': proof_screenshots[i].url})
        cfg = await bot.db.settings.find_one({'_id': str(interaction.guild_id)})
        chan = bot.get_channel(int(cfg['review_channel_id'])) if cfg else None
        if chan:
            driver_id = f'{str(interaction.guild_id)}_{str(interaction.user.id)}'
            submitted_at = time.time()
            submission_id = hashlib.sha256(f"{interaction.guild_id}:{interaction.user.id}:{submitted_at}".encode()).hexdigest()[:24]
            payload = {'courses': courses, 'proof_url': courses[0]['proof_url'], 'is_change': bool(is_change), 'submitted_at': submitted_at, 'submission_id': submission_id}
            claim = await bot.db.drivers.update_one(
                {'_id': driver_id, 'defense_review_pending': {'$ne': True}},
                {'$set': {'defense_review_pending': True, 'defense_review_payload': payload}}
            )
            if getattr(claim, 'modified_count', 0) != 1:
                await interaction.followup.send('⏳ Your defense submission is already pending staff review. Wait for a decision before submitting another.', ephemeral=True)
                return
            if is_change:
                header_emb = discord.Embed(title='🛡️ Gauntlet Defense Change Request', description='A driver has requested to change their locked 5-course defense. Their current defense remains active until the new one is approved.', color=3447003)
            else:
                header_emb = discord.Embed(title='🛡️ New Gauntlet Defense Placement Verification', description="**Staff:** please verify each course's lap time and car against its matching screenshot below.", color=3447003)
            header_emb.add_field(name='Driver', value=interaction.user.mention, inline=False)
            header_emb.set_footer(text=f'ALU Defense Submission: {submission_id}')
            review_embeds = [header_emb]
            icon_files = []
            for i, course in enumerate(courses):
                course_emb = discord.Embed(title=f"🏁 Course {i + 1}: {course['track']}", description=f"🚗 **Car:** `{course['car']}`\n📈 **Car Performance:** `{course['car_rank']}`\n⏱️ **Lap Time:** `{course['lap_time']}`", color=3447003)
                icon_file, filename = map_icon_file(course['track'], i)
                if icon_file:
                    icon_files.append(icon_file)
                    add_map_icon(course_emb, course['track'], filename)
                course_emb.set_image(url=course['proof_url'])
                review_embeds.append(course_emb)
            try:
                message = await chan.send(embeds=review_embeds, files=icon_files, view=DefenseView(str(interaction.user.id), str(interaction.guild_id), courses, courses[0]['proof_url'], is_change=is_change))
                await bot.db.drivers.update_one({'_id': driver_id, 'defense_review_pending': True, 'defense_review_payload.submission_id': submission_id}, {'$set': {'defense_review_payload.review_channel_id': int(chan.id), 'defense_review_payload.review_message_id': int(message.id), 'defense_review_payload.delivery_status': 'delivered'}})
            except Exception:
                logging.exception('Defense review message delivery failed')
                found = await find_recent_bot_message(chan, f'ALU Defense Submission: {submission_id}', limit=20)
                if found:
                    await bot.db.drivers.update_one({'_id': driver_id, 'defense_review_payload.submission_id': submission_id}, {'$set': {'defense_review_payload.review_channel_id': int(chan.id), 'defense_review_payload.review_message_id': int(found.id), 'defense_review_payload.delivery_status': 'delivered'}})
                else:
                    await bot.db.drivers.update_one({'_id': driver_id, 'defense_review_payload.submission_id': submission_id}, {'$unset': {'defense_review_pending': '', 'defense_review_payload': ''}})
                    await interaction.followup.send('❌ Staff review message could not be delivered. Your submission was safely rolled back; please try again.', ephemeral=True)
                    return
            if is_change:
                await interaction.followup.send('📥 **Defense Change Staged:** 5-course lineup sent to staff for audit clearance! Your current defense remains active until the new one is approved.')
            else:
                await interaction.followup.send('📥 **Defense Staged:** 5-course lineup sent to staff for audit clearance!')
        else:
            await interaction.followup.send('❌ Staff review channel is not configured. Ask an administrator to open `/staff` → **Server Setup → Server Setup**.', ephemeral=True)

async def setup(bot):
    await bot.add_cog(DefenseCog(bot))

    # Re-register pending review buttons after a bot restart.
    try:
        pending = await bot.db.drivers.find({
            'defense_review_pending': True,
            'defense_review_payload.review_channel_id': {'$exists': True},
            'defense_review_payload.review_message_id': {'$exists': True},
        }).to_list(length=None)
        for profile in pending:
            payload = profile.get('defense_review_payload') or {}
            courses = payload.get('courses') or []
            raw_id = str(profile.get('_id', ''))
            if '_' not in raw_id or len(courses) != 5:
                continue
            guild_id, user_id = raw_id.split('_', 1)
            view = DefenseView(
                user_id, guild_id, courses, payload.get('proof_url'),
                is_change=bool(payload.get('is_change')),
            )
            bot.add_view(view, message_id=int(payload['review_message_id']))
    except Exception:
        logging.exception('Unable to restore pending defense review views after startup')
