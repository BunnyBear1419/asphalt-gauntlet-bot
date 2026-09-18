# ALU Gauntlet Bot

Production package for the Asphalt Legends Unite Gauntlet League Discord bot.

## Stack

- Python 3.12
- discord.py
- MongoDB Atlas
- PyMongo Async
- Discloud
- GitHub Actions

## Required environment variables

- `DISCORD_BOT_TOKEN` — Discord bot token
- `MONGO_URI` — MongoDB Atlas connection string
- `BACKUP_DIR` — optional local backup directory; defaults to `./backups`

Do not commit `.env` or real credentials.

## Local Windows setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
python main.py
```

Edit `.env` first and put in the real Discord token and MongoDB URI.

## Tests

```powershell
python -m py_compile main.py
python tests/test_final.py
```

## Discloud

The root `discloud.config` points to `main.py` and Python 3.12.

For GitHub deployment, connect the repository in Discloud and add these production environment variables in the Discloud environment-variable section:

- `DISCORD_BOT_TOKEN`
- `MONGO_URI`
- `BACKUP_DIR=./backups`

Do not put real secrets in GitHub.

## MongoDB

The bot stores league state in MongoDB. Keep MongoDB Atlas network access restricted as much as your deployment setup allows and use a dedicated database user.

The bot also exposes database backups through `/staff` → **Data → Backup** and runs a scheduled local JSON backup loop. Local Discloud storage should be treated as best-effort, not as the only backup location.

## Recommended Git flow

- `main` = production
- `dev` = testing
- Feature branches = changes

Test locally → push to `dev` → GitHub Actions passes → merge to `main` → deploy to Discloud.

## Production hardening

The production build uses PyMongo Async with MongoDB Stable API v1, deterministic review-delivery reconciliation, match-lap provenance for safe reverts, and a live Discord heartbeat for external health monitoring.

### Production health monitoring

This bot serves multiple independent Discord servers, so production health monitoring is **not tied to any guild or Discord channel**. The GitHub Actions health check verifies that Discloud reports the application as running and that the Discord API accepts the bot token.

No `HEALTH_CHANNEL_ID` GitHub secret is required.

Optionally, set `HEALTH_WEBHOOK_URL` in the bot environment to receive bot-level `ALU_HEARTBEAT` notifications in a private operations webhook. This is optional and is not associated with any Discord server.

## Production operations and player experience

The production build uses a deliberately small public slash-command surface:

- `/dashboard` — player home screen. Player features such as profile, registration, stats, defense, challenges, leaderboards, maps, references, notifications, and account controls are accessed through the dashboard UI.
- `/staff` — staff/admin home screen. Staff features such as player management, reviews, season controls, backups, diagnostics, live status, setup, and synchronization are accessed through the staff dashboard UI.

The underlying staff status callback is intentionally hidden from Discord's slash-command picker and is launched from **Staff → System → Live Status**. Player statistics are part of the canonical **Profile & Stats** dashboard view rather than a separate command.
- Durable admin audit events in `system_events` in addition to the configured Discord log channel.
- Automated weekly MongoDB restore verification plus manual `workflow_dispatch` support.
- Required-collection and critical-index checks through `/staff` → **Data → Database Check**.
- CI dependency auditing, compile checks, unit tests, and lightweight concurrency regression coverage.

For production monitoring, configure `HEALTH_WEBHOOK_URL`, `DISCORD_ALERT_WEBHOOK`, and the GitHub production-health secrets documented below.

## v18 UX changes

- Server Setup now lets admins choose the **Staff Role Name** and **Player Role Name**. The bot reuses an existing matching role or creates it when permitted. It never automatically grants the Staff role.
- Custom images can be uploaded by authorized staff by posting one image directly in the configured Staff Review Channel. The bot validates the image and stores a canonical Discord CDN copy in the configured log channel; URL/DM upload is no longer required for custom images.
- Season Automation **Disable** is a red danger button.
- Health & Diagnostics is a single canonical staff diagnostic center; duplicate health/diagnostics entry points should not be added.

<!-- CI verification trigger: production dashboard artwork deployment. -->
