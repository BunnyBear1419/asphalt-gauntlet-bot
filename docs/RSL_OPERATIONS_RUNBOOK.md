# RSL Operations & Launch Runbook

This runbook consolidates the remaining operational safeguards for Racing Syndicate League without creating duplicate dashboards or support systems.

## 1. Monitoring and alerting

The production health workflow runs hourly and can also be started manually. It checks:
- Discloud application status
- Discord bot API/token reachability
- Production web health endpoint
- MongoDB connectivity
- Fresh production heartbeat
- Bot readiness/database health

Health failures can notify the configured central Discord monitoring webhook.

Recommended production secrets/configuration:
- GitHub Actions: `DISCLOUD_TOKEN`, `DISCORD_BOT_TOKEN`, `MONGO_URI`, and deployment secrets already required by CI.
- Optional failure alert: `DISCORD_WEBHOOK_URL` for GitHub health-workflow failures.
- Optional bot heartbeat alert: `HEALTH_WEBHOOK_URL`.
- Optional Discord operational alert: `DISCORD_ALERT_WEBHOOK`.

Never put a bot token, MongoDB URI, webhook URL, or other credential in source control.

## 2. Scheduled health review

The automated monitor is the first line of defense. Staff should use the existing Operations/Diagnostics surface when investigating an alert.

Check:
1. Bot status and gateway latency.
2. MongoDB response.
3. Current season and active challenges.
4. Stale processing challenges.
5. Last backup and heartbeat.
6. Maintenance/Safe Mode state.
7. Recent audit/release events.

Do not create a second health dashboard.

## 3. Backup and restore verification

Backups are not considered reliable merely because a backup file exists.

Before destructive maintenance:
1. Confirm a recent backup/restore verification is green.
2. Confirm the target database/collection and affected records.
3. Enable Maintenance/Safe Mode when competition mutations must pause.
4. Perform the change.
5. Run database/integrity checks.
6. Record the action in the existing audit history.

Prefer reconciliation or archival over destructive deletion.

## 4. Disaster-recovery paths

### Website unavailable
Use the Discord bot's existing dashboard/staff paths for supported player and staff operations. Investigate Discloud and the production health workflow before making database changes.

### Discord unavailable
Use the website control center for supported web operations. Do not assume a Discord outage means competition data is lost.

### MongoDB unavailable
Do not attempt to recreate or manually rewrite competition state. Restore database connectivity, verify integrity, and use the existing recovery/reconciliation mechanisms.

### Failed deployment
Use the CI deployment workflow's known-good revision and rollback path. Verify production health after recovery before resuming competition.

### Stuck match/settlement
Use the existing Operations/Integrity & Recovery controls. Preserve the original settlement/audit records; reconciliation must be idempotent.

## 5. Maintenance cadence

### Before each season
- Verify backups and restore verification.
- Review season settings and division configuration.
- Confirm roles/channels and staff permissions.
- Review pending/stale competition records.
- Confirm notification paths.
- Confirm the deployment branch and CI status.

### During a season
- Review production health alerts.
- Review settlement/replay anomalies.
- Review evidence/media queues.
- Review stuck processing matches.
- Review ticket/coin ledger anomalies.
- Review tournament bracket transitions.
- Keep audit history intact.

### After a season
- Complete season finalization through the existing Operations controls.
- Verify rewards, roles, history, and standings.
- Verify the next-season state.
- Confirm backups.
- Review errors and reconciliation events.

## 6. Support and feedback

Do not create a separate website ticketing system.

Use the configured Discord support/ticket channel as the canonical human support path. Website help/support actions should route users there. Staff should classify reports as:
- Bug
- Account/access issue
- Competition/result issue
- Tournament issue
- Question
- Suggestion

Record competition-impacting corrections through the existing audit/recovery systems.

## 7. Privacy and retention

The Legal Center is the canonical policy surface. Before launch and after major feature changes, review that it accurately describes:
- Discord authentication/account identifiers
- Player profile and competition records
- Club/tournament participation
- Preferences and technical session information
- Cookies/storage and analytics
- User-submitted evidence/media
- Third-party services
- Support/contact handling
- Retention/deletion expectations

Do not promise deletion of records that must be retained for competition integrity without documenting the distinction between personal data and durable competition/audit history.

## 8. Analytics

Keep analytics intentionally limited to useful product signals. Review the existing Google Analytics configuration for:
- Homepage to registration progression
- Registration to first competition
- Tournament participation
- Mobile/desktop usage
- Common navigation exits

Do not collect unnecessary sensitive information. Analytics should support product usability decisions, not replace direct support feedback.

## 9. Release discipline

During final acceptance testing:
- Freeze feature scope.
- Fix defects, security issues, data-integrity issues, or launch-blocking UX problems.
- Run CI after every code change.
- Deploy only through the production deployment gate.
- Re-run the acceptance checklist after a production-affecting fix.

Avoid adding duplicate pages, commands, dashboards, or parallel support systems.

## 10. Post-launch watch period

For the first live season, pay particular attention to:
- settlement and replay errors
- ticket/coin ledger anomalies
- failed evidence/media reviews
- stuck processing matches
- web/Discord notification delivery
- tournament bracket transitions
- database/heartbeat health
- mobile/navigation reports

Keep competition history, verified results, champion records, approved media, career history, and audit events intact.

## 11. Launch completion rule

The system is ready to enter hands-on acceptance testing when:
- CI is green.
- Production deployment and smoke checks are green.
- Security/concurrency/database safeguards are green.
- The launch-readiness checklist is available.
- No known launch-blocking defect remains.

After that point, live acceptance testing is the source of truth for real user behavior.
