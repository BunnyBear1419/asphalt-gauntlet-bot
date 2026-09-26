# Discloud-first production deployment

This repository is designed to run the **Racing Syndicate League Discord bot and web control center in the same Discloud app**.

## Production architecture

- GitHub: source of truth for the application code.
- Discloud app: `asph`.
- Website: `https://asph.discloud.app/`.
- Discord bot: started by the same `main.py` process.
- MongoDB Atlas: persistent application data and web sessions.
- Local PC: **not required for 24/7 hosting**.

The root `discloud.config` uses `TYPE=site`, `MAIN=main.py`, Python 3.12, 512 MB RAM, and automatic restart. Discloud's site hosting routes the registered subdomain to the application's port; this application reads Discloud's `PORT` and defaults to 8080. citeturn1search1turn1search4

## Production deployment path: GitHub Actions → Discloud

GitHub Actions is the repository's **single production deployment path**. The workflow in `.github/workflows/deploy.yml` runs tests first, uploads the committed tree to the existing Discloud app `asph`, restarts it, runs production smoke tests, and rolls back to the previous revision if the new deployment fails health checks.

Do **not** enable Discloud GitHub Integration for automatic deployment of this same repository/branch. A second automatic deployment path can race the Actions deployment and produce duplicate uploads, rate limits, or conflicting production revisions.

The workflow requires these GitHub Actions secrets:
- `DISCLOUD_TOKEN`
- `DISCLOUD_APP_ID` — must be exactly `asph`
- `DISCORD_BOT_TOKEN`
- `MONGO_URI`

After a successful workflow, verify `https://asph.discloud.app/healthz` and Discord connectivity.

## Required production environment variables

Set these in Discloud's environment-variable configuration. **Do not commit their values to GitHub.**

- `DISCORD_BOT_TOKEN` — Discord bot token.
- `MONGO_URI` — MongoDB Atlas connection string.
- `DISCORD_CLIENT_ID` — Discord application client ID used by website OAuth.
- `DISCORD_CLIENT_SECRET` — Discord OAuth client secret.
- `WEB_PUBLIC_URL=https://asph.discloud.app` — public website URL.
- `WEB_STAFF_USER_IDS` — optional comma-separated Discord user IDs that should have global web staff access.
- `BACKUP_DIR=./backups` — optional local backup directory.

Optional:

- `HEALTH_WEBHOOK_URL` — private operations heartbeat webhook.
- `DISCORD_ALERT_WEBHOOK` — Discord alert webhook if configured by the bot.

## Discord OAuth configuration

In the Discord Developer Portal, the OAuth redirect URI must be:

`https://asph.discloud.app/auth/callback`

The application already uses `https://asph.discloud.app` as its production default public URL, but keeping `WEB_PUBLIC_URL` explicitly set in Discloud makes the production configuration unambiguous.

## What runs together

`main.py` imports the canonical runner from `ALU_Gauntlet.main`.

The runner:

1. Loads the production cogs.
2. Reads `DISCORD_BOT_TOKEN`.
3. Starts `WebControlCenter` on `0.0.0.0` and Discloud's `PORT`.
4. Starts the Discord bot.
5. Stops the web server cleanly when the bot process exits.

This means the website and Discord bot do not need separate local processes or a computer running 24/7.

## Deployment safety

Production deployment is owned by the GitHub Actions `CI and Deploy` workflow. Do not configure a second automatic deployment path for the same `main` pushes, because overlapping uploads can trigger Discloud rate limits or race the production process.

The repository also contains `.discloudignore` so Git metadata, development environments, tests, logs, backups, and local environment files are not included in the Discloud deployment package. Discloud recommends using `.discloudignore` to exclude unnecessary deployment files. citeturn1search1

## Production verification

After deployment, check:

- `https://asph.discloud.app/healthz`
- `https://asph.discloud.app/login`
- `https://asph.discloud.app/`
- Discord bot is online.
- Discord OAuth login reaches `/auth/callback`.
- MongoDB-backed player/session data loads.
- Player dashboard works.
- Staff dashboard works.

Do not delete or recreate the existing `asph` app just to change deployment method. The goal is to update the existing service in place.
