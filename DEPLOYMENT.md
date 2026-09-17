# ALU Gauntlet Web Control Center Deployment

The Web Control Center runs in the same process as the Discord bot. The production container exposes port `8080` and binds to `0.0.0.0` so a hosting platform can route public HTTPS traffic to it.

## Required production environment

Set these variables in the hosting provider's secret/environment settings:

- `DISCORD_BOT_TOKEN`
- `MONGO_URI`
- `DISCORD_CLIENT_ID`
- `DISCORD_CLIENT_SECRET`
- `WEB_PUBLIC_URL` — the public HTTPS URL of the Control Center, with no trailing slash
- `WEB_STAFF_USER_IDS` — optional comma-separated Discord user IDs that should have web staff access regardless of guild administrator permissions
- `BACKUP_DIR` — normally `./backups`
- `WEB_HOST=0.0.0.0`
- `WEB_PORT=8080` unless the hosting platform requires another port

Never commit production credentials to GitHub.

## Discord OAuth2 setup

In the Discord Developer Portal, configure the OAuth2 redirect URI as:

`WEB_PUBLIC_URL/auth/callback`

The application uses the `identify` and `guilds` scopes. Staff access is then checked against the Discord account's administrator permissions for the selected server, or the optional `WEB_STAFF_USER_IDS` allowlist.

## Docker deployment

Build and run:

```bash
docker build -t alu-gauntlet .
docker run --env-file .env -p 8080:8080 alu-gauntlet
```

For production, provide environment variables through the hosting provider rather than storing a production `.env` file in the image or repository.

## Hosting platform settings

Use the repository's `Dockerfile` as the application build definition.

- Container port: `8080`
- Start command: already defined by the Dockerfile
- Persistent storage: optional for `BACKUP_DIR`; MongoDB is the durable application database
- Public URL: set `WEB_PUBLIC_URL` to the HTTPS address assigned by the host

If the platform supplies a dynamic `PORT`, set `WEB_PORT` to that value and keep `WEB_HOST=0.0.0.0`.

## First deployment checklist

1. Deploy the `feature/web-control-center` branch to a staging service.
2. Set all required environment variables.
3. Set the Discord OAuth redirect URI to the exact public callback URL.
4. Open the public Control Center URL and select **Login with Discord**.
5. Confirm a staff/admin account can sign in.
6. Confirm a non-staff account is rejected.
7. Select each authorized Discord server and verify server data stays scoped to that server.
8. Run **Launch Check** from the web Control Center.
9. Verify `/dashboard` and `/staff` still work in Discord.
10. Only after staging verification should the deployment be promoted to production.

## Current safety model

The web Control Center is intentionally read-only in this release. It does not expose simulator functionality and does not mutate league state. Configuration changes remain in the Discord setup wizard. The web UI should therefore be treated as a staff operations and monitoring surface until mutation APIs are deliberately added and tested.
