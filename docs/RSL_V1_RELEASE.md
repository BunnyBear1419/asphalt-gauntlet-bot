# RSL v1.0 Production Baseline

## Purpose

Racing Syndicate League v1.0 is the production baseline after the final acceptance gate. The baseline favors reliability, recoverability, transparent records, and consistent website/Discord behavior over adding more competitive mechanics.

## Already-protected systems

- GitHub Actions CI/deployment gate.
- Discloud-first production deployment.
- Automated production health checks.
- MongoDB backup/restore verification and manual restore drills.
- Durable \`system_events\` audit records.
- Database schema/index diagnostics.
- Unified public Player Profile.
- Gauntlet settlement/replay/recovery protections.
- Tournament registration, bracket, result, media, and completion safeguards.
- XP, achievements, season history, notifications, and RSL Command Center.
- Website/Discord authorization and guild-isolation checks.

## New operational controls

### Maintenance Mode

Staff can pause competitive mutations for a guild without taking the entire website offline.

While enabled:
- New competitive mutations are blocked.
- Existing public profiles and history remain readable.
- Account settings, notifications, reminders, and staff controls remain available.
- Staff can disable maintenance mode and resume competition.

Maintenance mode changes are written to \`system_events\`.

### Discord Support & Disputes

All support and competition disputes are handled through the official Discord ticket channel. The website does not maintain a second dispute queue; players should open an RSL ticket and include the relevant match/tournament/player identifier and evidence when applicable.

Each request contains:
- category
- subject
- description
- optional target type/id
- submitter
- timestamps
- status
- staff resolution

Staff decisions are retained and audited rather than silently replacing history.

## Backup and Restore

The repository already includes automated weekly MongoDB restore verification and a manual restore-test workflow. Before declaring a release baseline, staff should confirm that the latest successful restore is readable and that the documented recovery credentials/process are available.

## Release Freeze

After v1.0 acceptance:
- Security fixes: allowed.
- Data-integrity/reliability fixes: allowed.
- Production-breaking bug fixes: allowed.
- Accessibility/critical UX fixes: allowed.
- New competitive mechanics: require a deliberate v1.1 change review.
- Schema changes: require migration/recovery review.
- Destructive cleanup: requires staff review.

## Human acceptance still required

Automation cannot replace the final production walkthrough:
1. One controlled Gauntlet match.
2. One controlled tournament.
3. Website ↔ Discord parity.
4. Staff/admin authorization walkthrough.
5. Notification/economy/XP verification.
6. Production log observation after real activity.
7. Backup/restore confirmation.

The v1.0 baseline should be tagged only after these checks are completed.
