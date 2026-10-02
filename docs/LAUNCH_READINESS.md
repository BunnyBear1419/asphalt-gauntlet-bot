# RSL Launch Readiness

## Release status
- Production branch: `main`
- Hosting: Discloud
- Automated CI/deploy: GitHub Actions
- Latest verified release: `b1604be9062e453f0341e2307d6f65224585449d`
- Latest CI/deploy run: #3626 — passed
- Automated tests: passed
- Production module import smoke gate: passed
- Compile check: passed
- Dependency audit: passed
- Discloud deployment/restart: passed
- Post-deployment smoke test: passed
- Production OAuth/login smoke test: passed
- Production heartbeat/health checks: passed
- Rollback path: available; not required for the latest successful release

## Current assurance status
The automated implementation and regression phase is complete for the current verified release (`b1604be9062e453f0341e2307d6f65224585449d`). Browser contract coverage includes the major Clubs, Player Settings, Admin System, navigation, support, ticket, calendar, Gauntlet, and tournament surfaces. Production import-smoke coverage is also enabled to catch route/package import failures before deployment.

A read-only Chromium live browser suite is now part of the deployment gate and is also available as a scheduled/manual workflow. It checks the deployed public shell, navigation, Clubs controls, protected routes, and a mobile viewport without submitting forms or changing competition data.

The remaining unchecked acceptance items below are intentionally manual/live acceptance tests. They are not marked complete based solely on automated tests.

## Final product checks
- [x] Primary navigation uses Rules before Companion
- [x] No duplicate Companion navigation
- [x] No obsolete Rules icon asset reference
- [x] Public Profile has no duplicate leaderboard navigation action
- [x] First-time Driver onboarding is integrated into the existing Player page
- [x] Existing notifications, Career/season history, Operations/Recovery, and Admin systems are reused rather than duplicated
- [x] Six RSL divisions remain the league structure
- [x] Public slash-command surface remains intentionally small
- [x] Security, upload validation, settlement idempotency, guild isolation, and concurrency protections are covered by regression tests
- [x] Cross-cutting assurance layer added without duplicating canonical diagnostics, notifications, economy, season history, or Discord support
- [x] Privacy export/request, evidence timeline, public status, transparency, readiness, and admin security/performance APIs are covered by regression tests
- [x] Non-transactional paid-ticket purchase failure cannot permanently consume Coins without a ticket grant
- [x] OAuth callback errors no longer expose exception type/details to unauthenticated users

## Final acceptance test matrix

### Website
- [x] Automated live browser smoke checks the deployed homepage and public routes
- [x] Automated live browser smoke exercises the Clubs Create Club panel without submitting it
- [x] Automated live browser smoke checks protected Player/Admin route gates
- [x] Automated live browser smoke checks a mobile viewport
- [ ] Open homepage while signed out
- [ ] Verify navigation and profile menu
- [ ] Sign in with Discord
- [ ] Verify Player dashboard/onboarding
- [ ] Verify My Settings and My Profile separation
- [ ] Verify profile stats, XP, credits, tickets, division, and history
- [ ] Verify Gauntlet registration/challenge/defense screens
- [ ] Verify tournament registration, brackets, and results
- [ ] Verify Clubs
- [ ] Verify Calendar
- [ ] Verify Rules, Help, and Legal pages
- [ ] Verify ticket/support path points to the configured Discord ticket channel
- [ ] Test desktop and mobile layouts
- [ ] Test keyboard focus and modal close behavior

### Discord
- [ ] Confirm bot is online
- [ ] Confirm /dashboard opens the player experience
- [ ] Confirm /staff is restricted to staff
- [ ] Verify player-facing actions work from Discord
- [ ] Verify staff actions remain available if the website is unavailable
- [ ] Verify website actions produce expected Discord notifications/logs

### Competition
- [ ] Complete a controlled five-race Gauntlet challenge
- [ ] Verify race-win scoring
- [ ] Verify ticket consumption only when an opponent is selected
- [ ] Verify defense submission/review
- [ ] Verify result approval/rejection
- [ ] Verify settlement and replay protection
- [ ] Verify abandoned/quitting recovery behavior
- [ ] Verify XP, RSL Coins, roles, and season progression
- [ ] Verify tournament registration/check-in/bracket/result flow

### Operations and recovery
- [ ] Confirm Operations/Diagnostics reports healthy state
- [ ] Confirm audit events are recorded
- [ ] Confirm backup exists and latest restore verification is green
- [ ] Confirm Maintenance Mode can safely pause competition
- [ ] Confirm stuck-match recovery path
- [ ] Confirm season preview/finalization controls
- [ ] Confirm release history records deployments
- [ ] Confirm website and Discord provide an alternate operational path

## Launch rule
Do not add new feature scope during acceptance testing unless a missing requirement, security issue, data-integrity issue, or launch-blocking usability defect is discovered. Fix defects, rerun automated CI, redeploy, and then resume the acceptance matrix.

## Post-launch
For the first live season, monitor:
- settlement/replay errors
- ticket/coin ledger anomalies
- failed evidence/media reviews
- stuck processing matches
- Discord/web notification delivery
- tournament bracket transitions
- database/heartbeat health
- user-reported navigation or mobile issues

Keep competition history and audit records intact. Prefer correction/reconciliation over destructive cleanup.
