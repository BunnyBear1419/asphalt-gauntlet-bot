# Racing Syndicate League Production Maintenance

## Deployment

Production is Discloud-first. The `main` branch is the production branch and GitHub Actions verifies compilation, tests, deployment, restart, and automated post-deployment health checks.

Personal browser/live testing is intentionally separate from automated verification.

## Verification order

Run:

    python -m py_compile main.py
    pytest -q

The production workflow performs the repository's configured test and deployment checks. MongoDB integration checks run separately when their workflow is triggered.

## Database safeguards

Critical tournament protections include:

- unique active player registration per tournament
- unique active club registration per tournament
- unique tournament action lock per match
- indexed tournament media by tournament/status/time
- unique notification delivery by event/user/lead time
- deterministic match settlement identifiers

Keep Atlas access restricted and use a dedicated database user.

## Cleanup policy

Competition history is valuable data. Do not use broad automatic deletion for completed tournaments, verified results, champion records, or published media.

For stale operational records, first identify:

1. the collection and record age;
2. whether the record belongs to a live/active tournament;
3. whether it is referenced by another record;
4. whether an audit/history entry exists;
5. whether the record is safe to archive rather than delete.

Any destructive cleanup should be reviewed before execution.

## Final release checklist

- [ ] No stale top-level `/setup` Discord command is exposed.
- [ ] Staff setup remains available through the staff/dashboard flow.
- [ ] Public command surface remains `/dashboard` and `/staff`.
- [ ] Calendar navigation appears before Companion.
- [ ] Search remains left of Profile.
- [ ] Account language preference remains persisted by user.
- [ ] Tournament result mode is stored and enforced.
- [ ] Tournament media approval is enforced.
- [ ] Completed tournaments expose champion, standings, match history, and approved media.
- [ ] CI is green before production deployment.