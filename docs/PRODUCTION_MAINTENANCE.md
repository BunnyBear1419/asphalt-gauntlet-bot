# Racing Syndicate League Production Maintenance

## Purpose
Operational guidance for maintaining the production RSL web control center and Discord bot without deleting competition history or bypassing deployment safety gates.

## Deployment
Production is Discloud-first. `main` is the production branch. CI/deploy runs compilation, tests, dependency checks, deployment, restart, production smoke checks, and rollback recovery when required.

Personal browser/live testing remains a final acceptance activity; it is not a substitute for automated verification.

## Operational safeguards
- Keep MongoDB Atlas access restricted and use a dedicated database user.
- Treat `system_events` as durable audit history.
- Use Maintenance Mode for planned competitive changes instead of taking the entire website offline.
- Route corrections, disputes, and support through the official Discord ticket workflow; do not silently overwrite competition history.
- Use automated backup verification or the manual restore drill before destructive database work.

## Safe cleanup policy
Competition history is valuable data. Do not broadly delete completed tournaments, verified results, champion records, published media, player career history, or audit records.

For stale operational records, verify the collection and record age, active-event references, dependent records, audit/history coverage, and whether archiving is safer than deletion.

Any destructive cleanup requires staff review and a verified backup.

## Repository cleanup policy
- Keep compatibility routes/files only when they protect existing URLs or stored links.
- Keep the seven production workflows because each has a distinct responsibility.
- Keep active setup/UI compatibility modules such as `setup_wizard.py`, `dashboard_setup_bridge.py`, and `ui_fixes.py`; they are imported by the running application.
- Keep `profile.html` and `profile.js` as compatibility redirects until the legacy route is intentionally retired in a breaking release.
- The canonical public Player Profile is `/profile?user_id=...`; settings remain under `/player/settings`.
- The unified profile regression suite is `tests/test_unified_profile.py`.

## Final release checklist
- [ ] No stale top-level `/setup` Discord command is exposed.
- [ ] Staff setup remains available through the staff/dashboard flow.
- [ ] Public command surface remains `/dashboard` and `/staff`.
- [ ] Calendar navigation appears before Rules and Companion; XP is available inside player profiles and Admin Tools.
- [ ] Search remains left of Profile.
- [ ] Account language preference remains persisted by user.
- [ ] Tournament result mode is stored and enforced.
- [ ] unique active player registration remains enforced.
- [ ] Tournament media approval is enforced.
- [ ] Completed tournaments expose champion, standings, match history, and approved media.
- [ ] CI is green before production deployment.
- [ ] Latest backup restore verification is green before destructive database maintenance.
