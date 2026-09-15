from discord.ext import commands
from discord import app_commands
from ..core.core import *

class SeasonCog(commands.Cog):
    season_group = app_commands.Group(name="season", description="Manage league seasons.")

    @season_group.command(name='auto', description='Control whether a scheduled season end automatically starts the next season.')
    @app_commands.describe(mode='Choose whether scheduled season endings may automatically roll into the next season')
    @app_commands.choices(mode=[app_commands.Choice(name="Enable automatic season rollover", value="on"), app_commands.Choice(name="Disable automatic season rollover", value="off")])
    @require_admin()
    async def season_auto_cmd(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=True)
        enabled = mode.value == 'on'
        await bot.db.settings.update_one({'_id': str(interaction.guild_id)}, {'$set': {'automatic_season_end': enabled}}, upsert=True)
        status = 'ENABLED' if enabled else 'DISABLED'
        detail = 'When a scheduled season end is reached, the bot will close the current season and immediately start the next season.' if enabled else 'When a scheduled season end is reached, the bot will close the current season, but the next season will wait for staff to schedule and explicitly start it.'
        await interaction.followup.send(f'⚙️ **Automatic Season Rollover: {status}**\n\n{detail}\n\n📅 `/staff` → **Season → Season Schedule** automatically starts and ends seasons at the selected times. `/staff` → **Season → Start Season** may start a season early, but its scheduled end still applies. `/staff` → **Season → End Season** always prevents an immediate automatic rollover to the next season.', ephemeral=True)
        await audit_admin_action(interaction, 'Season Automation', f'Automatic scheduled rollover set to `{enabled}`. Scheduled starts remain manual.')

    @season_group.command(name='schedule', description='Sets custom calendar horizons for active tournament season grids.')
    @app_commands.describe(start_date='Start date mapping (YYYY-MM-DD HH:MM)', end_date='Closing deadline boundary (YYYY-MM-DD HH:MM)')
    @require_admin()
    async def season_schedule_cmd(self, interaction: discord.Interaction, start_date: str, end_date: str):
        await interaction.response.defer(ephemeral=True)
        try:
            config = await bot.db.settings.find_one({'_id': str(interaction.guild_id)})
            tz_name = get_guild_timezone(config)
            local_tz = ZoneInfo(tz_name)
            start_dt = datetime.strptime(start_date.strip(), '%Y-%m-%d %H:%M').replace(tzinfo=local_tz)
            end_dt = datetime.strptime(end_date.strip(), '%Y-%m-%d %H:%M').replace(tzinfo=local_tz)
            if end_dt <= start_dt:
                raise ValueError('end date must be after start date')
            start_timestamp = start_dt.timestamp()
            end_timestamp = end_dt.timestamp()
            now = time.time()
            current_state = await bot.db.season_state.find_one({'_id': f'guild_{interaction.guild_id}'}) or {}
            season_number = int(current_state.get('season_number', 1))
            starts_now = now >= start_timestamp and now < end_timestamp
            await bot.db.season_state.update_one({'_id': f'guild_{interaction.guild_id}'}, {'$set': {'guild_id': str(interaction.guild_id), 'season_number': season_number, 'starts_at': start_timestamp, 'ends_at': end_timestamp, 'season_active': starts_now, 'awaiting_staff_start': not starts_now, **({'started_at': now} if starts_now else {})}, '$unset': {'rollover_lock_at': '', 'rollover_phase': '', 'rollover_season': ''}}, upsert=True)
            if starts_now:
                await announce_season_start(str(interaction.guild_id), season_number, reason='scheduled')
            success_emb = discord.Embed(title='📅 SEASON SCHEDULE SET', color=ASPHALT_VICTORY_COLOR)
            success_emb.description = f'⏱️ **Season {season_number} calendar verified:**\n• **Server Timezone:** `{timezone_label(tz_name)}` (`{tz_name}`)\n• **Automatic Start:** `{start_date}`\n• **Automatic End:** `{end_date}`\n\nThe season will automatically start at the scheduled time and automatically end at the scheduled time. `/staff` → **Season → Season Automation** controls whether the scheduled end immediately rolls into the next season. `/staff` → **Season → Start Season** may start it early, but the scheduled end remains unchanged.'
            await interaction.followup.send(embed=success_emb)
            await dispatch_audit_log(interaction.guild_id, '📅 Timeline Program Updated', f'Season schedule modified manually. Target close entry locks scheduled at: {end_date}', color=ASPHALT_THEME_COLOR)
            await audit_admin_action(interaction, 'Season Schedule', f'Changed season closing time to `{end_date}`.')
        except ValueError:
            await interaction.followup.send('❌ **Timestamp Read Error:** Please verify exact syntax pattern structural formats: `YYYY-MM-DD HH:MM`', ephemeral=True)

    @season_group.command(name='reset', description="Reset this server's season numbering back to Season 1.")
    @app_commands.describe(mode='Choose whether to reset only the season number or clean all pre-launch test season data')
    @app_commands.choices(mode=[app_commands.Choice(name='Season number only', value='counter'), app_commands.Choice(name='Full pre-launch/test reset', value='full')])
    @require_admin()
    async def season_reset_cmd(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        full = mode.value == 'full'
        if full:
            warning = '⚠️ **FULL PRE-LAUNCH/TEST RESET**\n\nThis will return the server to Season 1, delete archived season history, clear pending/challenges/lap-time data, and reset registered drivers to an unregistered Season 1 state with ELO/career counters at zero. This is intended to erase test data before launch.'
        else:
            warning = "⚠️ **RESET SEASON NUMBER**\n\nThis will set the server's current season to **Season 1** and align existing driver records to Season 1. Historical season archives and career statistics will remain."
        await interaction.response.send_message(warning + '\n\nAre you sure?', view=ConfirmSeasonResetView(interaction.guild_id, full), ephemeral=True)

    @season_group.command(name='start', description='Start the scheduled season early; its scheduled end still applies.')
    @require_admin()
    async def season_start_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=True):
            return
        await interaction.response.defer(ephemeral=True)
        gid = str(interaction.guild_id)
        state = await bot.db.season_state.find_one({'_id': f'guild_{gid}'})
        if not state:
            await interaction.followup.send('❌ No season state exists. Open `/staff` → **Season** → **Season Schedule** first.', ephemeral=True)
            return
        if bool(state.get('season_active', True)) and (not bool(state.get('awaiting_staff_start', False))):
            await interaction.followup.send(f"ℹ️ Season {int(state.get('season_number', 1))} is already active.", ephemeral=True)
            return
        start_at = float(state.get('starts_at', 0) or 0)
        end_at = float(state.get('ends_at', 0) or 0)
        if not start_at or not end_at or end_at <= start_at:
            await interaction.followup.send('❌ Set a valid start and end schedule from `/staff` → **Season** → **Season Schedule** before explicitly starting this season.', ephemeral=True)
            return
        now = time.time()
        await bot.db.season_state.update_one({'_id': f'guild_{gid}', 'season_number': int(state.get('season_number', 1))}, {'$set': {'season_active': True, 'awaiting_staff_start': False, 'started_at': now}, '$unset': {'rollover_phase': '', 'rollover_season': ''}})
        season_number = int(state.get('season_number', 1))
        await announce_season_start(gid, season_number, reason='early')
        await interaction.followup.send(f'✅ **Season {season_number} started early.** The "scheduled end time remains unchanged", so the season will still automatically end at the scheduled end time.', ephemeral=True)
        await audit_admin_action(interaction, 'Season Start', f'Explicitly started Season {season_number}.')

    @season_group.command(name='status', description='Show the current season schedule and automation state.')
    @require_admin()
    async def season_status_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=True):
            return
        await interaction.response.defer(ephemeral=True)
        gid = str(interaction.guild_id)
        config = await bot.db.settings.find_one({'_id': gid}) or {}
        state = await bot.db.season_state.find_one({'_id': f'guild_{gid}'})
        if not state:
            await interaction.followup.send('ℹ️ No season state exists yet. Use `/staff` → **Season** to initialize the season.', ephemeral=True)
            return
        season = int(state.get('season_number', 1))
        active = bool(state.get('season_active', False))
        awaiting = bool(state.get('awaiting_staff_start', False))
        auto = bool(config.get('automatic_season_end', False))
        tz_name = get_guild_timezone(config)
        start_at = float(state.get('starts_at', 0) or 0)
        end_at = float(state.get('ends_at', 0) or 0)

        def fmt(ts):
            if not ts:
                return 'Not scheduled'
            return datetime.fromtimestamp(ts, tz=ZoneInfo(tz_name)).strftime('%Y-%m-%d %H:%M %Z')
        status = 'ACTIVE' if active else 'WAITING FOR STAFF START' if awaiting else 'DORMANT'
        detail = f"**Season:** {season}\n**Status:** {status}\n**Scheduled start:** {fmt(start_at)}\n**Scheduled end:** {fmt(end_at)}\n**Automatic scheduled rollover:** {('ON' if auto else 'OFF')}\n\n`/staff` → **Season → Season Schedule** automatically starts and ends the season at the selected times. `/staff` → **Season → Start Season** can open it early and does not change the scheduled end. Automatic rollover only affects a scheduled end; manual `/staff` → **Season → End Season** always leaves the next season waiting for a new schedule."
        await interaction.followup.send(detail, ephemeral=True)

    @season_group.command(name='end', description='Force-closes the season; the next season will not roll over automatically.')
    @require_admin()
    async def season_end_cmd(self, interaction: discord.Interaction):
        if not await enforce_channel_constraints(interaction, admin_cmd=True):
            return
        await interaction.response.send_message('⚠️ **End the current season?** This will archive the standings and prepare the next season. The next season will NOT start automatically; staff must schedule it and use `/staff` → **Season → Start Season**.', view=ConfirmSeasonEndView(interaction.guild_id), ephemeral=True)

    @season_group.command(name='history', description='View archived final standings from completed seasons.')
    @app_commands.describe(season='Season number to view (optional)')
    async def seasonhistory_cmd(self, interaction: discord.Interaction, season: int=None):
        if not await enforce_channel_constraints(interaction, admin_cmd=False):
            return
        guild_id = str(interaction.guild_id)
        if season is not None:
            archive = await bot.db.season_history.find_one({'_id': f'{guild_id}_{int(season)}'})
            if not archive:
                await interaction.response.send_message(f'❌ No archived Season {int(season)} was found.', ephemeral=True)
                return
            rows = archive.get('standings', [])
            lines = []
            for row in rows[:25]:
                lines.append(f"**#{row.get('rank')}** <@{row.get('user_id')}> — **{row.get('elo', 1000)} ELO** — {row.get('division', 'Unranked')}")
            desc = '\n'.join(lines) if lines else '*No archived standings.*'
            if len(rows) > 25:
                desc += f'\n\n…and {len(rows) - 25} more drivers in the archived record.'
            embed = discord.Embed(title=f'🏆 SEASON {int(season)} ARCHIVE', description=desc[:4096], color=ASPHALT_THEME_COLOR)
            embed.set_footer(text=f"Closed {datetime.fromtimestamp(float(archive.get('closed_at', time.time())), tz=timezone.utc).strftime('%Y-%m-%d')}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        archives = await bot.db.season_history.find({'guild_id': guild_id}).sort('season_number', -1).limit(15).to_list(length=15)
        if not archives:
            await interaction.response.send_message('ℹ️ No completed season archives yet.', ephemeral=True)
            return
        lines = [f"🏁 **Season {a.get('season_number')}** — `{a.get('player_count', len(a.get('standings', [])))}` drivers — {datetime.fromtimestamp(float(a.get('closed_at', time.time())), tz=timezone.utc).strftime('%Y-%m-%d')}" for a in archives]
        await interaction.response.send_message(embed=discord.Embed(title='🏆 SEASON ARCHIVES', description='\n'.join(lines), color=ASPHALT_THEME_COLOR), ephemeral=True)

async def setup(bot):
    cog = SeasonCog(bot)
    await bot.add_cog(cog)
    if bot.tree.get_command('season') is None:
        bot.tree.add_command(cog.season_group)
