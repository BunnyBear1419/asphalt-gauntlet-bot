# Discloud-first production deployment

This repository is designed to run the **ALU Gauntlet Discord bot and web control center in the same Discloud app**.

## Production architecture

- GitHub: source of truth for the application code.
- Discloud app: `asph`.
- Website: `https://asph.discloud.app/`.
- Discord bot: started by the same `main.py` process.
- MongoDB Atlas: persistent application data and web sessions.
- Local PC: **not required for 24/7 hosting**.

The root `discloud.config` uses `TYPE=site`, `MAIN=main.py`, Python 3.12, 512 MB RAM, and automatic restart. Discloud's site hosting routes the registered subdomain to the application's port; this application reads Discloud's `PORT` and defaults to 8080. citeturn1search1turn1search4

## Recommended deployment path: Discloud GitHub Integration

GitHub Actions is **not required** for production deployment. Discloud supports deploying directly from a GitHub repository.

1. Open the Discloud Dashboard.
2. Open **GitHub Integration**.
3. Connect the GitHub account that owns this repository.
4. Configure repository access and allow the `BunnyBear1419/asphalt-gauntlet-bot` repository.
5. Use **Upload → GitHub**.
6. Select this repository and the `main` branch.
7. Keep the existing app ID as `asph` so the deployment targets the existing website/bot service.
8. Enter the production environment variables listed below.
9. Deploy.
10. Verify `https://asph.discloud.app/healthz` returns a healthy response and then verify Discord bot connectivity.

Discloud documents the GitHub Integration flow and requires a valid root-level `discloud.config`. citeturn1search0

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

The existing GitHub Actions workflow can remain in the repository for testing/optional automation, but **production deployment does not depend on GitHub Actions** when using Discloud's GitHub Integration.

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
