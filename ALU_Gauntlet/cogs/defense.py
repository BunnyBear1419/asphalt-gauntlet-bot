import hashlib
from discord.ext import commands
from discord import app_commands
from ..core.core import *

class DefenseCog(commands.Cog):

    @app_commands.command(name='setdefense', description='🛡️ Assigns your 5 seasonal defense routes.')
    async def set_defense_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        profile = await bot.db.drivers.find_one({'_id': f'{str(interaction.guild_id)}_{str(interaction.user.id)}'})
        if not profile:
            await interaction.followup.send('❌ Open `/register` first.', ephemeral=True)
            return
        if has_5_course_defense(profile):
            await interaction.followup.send('ℹ️ You already have a defense. Use `/gauntlet` → **Defense** → **Change Defense** to change it.', ephemeral=True)
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
            await interaction.followup.send('❌ Open `/register` first.', ephemeral=True)
            return
        defense = profile.get('defense_locked')
        if not defense or not defense.get('courses'):
            await interaction.followup.send('ℹ️ Your defense needs to be upgraded to the new 5-course format. Use `/gauntlet` → **Defense** → **Set Defense** to generate new courses.', ephemeral=True)
            return
        courses = defense.get('courses', [])
        embeds, files = build_course_embeds(courses, '🛡️ Your Locked Ghost Defense (5 Courses)', 'Your currently approved 5-course defense lineup.', ASPHALT_THEME_COLOR)
        embeds[-1].set_footer(text='Use /changedefense to submit a replacement for staff review (once per day).')
        await interaction.followup.send(embeds=embeds, files=files, ephemeral=True)

    @app_commands.command(name='changedefense', description='🛡️ Re-submit your defense on the same 5 seasonal routes (once per 24 hours).')
    async def change_defense_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        profile = await bot.db.drivers.find_one({'_id': f'{str(interaction.guild_id)}_{str(interaction.user.id)}'})
        if not profile:
            await interaction.followup.send('❌ Open `/register` first.', ephemeral=True)
            return
        if not has_5_course_defense(profile):
            await interaction.followup.send("ℹ️ You don't have a valid 5-course defense yet. Use `/gauntlet` → **Defense** → **Set Defense** to set up your first one.", ephemeral=True)
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
            await interaction.followup.send('❌ Open `/register` first.', ephemeral=True)
            return
        if profile.get('defense_review_pending'):
            await interaction.followup.send('⏳ Your defense submission is already pending staff review. Wait for it to be approved or rejected.', ephemeral=True)
            return
        pending_tracks = profile.get('pending_tracks')
        if not pending_tracks:
            await interaction.followup.send('❌ No pending courses. Use `/gauntlet` → **Defense** to generate courses first.', ephemeral=True)
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
                await bot.db.drivers.update_one({'_id': driver_id, 'defense_review_pending': True, 'defense_review_payload.submission_id': submission_id}, {'$set': {'defense_review_payload.review_channel_id': int(chan.id), 'defense_review_payload.review_message_id': int(message.id)}})
            except Exception:
                await bot.db.drivers.update_one({'_id': driver_id, 'defense_review_payload.submission_id': submission_id}, {'$unset': {'defense_review_pending': '', 'defense_review_payload': ''}})
                logging.exception('Defense review message delivery failed')
                await interaction.followup.send('❌ Staff review message could not be delivered. Your submission was safely rolled back; please try again.', ephemeral=True)
                return
            if is_change:
                await interaction.followup.send('📥 **Defense Change Staged:** 5-course lineup sent to staff for audit clearance! Your current defense remains active until the new one is approved.')
            else:
                await interaction.followup.send('📥 **Defense Staged:** 5-course lineup sent to staff for audit clearance!')
        else:
            await interaction.followup.send('❌ Staff review channel is not configured. Ask an administrator to run `/setup`.', ephemeral=True)

async def setup(bot):
    await bot.add_cog(DefenseCog(bot))
