import hashlib
from discord.ext import commands
from discord import app_commands
from ..core.core import *

class CompetitionCog(commands.Cog):

    @app_commands.command(name='leaderboard', description='View current-season division standings.')
    async def leaderboard_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        await interaction.response.defer()
        state = await bot.db.season_state.find_one({'_id': f'guild_{interaction.guild_id}'})
        season_number = int(state.get('season_number', 1)) if state else 1
        embed = discord.Embed(title=f'🏆 SEASON {season_number} DIVISION LEADERBOARD', description="Select a division below. Standings are paginated so large divisions never overflow Discord's embed limits.", color=ASPHALT_THEME_COLOR)
        embed.set_image(url=ASPHALT_MEDIA['banner_leaderboard'])
        await interaction.followup.send(embed=embed, view=LeaderboardDivisionView(str(interaction.guild_id)))

    @app_commands.command(name='top', description='View top 5 leaderboards — choose a category.')
    async def top_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        await interaction.response.defer()
        guild_id = str(interaction.guild_id)
        embed = discord.Embed(title='👑 LEADERBOARD SELECTION', description='Choose a leaderboard category from the dropdown below to view the top 5 players.', color=ASPHALT_THEME_COLOR)
        embed.set_thumbnail(url=ASPHALT_MEDIA['thumb_profile'])
        embed.set_footer(text='Select a category below')
        await interaction.followup.send(embed=embed, view=TopLeaderboardView())

    @app_commands.command(name='maps', description='View a Gauntlet map and its two official routes.')
    @app_commands.describe(map_name='Map to view')
    @app_commands.autocomplete(map_name=map_autocomplete)
    async def map_cmd(self, interaction: discord.Interaction, map_name: str):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        await interaction.response.defer(ephemeral=True)
        routes = [t for t in ALU_TRACKS if map_name_from_track(t).lower() == map_name.lower()]
        if not routes:
            await interaction.followup.send('❌ Please choose a map from the map list.', ephemeral=True)
            return
        map_name_only = map_name_from_track(routes[0])
        embed = discord.Embed(title=f'🗺️ {map_name_only}', description='\n'.join((f'🏁 **Route {i + 1}:** `{route}`' for i, route in enumerate(routes))), color=ASPHALT_THEME_COLOR)
        embed.set_footer(text='ALU Gauntlet Map Reference')
        icon_file, icon_filename = map_icon_file(routes[0])
        if icon_file:
            add_map_icon(embed, routes[0], icon_filename)
            await interaction.followup.send(embed=embed, file=icon_file, ephemeral=True)
            return
        preview_file, preview_filename = map_preview_file(routes[0])
        if preview_file:
            add_map_preview(embed, preview_filename)
            await interaction.followup.send(embed=embed, file=preview_file, ephemeral=True)
        else:
            embed.add_field(name='🖼️ Map Image', value='*No supplied map image is available for this map yet.*', inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name='besttime', description="Compare a driver's best saved lap on a map with the universal record.")
    @app_commands.describe(driver='Driver to inspect', map_name='Map/track to inspect')
    @app_commands.autocomplete(map_name=track_autocomplete)
    async def besttime_cmd(self, interaction: discord.Interaction, driver: discord.Member, map_name: str):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        await interaction.response.defer()
        if map_name not in ALU_TRACKS:
            await interaction.followup.send('❌ Please choose a map from the track list.', ephemeral=True)
            return
        await send_driver_best_time(interaction, driver, map_name)

    @app_commands.command(name='reference', description='Show the approved best reference lap and video for a map.')
    @app_commands.describe(map_name='Map/track to inspect')
    @app_commands.autocomplete(map_name=track_autocomplete)
    async def reference_cmd(self, interaction: discord.Interaction, map_name: str):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        await interaction.response.defer()
        if map_name not in ALU_TRACKS:
            await interaction.followup.send('❌ Please choose a map from the track list.', ephemeral=True)
            return
        ref_id = re.sub('[^a-z0-9]+', '_', map_name.lower()).strip('_')
        ref = await bot.db.map_references.find_one({'_id': ref_id})
        embed = discord.Embed(title=f'🎥 Reference Lap — {map_name}', color=ASPHALT_THEME_COLOR)
        if ref:
            embed.description = f"**Best Approved Lap:** `{ref['best_lap_time']}`\n**Video Reference:** {ref['video_url']}\n**Submitted by:** <@{ref['submitted_by']}>"
        else:
            embed.description = '*No approved reference video exists for this map yet.* Open `/gauntlet` → **Tracks & Times** → **Add Reference** to submit one.'
        icon_file, filename = map_icon_file(map_name)
        if icon_file:
            add_map_icon(embed, map_name, filename)
            await interaction.followup.send(embed=embed, file=icon_file)
        else:
            await interaction.followup.send(embed=embed)

    @app_commands.command(name='add_reference', description='Submit a faster map lap video for staff approval.')
    @app_commands.describe(map_name='Map/track', lap_time='Lap time in MM:SS.MS', video_reference='Video URL proving the lap')
    @app_commands.autocomplete(map_name=track_autocomplete)
    async def add_reference_cmd(self, interaction: discord.Interaction, map_name: str, lap_time: str, video_reference: str):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        await interaction.response.defer(ephemeral=True)
        if map_name not in ALU_TRACKS:
            await interaction.followup.send('❌ Please choose a map from the track list.', ephemeral=True)
            return
        ms = parse_lap_time(lap_time)
        if ms <= 0:
            await interaction.followup.send('❌ Lap time must be a positive `MM:SS.MS` value with seconds from 00–59.', ephemeral=True)
            return
        if not video_reference.lower().startswith(('http://', 'https://')):
            await interaction.followup.send('❌ Video reference must be a valid URL.', ephemeral=True)
            return
        ref_id = re.sub('[^a-z0-9]+', '_', map_name.lower()).strip('_')
        current = await bot.db.map_references.find_one({'_id': ref_id})
        if current and ms >= int(current.get('best_ms', 10 ** 18)):
            await interaction.followup.send(f"ℹ️ `{lap_time}` is not faster than the current approved reference `{current['best_lap_time']}`.", ephemeral=True)
            return
        guild_id = str(interaction.guild_id)
        season = await get_current_season_number(guild_id)
        submitter = await bot.db.drivers.find_one({'_id': f'{guild_id}_{interaction.user.id}'})
        if not submitter or not submitter.get('season_registered') or int(submitter.get('season_number', 0)) != season:
            await interaction.followup.send(f'❌ You must be registered for Season {season} before submitting a reference lap.', ephemeral=True)
            return
        cfg = await bot.db.settings.find_one({'_id': guild_id})
        review_chan = bot.get_channel(int(cfg['review_channel_id'])) if cfg and cfg.get('review_channel_id') else None
        if not review_chan:
            await interaction.followup.send('❌ Staff review channel is not configured.', ephemeral=True)
            return
        fingerprint = hashlib.sha256(f'{guild_id}:{interaction.user.id}:{map_name.lower()}:{ms}:{video_reference.strip()}'.encode()).hexdigest()
        existing_submission = await bot.db.reference_pending.find_one({'fingerprint': fingerprint, 'guild_id': guild_id})
        if existing_submission:
            if existing_submission.get('status') == 'pending' and existing_submission.get('review_message_id'):
                await interaction.followup.send('⏳ This exact reference submission is already pending staff review.', ephemeral=True)
                return
            if existing_submission.get('status') == 'approved':
                await interaction.followup.send('ℹ️ This exact reference submission has already been approved.', ephemeral=True)
                return
        submission_id = f'{guild_id}_{interaction.user.id}_{int(time.time() * 1000)}'
        submission = {'_id': submission_id, 'guild_id': guild_id, 'user_id': str(interaction.user.id), 'track': map_name, 'lap_time': lap_time, 'ms': ms, 'video_url': video_reference.strip(), 'status': 'pending', 'submitted_at': time.time(), 'fingerprint': fingerprint}
        try:
            await bot.db.reference_pending.insert_one(submission)
        except DuplicateKeyError:
            existing_submission = await bot.db.reference_pending.find_one({'fingerprint': fingerprint, 'guild_id': guild_id})
            await interaction.followup.send('⏳ This exact reference submission is already pending staff review.', ephemeral=True)
            return
        emb = discord.Embed(title='🎥 New Reference Lap Submission', description=f'<@{interaction.user.id}> submitted a potential new reference for **{map_name}**.\n\n**Lap:** `{lap_time}`\n**Video:** {video_reference}', color=ASPHALT_ADMIN_COLOR)
        if current:
            emb.add_field(name='Current Approved Lap', value=f"`{current['best_lap_time']}`", inline=True)
        try:
            message = await review_chan.send(embed=emb, view=ReferenceReviewView(submission_id))
            await bot.db.reference_pending.update_one({'_id': submission_id, 'status': 'pending'}, {'$set': {'review_channel_id': int(review_chan.id), 'review_message_id': int(message.id)}})
        except Exception:
            await bot.db.reference_pending.delete_one({'_id': submission_id, 'status': 'pending'})
            logging.exception('Reference review message delivery failed')
            await interaction.followup.send('❌ Staff review message could not be delivered. Your submission was safely rolled back; please try again.', ephemeral=True)
            return
        await interaction.followup.send('📥 Reference submitted to staff for approval. If approved, it replaces the current reference for that map.', ephemeral=True)

async def setup(bot):
    await bot.add_cog(CompetitionCog(bot))
