from discord.ext import commands
from discord import app_commands
from ..core.core import *

async def send_admin_dashboard(interaction: discord.Interaction):
    """Open the canonical staff dashboard view for /staff."""
    guild_id = str(interaction.guild_id)
    # StaffDashboardView ownership is per-admin session, not per-guild.
    # Passing guild_id here makes every component interaction fail its owner check.
    view = StaffDashboardView(str(interaction.user.id))
    embed = discord.Embed(
        title='🛠️ RACING SYNDICATE LEAGUE • STAFF CONTROL CENTER',
        description='Manage players, seasons, defenses, setup, diagnostics, backups, and league operations from the staff dashboard below.',
        color=ASPHALT_ADMIN_COLOR,
    )
    embed.set_footer(text='Staff controls • Staff permissions required')
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class StaffCog(commands.Cog):

    @app_commands.command(name='missingdefense', description='[Staff Only] List current-season drivers without a locked defense.')
    async def missing_defense_cmd(self, interaction: discord.Interaction):
        if not await check_admin_privileges(interaction):
            await interaction.response.send_message('❌ Staff only.', ephemeral=True)
            return
        guild_id = str(interaction.guild_id)
        season = await get_current_season_number(guild_id)
        docs = await bot.db.drivers.find({'guild_id': guild_id, 'season_registered': True, 'season_number': season, 'defense_locked.courses.4': {'$exists': False}}).to_list(length=1000)
        lines = [f"• <@{d['user_id']}> — `{d.get('game_id', '?')}`" for d in docs]
        embed = discord.Embed(title=f'🛡️ MISSING DEFENSE — SEASON {season}', description='\n'.join(lines) if lines else '✅ Everyone has a locked defense.', color=ASPHALT_ADMIN_COLOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name='adminlog', description='[Staff Only] View recent administrative audit entries.')
    @app_commands.describe(limit='Number of recent log entries to show (1-15)')
    async def adminlog_cmd(self, interaction: discord.Interaction, limit: int=10):
        if not await check_admin_privileges(interaction):
            await interaction.response.send_message('❌ Staff only.', ephemeral=True)
            return
        limit = max(1, min(15, limit))
        cfg = await bot.db.settings.find_one({'_id': str(interaction.guild_id)})
        if not cfg or not cfg.get('log_channel_id'):
            await interaction.response.send_message('ℹ️ Log channel is not configured.', ephemeral=True)
            return
        ch = bot.get_channel(int(cfg['log_channel_id']))
        if not ch:
            await interaction.response.send_message('❌ Log channel could not be found.', ephemeral=True)
            return
        messages = []
        try:
            async for m in ch.history(limit=limit):
                if m.embeds:
                    e = m.embeds[0]
                    messages.append(f"• **{e.title or 'Log'}** — {(e.description or '')[:180]}")
        except Exception as exc:
            await interaction.response.send_message(f'❌ Could not read audit log: `{exc}`', ephemeral=True)
            return
        embed = discord.Embed(title='🛡️ RECENT ADMIN LOG', description='\n\n'.join(messages) if messages else 'No recent audit entries found.', color=ASPHALT_ADMIN_COLOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.guild_only()
    @app_commands.command(name='staff', description='[Staff Only] Open the Racing Syndicate League staff control center.')
    async def staff_dashboard_cmd(self, interaction: discord.Interaction):
        if not await check_admin_privileges(interaction):
            await interaction.response.send_message('❌ Staff only.', ephemeral=True)
            return
        await send_admin_dashboard(interaction)

    @app_commands.command(name='pending', description='[Staff Only] Show all drivers awaiting current-season approval.')
    async def pending_cmd(self, interaction: discord.Interaction):
        if not await check_admin_privileges(interaction):
            await interaction.response.send_message('❌ Access Denied: Staff only.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        season = await get_current_season_number(guild_id)
        rows = await bot.db.pending.find({'guild_id': guild_id, 'season_number': season}).to_list(length=1000)
        if not rows:
            await interaction.followup.send(f'✅ No pending driver registrations for Season {season}.', ephemeral=True)
            return
        lines = [f"<@{d['user_id']}> — `{d.get('game_id', '?')}` — `{int(d.get('rank', 0)):,} PI` → **{get_division_for_pi(int(d.get('rank', 0)))['name']}**" for d in rows]
        await interaction.followup.send(embed=discord.Embed(title=f'⏳ PENDING DRIVERS — SEASON {season}', description='\n'.join(lines)[:4096], color=ASPHALT_ALERT_COLOR), ephemeral=True)
        await audit_admin_action(interaction, 'Pending Drivers', f'Viewed {len(rows)} pending Season {season} registration(s).')

    @app_commands.command(name='listplayers', description='[Staff Only] List every driver registered in this server with ELO and division.')
    @app_commands.describe(page='Page number')
    async def listplayers_cmd(self, interaction: discord.Interaction, page: int=1):
        if not await check_admin_privileges(interaction):
            await interaction.response.send_message('❌ Access Denied: Staff only.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        page = max(1, page)
        guild_id = str(interaction.guild_id)
        season = await get_current_season_number(guild_id)
        query = {'guild_id': guild_id, 'season_registered': True, 'season_number': season}
        total = await bot.db.drivers.count_documents(query)
        per_page = 20
        pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, pages)
        drivers = await bot.db.drivers.find(query).sort('elo', -1).skip((page - 1) * per_page).limit(per_page).to_list(length=per_page)
        lines = [f"**#{i}** <@{d['user_id']}> — `{d.get('game_id', '?')}` — **{d.get('elo', 1000)} ELO** — `{d.get('garage_pi', 0):,} PI` — {get_division_for_pi(int(d.get('garage_pi', 0)))['name']}" for i, d in enumerate(drivers, start=(page - 1) * per_page + 1)]
        embed = discord.Embed(title=f'📋 REGISTERED PLAYERS — SEASON {season}', description='\n'.join(lines) if lines else '*No registered drivers.*', color=ASPHALT_ADMIN_COLOR)
        embed.set_footer(text=f'Page {page}/{pages} • {total} total registered drivers')
        await interaction.followup.send(embed=embed, ephemeral=True)
        await audit_admin_action(interaction, 'List Players', f'Viewed registered player list page {page}/{pages}.')

    @app_commands.command(name='clearhistory', description='[Staff Only] Wipes selected league data or resets the guild league state.')
    @app_commands.choices(target_data=[app_commands.Choice(name='Pending Queue Only', value='pending'), app_commands.Choice(name='Approved Drivers Only', value='drivers'), app_commands.Choice(name='Reset Everything', value='all')])
    async def clear_history_cmd(self, interaction: discord.Interaction, target_data: app_commands.Choice[str]):
        if not await enforce_channel_constraints(interaction, admin_cmd=True) or not await check_admin_privileges(interaction):
            return
        await interaction.response.send_message(f'⚠️ **Confirm purge:** `{target_data.name}`. This action can delete league data and cannot be undone.', view=ConfirmClearHistoryView(interaction.guild_id, target_data.value), ephemeral=True)

    @app_commands.command(name='dbcheck', description='[Staff Only] Audits database consistency and recoverable settlement states.')
    async def dbcheck_cmd(self, interaction: discord.Interaction):
        if not await check_admin_privileges(interaction):
            await interaction.response.send_message('❌ Access Denied: Admin authorization required.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild.id) if interaction.guild else None
        if not guild_id:
            await interaction.followup.send('❌ This command must be used inside a server.', ephemeral=True)
            return
        issues = []
        checks = []
        try:
            existing_collections = set(await bot.db.list_collection_names())
            missing_collections = sorted(set(REQUIRED_COLLECTIONS) - existing_collections)
            if missing_collections:
                issues.append('Missing required collections: ' + ', '.join(missing_collections))
            else:
                checks.append(f'Required collections verified: {len(REQUIRED_COLLECTIONS)}')
            index_expectations = {
                'lap_time_history': 'match_id_1',
                'system_events': 'guild_id_1_timestamp_-1',
            }
            for coll_name, index_name in index_expectations.items():
                names = set((await bot.db[coll_name].index_information()).keys())
                if index_name not in names:
                    issues.append(f'{coll_name} missing index {index_name}')
                else:
                    checks.append(f'{coll_name}.{index_name} verified')
        except Exception as exc:
            issues.append(f'Schema/index verification failed: {str(exc)[:180]}')
        try:
            drivers = await bot.db.drivers.find({'guild_id': guild_id}).to_list(length=5000)
            checks.append(f'Drivers scanned: {len(drivers)}')
            seen_ids = set()
            for d in drivers:
                if d.get('_id') in seen_ids:
                    issues.append(f"Duplicate driver id: {d.get('_id')}")
                seen_ids.add(d.get('_id'))
                elo = d.get('elo', 1000)
                pi = d.get('garage_pi')
                if not isinstance(elo, (int, float)) or elo < 100:
                    issues.append(f"Invalid ELO: {d.get('_id')} = {elo}")
                if pi is not None and (not isinstance(pi, (int, float)) or pi < 0):
                    issues.append(f"Invalid PI: {d.get('_id')} = {pi}")
            active = await bot.db.active_challenges.find({'guild_id': guild_id, 'status': {'$in': ['active', 'processing']}}).to_list(length=5000)
            checks.append(f'Unfinished challenges scanned: {len(active)}')
            by_challenger = {}
            for ch in active:
                by_challenger.setdefault(ch.get('challenger_id'), []).append(ch)
                if not ch.get('opponent_id'):
                    issues.append(f"Challenge missing opponent: {ch.get('_id')}")
                if ch.get('status') == 'active' and ch.get('expires_at') and (float(ch.get('expires_at', 0)) <= time.time()):
                    issues.append(f"Expired active challenge: {ch.get('_id')}")
                if ch.get('status') in {'active', 'processing'} and int(ch.get('season_number', 0)) <= 0:
                    issues.append(f"Challenge missing season number: {ch.get('_id')}")
                if ch.get('status') == 'processing' and ch.get('processing_at'):
                    age = time.time() - float(ch.get('processing_at', time.time()))
                    if age > 15 * 60:
                        issues.append(f"Stale processing challenge: {ch.get('_id')} ({int(age / 60)}m)")
            for uid, rows in by_challenger.items():
                if len(rows) > 1:
                    issues.append(f'Multiple unfinished challenges for {uid}: {len(rows)}')
            matches = await bot.db.matches.find({'guild_id': guild_id}).to_list(length=5000)
            checks.append(f'Match settlements scanned: {len(matches)}')
            for m in matches:
                status = m.get('settlement_status')
                if status == 'pending':
                    issues.append(f"Pending settlement requires recovery review: {m.get('_id')}")
                    continue
                if status == 'completed' and m.get('challenger_elo_after') is not None and (m.get('defender_elo_after') is not None):
                    c = await bot.db.drivers.find_one({'_id': f"{guild_id}_{m.get('challenger_id')}"})
                    d = await bot.db.drivers.find_one({'_id': f"{guild_id}_{m.get('opponent_id')}"})
                    if c and d:
                        pass
                    elif not c or not d:
                        issues.append(f"Completed match references missing driver(s): {m.get('_id')}")
            # Cross-collection duplicate/orphan audit. Read-only: no repair mutations are made here.
            async def duplicate_groups(collection, key_fields, label, extra_match=None):
                match_filter = {'guild_id': guild_id}
                if extra_match:
                    match_filter.update(extra_match)
                pipeline = [
                    {'$match': match_filter},
                    {'$group': {'_id': {k: '
                rows = await collection.aggregate(pipeline).to_list(length=20)
                if rows:
                    issues.append(f'{label}: {len(rows)} duplicate key group(s)')
                else:
                    checks.append(f'{label}: 0 duplicates')
                return rows

            await duplicate_groups(bot.db.club_members, ['club_id', 'user_id'], 'Duplicate club memberships')
            await duplicate_groups(bot.db.tournament_club_registrations, ['tournament_id', 'club_id'], 'Duplicate tournament registrations')
            await duplicate_groups(bot.db.matches, ['settlement_id'], 'Duplicate match settlements', {'settlement_id': {'$exists': True, '$ne': None}})
            await duplicate_groups(bot.db.drivers, ['user_id'], 'Duplicate driver identities')

            verified_game_ids = await bot.db.web_preferences.aggregate([
                {'$match': {'guild_id': guild_id, 'asphalt_connection.status': 'verified'}},
                {'$group': {'_id': '$asphalt_connection.game_id', 'count': {'$sum': 1}}},
                {'$match': {'count': {'$gt': 1}}},
                {'$limit': 20},
            ]).to_list(length=20)
            if verified_game_ids:
                issues.append(f'Duplicate verified Asphalt IDs: {len(verified_game_ids)}')
            else:
                checks.append('Duplicate verified Asphalt IDs: 0')

            club_ids = {str(x.get('_id')) for x in await bot.db.clubs.find({'guild_id': guild_id}, {'_id': 1}).to_list(length=5000)}
            memberships = await bot.db.club_members.find({'guild_id': guild_id}, {'_id': 1, 'club_id': 1}).to_list(length=5000)
            orphan_memberships = [x for x in memberships if str(x.get('club_id')) not in club_ids]
            checks.append(f'Orphaned club memberships: {len(orphan_memberships)}')
            if orphan_memberships:
                issues.append(f'Orphaned club memberships: {len(orphan_memberships)}')

            tournament_ids = {str(x.get('_id')) for x in await bot.db.tournaments.find({'guild_id': guild_id}, {'_id': 1}).to_list(length=5000)}
            registrations = await bot.db.tournament_club_registrations.find({'guild_id': guild_id}, {'_id': 1, 'tournament_id': 1, 'club_id': 1}).to_list(length=5000)
            orphan_regs = [x for x in registrations if str(x.get('tournament_id')) not in tournament_ids or str(x.get('club_id')) not in club_ids]
            checks.append(f'Orphaned tournament registrations: {len(orphan_regs)}')
            if orphan_regs:
                issues.append(f'Orphaned tournament registrations: {len(orphan_regs)}')

            driver_ids = {str(x.get('_id')) for x in drivers}
            referenced_driver_ids = set()
            for m in matches:
                for field in ('challenger_id', 'opponent_id', 'winner_id', 'w_id'):
                    value = m.get(field)
                    if value:
                        referenced_driver_ids.add(f'{guild_id}_{value}' if '_' not in str(value) else str(value))
            missing_match_drivers = sorted(x for x in referenced_driver_ids if x not in driver_ids)
            checks.append(f'Match references to missing drivers: {len(missing_match_drivers)}')
            if missing_match_drivers:
                issues.append(f'Matches reference missing drivers: {len(missing_match_drivers)}')

            tournament_docs = await bot.db.tournaments.find({'guild_id': guild_id}, {'_id': 1, 'club_id': 1, 'club_ids': 1}).to_list(length=5000)
            missing_tournament_clubs = 0
            for t in tournament_docs:
                refs = []
                if t.get('club_id'):
                    refs.append(t.get('club_id'))
                refs.extend(t.get('club_ids') or [])
                missing_tournament_clubs += sum(1 for cid in refs if str(cid) not in club_ids)
            checks.append(f'Tournament references to missing clubs: {missing_tournament_clubs}')
            if missing_tournament_clubs:
                issues.append(f'Tournaments reference missing clubs: {missing_tournament_clubs}')
            completed_matches = [m for m in matches if m.get('settlement_status') == 'completed' and not m.get('reverted')]
            match_counts = {}
            win_counts = {}
            for m in completed_matches:
                for uid in (m.get('challenger_id'), m.get('opponent_id')):
                    if uid:
                        match_counts[uid] = match_counts.get(uid, 0) + 1
                winner = m.get('w_id')
                if winner:
                    win_counts[winner] = win_counts.get(winner, 0) + 1
                if m.get('challenger_elo_after') is not None and m.get('defender_elo_after') is not None:
                    if m.get('challenger_elo_after') < 100 or m.get('defender_elo_after') < 100:
                        issues.append(f"Completed match has invalid post-match ELO: {m.get('_id')}")
            for d in drivers:
                uid = str(d.get('user_id'))
                played = int(d.get('career_played', 0) or 0)
                wins = int(d.get('career_wins', 0) or 0)
                if played < match_counts.get(uid, 0):
                    issues.append(f"Career played is below match history for {d.get('_id')}: {played} < {match_counts.get(uid, 0)}")
                if wins < win_counts.get(uid, 0):
                    issues.append(f"Career wins are below match history for {d.get('_id')}: {wins} < {win_counts.get(uid, 0)}")
                if wins > played:
                    issues.append(f"Career wins exceed career played for {d.get('_id')}: {wins} > {played}")
                if d.get('defense_review_pending') and not d.get('defense_review_payload'):
                    issues.append(f"Defense review flag has no payload: {d.get('_id')}")
            # Universal record integrity: every stored record must point to a real track
            # and have a positive time.
            global_records = await bot.db.map_records.find({}).to_list(length=5000)
            checks.append(f'Universal records scanned: {len(global_records)}')
            for rec in global_records:
                if rec.get('track') not in ALU_TRACKS or int(rec.get('best_ms', 0) or 0) <= 0:
                    issues.append(f"Invalid universal record: {rec.get('_id')}")
            status_line = '✅ DATABASE CONSISTENT' if not issues else f'⚠️ {len(issues)} ISSUE(S) FOUND'
            embed = discord.Embed(title='🗄️ RACING SYNDICATE LEAGUE — DATABASE CHECK', description=status_line, color=ASPHALT_VICTORY_COLOR if not issues else ASPHALT_ADMIN_COLOR, timestamp=datetime.now(timezone.utc))
            embed.add_field(name='Checks', value='\n'.join((f'• {x}' for x in checks)) or '• No records found', inline=False)
            if issues:
                preview = '\n'.join((f'• {x}' for x in issues[:20]))
                if len(issues) > 20:
                    preview += f'\n• …and {len(issues) - 20} more'
                embed.add_field(name='Issues / Recovery Review', value=preview[:1024], inline=False)
            else:
                embed.add_field(name='Recovery Test', value='• Settlement reservations and challenge locks passed structural checks.\n• No automatic mutations were made.', inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
            await audit_admin_action(interaction, 'DBCheck', f'Database consistency audit: {len(issues)} issue(s).')
        except Exception as exc:
            logging.exception('Database consistency check failed', exc_info=exc)
            await interaction.followup.send(f'❌ Database consistency check failed: `{exc}`', ephemeral=True)

    @app_commands.command(name='backup', description='[Staff Only] Create an immediate database backup.')
    async def backup_cmd(self, interaction: discord.Interaction):
        if not await check_admin_privileges(interaction):
            await interaction.response.send_message('❌ Staff only.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            folder = await create_database_backup(f'manual by {interaction.user.id}')
            if folder:
                await interaction.followup.send(f'✅ Database backup created.\n`{folder}`', ephemeral=True)
                await audit_admin_action(interaction, 'Database Backup', f'Created backup `{folder}`.')
            else:
                await interaction.followup.send('ℹ️ MongoDB is not connected; no cloud database backup was created.', ephemeral=True)
        except Exception as exc:
            logging.exception('Manual database backup failed')
            await interaction.followup.send(f'❌ Backup failed: `{exc}`', ephemeral=True)
            await send_admin_alert(str(interaction.guild_id), 'DATABASE BACKUP FAILED', str(exc))

    @app_commands.command(name='diagnostics', description='[Staff Only] Run a read-only health and database diagnostic report.')
    async def diagnostics_cmd(self, interaction: discord.Interaction):
        if not await check_admin_privileges(interaction):
            await interaction.response.send_message('❌ Staff only.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        now = time.time()
        uptime_seconds = max(0, int(now - getattr(bot, 'started_at', now)))

        def fmt_uptime(seconds: int) -> str:
            days, rem = divmod(seconds, 86400)
            hours, rem = divmod(rem, 3600)
            minutes, secs = divmod(rem, 60)
            parts = []
            if days:
                parts.append(f'{days}d')
            if hours or days:
                parts.append(f'{hours}h')
            if minutes or hours or days:
                parts.append(f'{minutes}m')
            parts.append(f'{secs}s')
            return ' '.join(parts)

        def task_status(task_obj) -> str:
            if task_obj is None:
                return '⚪ Not initialized'
            try:
                if task_obj.is_running():
                    return '🟢 Running'
                if task_obj.is_being_cancelled():
                    return '🟡 Stopping'
                if task_obj.failed():
                    return '🔴 Failed'
            except Exception:
                pass
            return '⚪ Stopped'
        runtime = []
        counts = {}
        integrity = []
        mongo_ok = False
        latency = bot.latency
        latency_text = f'{round(latency * 1000, 1)}ms' if latency != float('inf') else 'N/A'
        runtime.append(('Gateway', f'🟢 Online • {latency_text}'))
        runtime.append(('Uptime', f'🟢 {fmt_uptime(uptime_seconds)}'))
        runtime.append(('Commands', f'🟢 {len(bot.tree.get_commands())} loaded'))
        runtime.append(('Python', f'`{sys.version.split()[0]}`'))
        runtime.append(('Host', f'`{platform.system()}`'))
        try:
            if bot.mongo_client:
                started = time.perf_counter()
                await bot.mongo_client.admin.command('ping')
                mongo_ms = round((time.perf_counter() - started) * 1000, 1)
                mongo_ok = True
                runtime.append(('MongoDB', f'🟢 Connected • {mongo_ms}ms'))
                for name in ('drivers', 'pending', 'matches', 'active_challenges', 'season_history', 'reference_pending'):
                    try:
                        counts[name] = await getattr(bot.db, name).count_documents({})
                    except Exception:
                        counts[name] = '?'
                try:
                    meta = await bot.db.settings.find_one({'_id': 'global_meta'})
                    if meta and meta.get('guild_overrides_cleaned'):
                        runtime.append(('Guild Command Overrides', '🟢 Cleared (cached — skipped on future boots)'))
                    else:
                        runtime.append(('Guild Command Overrides', '🟡 Not yet cleared — will run on next boot, or use `/staff` → **System → Sync Commands** with full cleanup if needed'))
                except Exception:
                    runtime.append(('Guild Command Overrides', '🔴 Could not check status'))
            else:
                runtime.append(('MongoDB', '🔴 Not connected • mock DB active'))
        except Exception as exc:
            runtime.append(('MongoDB', f'🔴 Error • {str(exc)[:160]}'))
        season_text = 'Unavailable'
        queue_text = 'Unavailable'
        if mongo_ok:
            try:
                state = await bot.db.season_state.find_one({'_id': f'guild_{guild_id}'})
                season = int(state.get('season_number', 1)) if state else 1
                registered = await bot.db.drivers.count_documents({'guild_id': guild_id, 'season_registered': True, 'season_number': season})
                pending = await bot.db.pending.count_documents({'guild_id': guild_id, 'season_number': season})
                active = await bot.db.active_challenges.count_documents({'guild_id': guild_id, 'status': {'$in': ['active', 'processing']}})
                stale = await bot.db.active_challenges.count_documents({'guild_id': guild_id, 'status': 'processing', 'processing_at': {'$lt': now - 900}})
                pending_settlements = await bot.db.matches.count_documents({'guild_id': guild_id, 'settlement_status': 'pending'})
                bad_elo = await bot.db.drivers.count_documents({'guild_id': guild_id, '$or': [{'elo': {'$lt': 0}}, {'elo': {'$gt': 10000}}]})
                bad_pi = await bot.db.drivers.count_documents({'guild_id': guild_id, '$or': [{'garage_pi': {'$lt': 0}}, {'garage_pi': {'$gt': 100000}}]})
                season_text = f'Season {season} • {registered} registered'
                queue_text = f'{active} active/processing • {pending} pending'
                if stale:
                    integrity.append(f'⚠️ Stale processing challenges: `{stale}`')
                if pending_settlements:
                    integrity.append(f'⚠️ Pending settlements: `{pending_settlements}`')
                if bad_elo:
                    integrity.append(f'⚠️ Invalid ELO records: `{bad_elo}`')
                if bad_pi:
                    integrity.append(f'⚠️ Invalid PI records: `{bad_pi}`')
                if not integrity:
                    integrity.append('🟢 No obvious integrity issues found')
            except Exception as exc:
                integrity.append(f'🔴 Integrity check failed: {str(exc)[:160]}')
        else:
            integrity.append('🔴 Database integrity checks skipped — MongoDB unavailable')
        task_lines = [f"**Season Clock:** {task_status(getattr(bot, 'seasonal_clock_loop', None))}", f"**Player Reminders:** {task_status(getattr(bot, 'player_reminder_loop', None))}", f"**Backups:** {task_status(getattr(bot, 'backup_loop', None))}"]
        backup_root = os.getenv('BACKUP_DIR', './backups')
        backup_text = '⚪ No local backup directory'
        try:
            if os.path.isdir(backup_root):
                folders = [os.path.join(backup_root, x) for x in os.listdir(backup_root) if os.path.isdir(os.path.join(backup_root, x))]
                folders.sort(key=lambda x: os.path.getmtime(x), reverse=True)
                if folders:
                    age_hours = max(0, (now - os.path.getmtime(folders[0])) / 3600)
                    status = '🟢' if age_hours <= 30 else '🟡' if age_hours <= 48 else '🔴'
                    backup_text = f'{status} {len(folders)} local • latest {age_hours:.1f}h ago'
                else:
                    backup_text = '🔴 No local backups found'
        except Exception as exc:
            backup_text = f'🔴 Check failed • {str(exc)[:100]}'
        embed = discord.Embed(title='🛠️ RACING SYNDICATE LEAGUE — DIAGNOSTICS', description='Read-only system, database, task, and backup health check.', color=ASPHALT_ADMIN_COLOR if mongo_ok else ASPHALT_ALERT_COLOR, timestamp=datetime.now(timezone.utc))
        embed.set_thumbnail(url=ASPHALT_MEDIA['thumb_diagnostics'])
        embed.add_field(name='🖥️ Runtime', value='\n'.join((f'**{k}:** {v}' for k, v in runtime)), inline=False)
        embed.add_field(name='🗄️ Database', value='\n'.join([f"**Drivers:** `{counts.get('drivers', '?')}`", f"**Pending:** `{counts.get('pending', '?')}`", f"**Matches:** `{counts.get('matches', '?')}`", f"**Challenges:** `{counts.get('active_challenges', '?')}`", f"**Season Archives:** `{counts.get('season_history', '?')}`", f"**Reference Queue:** `{counts.get('reference_pending', '?')}`"]), inline=True)
        embed.add_field(name='⚙️ Tasks & Backups', value='\n'.join(task_lines) + f'\n**Local Backups:** {backup_text}', inline=True)
        embed.add_field(name='🏁 League', value=f'**Current:** {season_text}\n**Queue:** {queue_text}', inline=False)
        embed.add_field(name='🔍 Integrity', value='\n'.join(integrity)[:1024], inline=False)
        embed.set_footer(text='Read-only • `/staff` → **Data → Database Check** = full audit • `/staff` → **Data → Backup** = manual backup')
        await interaction.followup.send(embed=embed, ephemeral=True)
        await audit_admin_action(interaction, 'Diagnostics', 'Ran read-only system, database, task, and backup diagnostics.')

    @app_commands.command(name='launchcheck', description='[Staff Only] Run a read-only Racing Syndicate League production readiness check.')
    async def launchcheck_cmd(self, interaction: discord.Interaction):
        if not await check_admin_privileges(interaction):
            await interaction.response.send_message('⛔ Staff only.', ephemeral=True)
            return
        await send_launch_readiness(interaction)
        await record_system_event(str(interaction.guild_id), 'LAUNCH_CHECK', f'Launch readiness check requested by {interaction.user.id}')

async def setup(bot):
    await bot.add_cog(StaffCog(bot))
 + k for k in key_fields}, 'count': {'$sum': 1}}},
                    {'$match': {'count': {'$gt': 1}}},
                    {'$limit': 20},
                ]
                rows = await collection.aggregate(pipeline).to_list(length=20)
                if rows:
                    issues.append(f'{label}: {len(rows)} duplicate key group(s)')
                else:
                    checks.append(f'{label}: 0 duplicates')
                return rows

            await duplicate_groups(bot.db.club_members, ['club_id', 'user_id'], 'Duplicate club memberships')
            await duplicate_groups(bot.db.tournament_club_registrations, ['tournament_id', 'club_id'], 'Duplicate tournament registrations')
            await duplicate_groups(bot.db.matches, ['settlement_id'], 'Duplicate match settlements')
            await duplicate_groups(bot.db.drivers, ['user_id'], 'Duplicate driver identities')

            verified_game_ids = await bot.db.web_preferences.aggregate([
                {'$match': {'guild_id': guild_id, 'asphalt_connection.status': 'verified'}},
                {'$group': {'_id': '$asphalt_connection.game_id', 'count': {'$sum': 1}}},
                {'$match': {'count': {'$gt': 1}}},
                {'$limit': 20},
            ]).to_list(length=20)
            if verified_game_ids:
                issues.append(f'Duplicate verified Asphalt IDs: {len(verified_game_ids)}')
            else:
                checks.append('Duplicate verified Asphalt IDs: 0')

            club_ids = {str(x.get('_id')) for x in await bot.db.clubs.find({'guild_id': guild_id}, {'_id': 1}).to_list(length=5000)}
            memberships = await bot.db.club_members.find({'guild_id': guild_id}, {'_id': 1, 'club_id': 1}).to_list(length=5000)
            orphan_memberships = [x for x in memberships if str(x.get('club_id')) not in club_ids]
            checks.append(f'Orphaned club memberships: {len(orphan_memberships)}')
            if orphan_memberships:
                issues.append(f'Orphaned club memberships: {len(orphan_memberships)}')

            tournament_ids = {str(x.get('_id')) for x in await bot.db.tournaments.find({'guild_id': guild_id}, {'_id': 1}).to_list(length=5000)}
            registrations = await bot.db.tournament_club_registrations.find({'guild_id': guild_id}, {'_id': 1, 'tournament_id': 1, 'club_id': 1}).to_list(length=5000)
            orphan_regs = [x for x in registrations if str(x.get('tournament_id')) not in tournament_ids or str(x.get('club_id')) not in club_ids]
            checks.append(f'Orphaned tournament registrations: {len(orphan_regs)}')
            if orphan_regs:
                issues.append(f'Orphaned tournament registrations: {len(orphan_regs)}')

            driver_ids = {str(x.get('_id')) for x in drivers}
            referenced_driver_ids = set()
            for m in matches:
                for field in ('challenger_id', 'opponent_id', 'winner_id', 'w_id'):
                    value = m.get(field)
                    if value:
                        referenced_driver_ids.add(f'{guild_id}_{value}' if '_' not in str(value) else str(value))
            missing_match_drivers = sorted(x for x in referenced_driver_ids if x not in driver_ids)
            checks.append(f'Match references to missing drivers: {len(missing_match_drivers)}')
            if missing_match_drivers:
                issues.append(f'Matches reference missing drivers: {len(missing_match_drivers)}')

            tournament_docs = await bot.db.tournaments.find({'guild_id': guild_id}, {'_id': 1, 'club_id': 1, 'club_ids': 1}).to_list(length=5000)
            missing_tournament_clubs = 0
            for t in tournament_docs:
                refs = []
                if t.get('club_id'):
                    refs.append(t.get('club_id'))
                refs.extend(t.get('club_ids') or [])
                missing_tournament_clubs += sum(1 for cid in refs if str(cid) not in club_ids)
            checks.append(f'Tournament references to missing clubs: {missing_tournament_clubs}')
            if missing_tournament_clubs:
                issues.append(f'Tournaments reference missing clubs: {missing_tournament_clubs}')
            completed_matches = [m for m in matches if m.get('settlement_status') == 'completed' and not m.get('reverted')]
            match_counts = {}
            win_counts = {}
            for m in completed_matches:
                for uid in (m.get('challenger_id'), m.get('opponent_id')):
                    if uid:
                        match_counts[uid] = match_counts.get(uid, 0) + 1
                winner = m.get('w_id')
                if winner:
                    win_counts[winner] = win_counts.get(winner, 0) + 1
                if m.get('challenger_elo_after') is not None and m.get('defender_elo_after') is not None:
                    if m.get('challenger_elo_after') < 100 or m.get('defender_elo_after') < 100:
                        issues.append(f"Completed match has invalid post-match ELO: {m.get('_id')}")
            for d in drivers:
                uid = str(d.get('user_id'))
                played = int(d.get('career_played', 0) or 0)
                wins = int(d.get('career_wins', 0) or 0)
                if played < match_counts.get(uid, 0):
                    issues.append(f"Career played is below match history for {d.get('_id')}: {played} < {match_counts.get(uid, 0)}")
                if wins < win_counts.get(uid, 0):
                    issues.append(f"Career wins are below match history for {d.get('_id')}: {wins} < {win_counts.get(uid, 0)}")
                if wins > played:
                    issues.append(f"Career wins exceed career played for {d.get('_id')}: {wins} > {played}")
                if d.get('defense_review_pending') and not d.get('defense_review_payload'):
                    issues.append(f"Defense review flag has no payload: {d.get('_id')}")
            # Universal record integrity: every stored record must point to a real track
            # and have a positive time.
            global_records = await bot.db.map_records.find({}).to_list(length=5000)
            checks.append(f'Universal records scanned: {len(global_records)}')
            for rec in global_records:
                if rec.get('track') not in ALU_TRACKS or int(rec.get('best_ms', 0) or 0) <= 0:
                    issues.append(f"Invalid universal record: {rec.get('_id')}")
            status_line = '✅ DATABASE CONSISTENT' if not issues else f'⚠️ {len(issues)} ISSUE(S) FOUND'
            embed = discord.Embed(title='🗄️ RACING SYNDICATE LEAGUE — DATABASE CHECK', description=status_line, color=ASPHALT_VICTORY_COLOR if not issues else ASPHALT_ADMIN_COLOR, timestamp=datetime.now(timezone.utc))
            embed.add_field(name='Checks', value='\n'.join((f'• {x}' for x in checks)) or '• No records found', inline=False)
            if issues:
                preview = '\n'.join((f'• {x}' for x in issues[:20]))
                if len(issues) > 20:
                    preview += f'\n• …and {len(issues) - 20} more'
                embed.add_field(name='Issues / Recovery Review', value=preview[:1024], inline=False)
            else:
                embed.add_field(name='Recovery Test', value='• Settlement reservations and challenge locks passed structural checks.\n• No automatic mutations were made.', inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
            await audit_admin_action(interaction, 'DBCheck', f'Database consistency audit: {len(issues)} issue(s).')
        except Exception as exc:
            logging.exception('Database consistency check failed', exc_info=exc)
            await interaction.followup.send(f'❌ Database consistency check failed: `{exc}`', ephemeral=True)

    @app_commands.command(name='backup', description='[Staff Only] Create an immediate database backup.')
    async def backup_cmd(self, interaction: discord.Interaction):
        if not await check_admin_privileges(interaction):
            await interaction.response.send_message('❌ Staff only.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            folder = await create_database_backup(f'manual by {interaction.user.id}')
            if folder:
                await interaction.followup.send(f'✅ Database backup created.\n`{folder}`', ephemeral=True)
                await audit_admin_action(interaction, 'Database Backup', f'Created backup `{folder}`.')
            else:
                await interaction.followup.send('ℹ️ MongoDB is not connected; no cloud database backup was created.', ephemeral=True)
        except Exception as exc:
            logging.exception('Manual database backup failed')
            await interaction.followup.send(f'❌ Backup failed: `{exc}`', ephemeral=True)
            await send_admin_alert(str(interaction.guild_id), 'DATABASE BACKUP FAILED', str(exc))

    @app_commands.command(name='diagnostics', description='[Staff Only] Run a read-only health and database diagnostic report.')
    async def diagnostics_cmd(self, interaction: discord.Interaction):
        if not await check_admin_privileges(interaction):
            await interaction.response.send_message('❌ Staff only.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        now = time.time()
        uptime_seconds = max(0, int(now - getattr(bot, 'started_at', now)))

        def fmt_uptime(seconds: int) -> str:
            days, rem = divmod(seconds, 86400)
            hours, rem = divmod(rem, 3600)
            minutes, secs = divmod(rem, 60)
            parts = []
            if days:
                parts.append(f'{days}d')
            if hours or days:
                parts.append(f'{hours}h')
            if minutes or hours or days:
                parts.append(f'{minutes}m')
            parts.append(f'{secs}s')
            return ' '.join(parts)

        def task_status(task_obj) -> str:
            if task_obj is None:
                return '⚪ Not initialized'
            try:
                if task_obj.is_running():
                    return '🟢 Running'
                if task_obj.is_being_cancelled():
                    return '🟡 Stopping'
                if task_obj.failed():
                    return '🔴 Failed'
            except Exception:
                pass
            return '⚪ Stopped'
        runtime = []
        counts = {}
        integrity = []
        mongo_ok = False
        latency = bot.latency
        latency_text = f'{round(latency * 1000, 1)}ms' if latency != float('inf') else 'N/A'
        runtime.append(('Gateway', f'🟢 Online • {latency_text}'))
        runtime.append(('Uptime', f'🟢 {fmt_uptime(uptime_seconds)}'))
        runtime.append(('Commands', f'🟢 {len(bot.tree.get_commands())} loaded'))
        runtime.append(('Python', f'`{sys.version.split()[0]}`'))
        runtime.append(('Host', f'`{platform.system()}`'))
        try:
            if bot.mongo_client:
                started = time.perf_counter()
                await bot.mongo_client.admin.command('ping')
                mongo_ms = round((time.perf_counter() - started) * 1000, 1)
                mongo_ok = True
                runtime.append(('MongoDB', f'🟢 Connected • {mongo_ms}ms'))
                for name in ('drivers', 'pending', 'matches', 'active_challenges', 'season_history', 'reference_pending'):
                    try:
                        counts[name] = await getattr(bot.db, name).count_documents({})
                    except Exception:
                        counts[name] = '?'
                try:
                    meta = await bot.db.settings.find_one({'_id': 'global_meta'})
                    if meta and meta.get('guild_overrides_cleaned'):
                        runtime.append(('Guild Command Overrides', '🟢 Cleared (cached — skipped on future boots)'))
                    else:
                        runtime.append(('Guild Command Overrides', '🟡 Not yet cleared — will run on next boot, or use `/staff` → **System → Sync Commands** with full cleanup if needed'))
                except Exception:
                    runtime.append(('Guild Command Overrides', '🔴 Could not check status'))
            else:
                runtime.append(('MongoDB', '🔴 Not connected • mock DB active'))
        except Exception as exc:
            runtime.append(('MongoDB', f'🔴 Error • {str(exc)[:160]}'))
        season_text = 'Unavailable'
        queue_text = 'Unavailable'
        if mongo_ok:
            try:
                state = await bot.db.season_state.find_one({'_id': f'guild_{guild_id}'})
                season = int(state.get('season_number', 1)) if state else 1
                registered = await bot.db.drivers.count_documents({'guild_id': guild_id, 'season_registered': True, 'season_number': season})
                pending = await bot.db.pending.count_documents({'guild_id': guild_id, 'season_number': season})
                active = await bot.db.active_challenges.count_documents({'guild_id': guild_id, 'status': {'$in': ['active', 'processing']}})
                stale = await bot.db.active_challenges.count_documents({'guild_id': guild_id, 'status': 'processing', 'processing_at': {'$lt': now - 900}})
                pending_settlements = await bot.db.matches.count_documents({'guild_id': guild_id, 'settlement_status': 'pending'})
                bad_elo = await bot.db.drivers.count_documents({'guild_id': guild_id, '$or': [{'elo': {'$lt': 0}}, {'elo': {'$gt': 10000}}]})
                bad_pi = await bot.db.drivers.count_documents({'guild_id': guild_id, '$or': [{'garage_pi': {'$lt': 0}}, {'garage_pi': {'$gt': 100000}}]})
                season_text = f'Season {season} • {registered} registered'
                queue_text = f'{active} active/processing • {pending} pending'
                if stale:
                    integrity.append(f'⚠️ Stale processing challenges: `{stale}`')
                if pending_settlements:
                    integrity.append(f'⚠️ Pending settlements: `{pending_settlements}`')
                if bad_elo:
                    integrity.append(f'⚠️ Invalid ELO records: `{bad_elo}`')
                if bad_pi:
                    integrity.append(f'⚠️ Invalid PI records: `{bad_pi}`')
                if not integrity:
                    integrity.append('🟢 No obvious integrity issues found')
            except Exception as exc:
                integrity.append(f'🔴 Integrity check failed: {str(exc)[:160]}')
        else:
            integrity.append('🔴 Database integrity checks skipped — MongoDB unavailable')
        task_lines = [f"**Season Clock:** {task_status(getattr(bot, 'seasonal_clock_loop', None))}", f"**Player Reminders:** {task_status(getattr(bot, 'player_reminder_loop', None))}", f"**Backups:** {task_status(getattr(bot, 'backup_loop', None))}"]
        backup_root = os.getenv('BACKUP_DIR', './backups')
        backup_text = '⚪ No local backup directory'
        try:
            if os.path.isdir(backup_root):
                folders = [os.path.join(backup_root, x) for x in os.listdir(backup_root) if os.path.isdir(os.path.join(backup_root, x))]
                folders.sort(key=lambda x: os.path.getmtime(x), reverse=True)
                if folders:
                    age_hours = max(0, (now - os.path.getmtime(folders[0])) / 3600)
                    status = '🟢' if age_hours <= 30 else '🟡' if age_hours <= 48 else '🔴'
                    backup_text = f'{status} {len(folders)} local • latest {age_hours:.1f}h ago'
                else:
                    backup_text = '🔴 No local backups found'
        except Exception as exc:
            backup_text = f'🔴 Check failed • {str(exc)[:100]}'
        embed = discord.Embed(title='🛠️ RACING SYNDICATE LEAGUE — DIAGNOSTICS', description='Read-only system, database, task, and backup health check.', color=ASPHALT_ADMIN_COLOR if mongo_ok else ASPHALT_ALERT_COLOR, timestamp=datetime.now(timezone.utc))
        embed.set_thumbnail(url=ASPHALT_MEDIA['thumb_diagnostics'])
        embed.add_field(name='🖥️ Runtime', value='\n'.join((f'**{k}:** {v}' for k, v in runtime)), inline=False)
        embed.add_field(name='🗄️ Database', value='\n'.join([f"**Drivers:** `{counts.get('drivers', '?')}`", f"**Pending:** `{counts.get('pending', '?')}`", f"**Matches:** `{counts.get('matches', '?')}`", f"**Challenges:** `{counts.get('active_challenges', '?')}`", f"**Season Archives:** `{counts.get('season_history', '?')}`", f"**Reference Queue:** `{counts.get('reference_pending', '?')}`"]), inline=True)
        embed.add_field(name='⚙️ Tasks & Backups', value='\n'.join(task_lines) + f'\n**Local Backups:** {backup_text}', inline=True)
        embed.add_field(name='🏁 League', value=f'**Current:** {season_text}\n**Queue:** {queue_text}', inline=False)
        embed.add_field(name='🔍 Integrity', value='\n'.join(integrity)[:1024], inline=False)
        embed.set_footer(text='Read-only • `/staff` → **Data → Database Check** = full audit • `/staff` → **Data → Backup** = manual backup')
        await interaction.followup.send(embed=embed, ephemeral=True)
        await audit_admin_action(interaction, 'Diagnostics', 'Ran read-only system, database, task, and backup diagnostics.')

    @app_commands.command(name='launchcheck', description='[Staff Only] Run a read-only Racing Syndicate League production readiness check.')
    async def launchcheck_cmd(self, interaction: discord.Interaction):
        if not await check_admin_privileges(interaction):
            await interaction.response.send_message('⛔ Staff only.', ephemeral=True)
            return
        await send_launch_readiness(interaction)
        await record_system_event(str(interaction.guild_id), 'LAUNCH_CHECK', f'Launch readiness check requested by {interaction.user.id}')

async def setup(bot):
    await bot.add_cog(StaffCog(bot))
