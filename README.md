# ALU Gauntlet Bot

Production package for the Asphalt Legends Unite Gauntlet League Discord bot.

## Stack

- Python 3.12
- discord.py
- MongoDB Atlas
- Motor
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

The bot also has a `/backup` staff command and a scheduled local JSON backup loop. Local Discloud storage should be treated as best-effort, not as the only backup location.

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
