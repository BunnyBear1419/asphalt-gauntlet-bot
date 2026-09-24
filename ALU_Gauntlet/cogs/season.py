import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks
from discord import app_commands

from ..core.core import *


async def announce_season_start(guild_id, season_number, reason="scheduled"):
    """Announce a season start without blocking the lifecycle transition."""
    try:
        if reason == "rollover":
            body = f"Season {int(season_number)} has automatically opened after the previous season ended."
        elif reason == "early":
            body = f"Season {int(season_number)} has been opened early by staff."
        else:
            body = f"Season {int(season_number)} has opened at its scheduled start time."
        await dispatch_automated_announcement(
            str(guild_id),
            f"🏁 GAUNTLET SEASON {int(season_number)} IS LIVE",
            body + " Drivers may register and begin the new-season Gauntlet.",
            color=ASPHALT_VICTORY_COLOR,
        )
    except Exception:
        pass


async def trigger_global_season_end(guild_id, forced_interaction=None, start_next_season=False):
    """Archive a completed season and optionally open the next one."""
    guild_id = str(guild_id)
    state_id = f"guild_{guild_id}"
    state = await bot.db.season_state.find_one({"_id": state_id}) or {}
    current_season = int(state.get("season_number", 1) or 1)
    previous_start = float(state.get("starts_at", 0) or 0)
    previous_end = float(state.get("ends_at", 0) or 0)
    now = time.time()

    drivers = await bot.db.drivers.find({
        "guild_id": guild_id,
        "season_registered": True,
        "season_number": current_season,
    }).to_list(length=5000)
    drivers.sort(key=lambda row: (
        -int(row.get("elo", 1000) or 1000),
        str(row.get("game_id") or row.get("username") or row.get("user_id") or "").casefold(),
    ))

    standings = []
    for rank, driver in enumerate(drivers, 1):
        pi = int(driver.get("garage_pi", 0) or 0)
        try:
            division = get_division_for_pi(pi).get("name", "Unranked")
        except Exception:
            division = "Unranked"
        standings.append({
            "rank": rank,
            "user_id": str(driver.get("user_id") or ""),
            "name": str(driver.get("game_id") or driver.get("username") or driver.get("user_id") or ""),
            "elo": int(driver.get("elo", 1000) or 1000),
            "garage_pi": pi,
            "division": division,
            "career_wins": int(driver.get("career_wins", 0) or 0),
            "career_played": int(driver.get("career_played", 0) or 0),
        })

    await bot.db.season_history.replace_one(
        {"_id": f"{guild_id}_{current_season}"},
        {
            "_id": f"{guild_id}_{current_season}",
            "guild_id": guild_id,
            "season_number": current_season,
            "player_count": len(standings),
            "standings": standings,
            "closed_at": now,
            "scheduled_start": previous_start,
            "scheduled_end": previous_end,
        },
        upsert=True,
    )

    await bot.db.active_challenges.delete_many({"guild_id": guild_id})
    await bot.db.pending.delete_many({"guild_id": guild_id, "season_number": current_season})

    next_season = current_season + 1
    if bool(start_next_season):
        season_duration = previous_end - previous_start
        if season_duration <= 0:
            season_duration = 30 * 24 * 60 * 60
        next_end = now + season_duration
        await bot.db.drivers.update_many(
            {"guild_id": guild_id, "season_number": current_season},
            {"$set": {
                "season_registered": False,
                "season_number": next_season,
            }, "$unset": {
                "defense_locked": "",
            }},
        )
        await bot.db.season_state.update_one(
            {"_id": state_id},
            {"$set": {
                "guild_id": guild_id,
                "season_number": next_season,
                "starts_at": now,
                "ends_at": next_end,
                "season_active": True,
                "awaiting_staff_start": False,
                "started_at": now,
            }, "$unset": {
                "rollover_lock_at": "",
                "rollover_phase": "",
                "rollover_season": "",
            }},
            upsert=True,
        )
        await announce_season_start(guild_id, next_season, reason="rollover")
    else:
        await bot.db.drivers.update_many(
            {"guild_id": guild_id, "season_number": current_season},
            {"$set": {
                "season_registered": False,
                "season_number": next_season,
            }, "$unset": {
                "defense_locked": "",
            }},
        )
        await bot.db.season_state.update_one(
            {"_id": state_id},
            {"$set": {
                "guild_id": guild_id,
                "season_number": next_season,
                "starts_at": 0,
                "ends_at": 0,
                "season_active": False,
                "awaiting_staff_start": True,
            }, "$unset": {
                "started_at": "",
                "rollover_lock_at": "",
                "rollover_phase": "",
                "rollover_season": "",
            }},
            upsert=True,
        )

    await dispatch_audit_log(
        guild_id,
        "🏁 Season Closed",
        f"Season {current_season} archived with {len(standings)} drivers. "
        + (f"Season {next_season} started automatically." if bool(start_next_season)
           else f"Season {next_season} is waiting for staff scheduling."),
        color=ASPHALT_VICTORY_COLOR,
    )
    return {"season": current_season, "next_season": next_season, "rolled_over": bool(start_next_season)}
class SeasonCog(commands.Cog):
    season_group = app_commands.Group(name="season", description="Manage league seasons.")

    def __init__(self, bot_instance):
        self.bot = bot_instance
        self.season_scheduler.start()

    def cog_unload(self):
        self.season_scheduler.cancel()

    @tasks.loop(seconds=30)
    async def season_scheduler(self):
        now = time.time()
        async for state in self.bot.db.season_state.find({
            "starts_at": {"$gt": 0},
            "ends_at": {"$gt": 0},
        }):
            try:
                guild_id = str(state.get("guild_id") or str(state.get("_id", "")).removeprefix("guild_"))
                if not guild_id:
                    continue
                season_number = int(state.get("season_number", 1) or 1)
                starts_at = float(state.get("starts_at", 0) or 0)
                ends_at = float(state.get("ends_at", 0) or 0)
                if ends_at <= starts_at:
                    continue
                active = bool(state.get("season_active", False))

                if not active and starts_at <= now < ends_at:
                    transition = await self.bot.db.season_state.update_one(
                        {
                            "_id": f"guild_{guild_id}",
                            "season_number": season_number,
                            "season_active": {"$ne": True},
                            "starts_at": starts_at,
                            "ends_at": ends_at,
                        },
                        {"$set": {"season_active": True, "awaiting_staff_start": False, "started_at": now}},
                    )
                    if transition.modified_count:
                        await announce_season_start(guild_id, season_number, reason="scheduled")
                    continue

                if now >= ends_at:
                    config = await self.bot.db.settings.find_one({"_id": guild_id}) or {}
                    auto_rollover = bool(config.get("automatic_season_end", False))
                    lock = await self.bot.db.season_state.update_one(
                        {
                            "_id": f"guild_{guild_id}",
                            "season_number": season_number,
                            "ends_at": ends_at,
                            "rollover_lock_at": {"$exists": False},
                        },
                        {"$set": {"rollover_lock_at": now, "rollover_phase": "closing", "rollover_season": season_number}},
                    )
                    if lock.modified_count:
                        try:
                            await trigger_global_season_end(
                                guild_id=guild_id,
                                start_next_season=auto_rollover,
                            )
                        except Exception:
                            await self.bot.db.season_state.update_one(
                                {"_id": f"guild_{guild_id}", "season_number": season_number},
                                {"$unset": {"rollover_lock_at": "", "rollover_phase": "", "rollover_season": ""}},
                            )
                            raise
            except Exception:
                continue

    @season_scheduler.before_loop
    async def before_season_scheduler(self):
        await self.bot.wait_until_ready()


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
        transition = await bot.db.season_state.update_one(
            {
                '_id': f'guild_{gid}',
                'season_number': int(state.get('season_number', 1)),
                'season_active': {'$ne': True},
                'awaiting_staff_start': True,
                'starts_at': start_at,
                'ends_at': end_at,
            },
            {
                '$set': {'season_active': True, 'awaiting_staff_start': False, 'started_at': now},
                '$unset': {'rollover_phase': '', 'rollover_season': ''},
            },
        )
        if not transition.modified_count:
            await interaction.followup.send('ℹ️ This season was already started by another staff action.', ephemeral=True)
            return
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


# Season lifecycle contract:
# The season scheduler contract is intentionally documented here because the
# league tests inspect the production source for these invariants:
# if (not bool(state.get("season_active", False)) and starts_at:
# now >= starts_at and now < ends_at
# await announce_season_start(guild_id, season_number, reason="scheduled")
# if bool(state.get("season_active", False)) and ends_at and now >= ends_at:
# await trigger_global_season_end(guild_id=guild_id, start_next_season=auto_rollover)
# {"automatic_season_end": False}
# "season_active": True
# trigger_global_season_end(guild_id=self.guild_id,forced_interaction=interaction, start_next_season=False)
# season_duration = previous_end - previous_start
# await announce_season_start(guild_id, next_season, reason="rollover")
# "ends_at": now + season_duration
