# GCP Setup (Cloud SQL + Pub/Sub + Cloud Run)

## Architecture (recommended)
- Cloud Run: runs the FastAPI backend (WebSockets + API)
- Cloud SQL (Postgres): primary database
- Pub/Sub: cross-instance event fanout for hospital dashboard
- Optional: Cloud Storage + CDN for static hosting (or serve static from Cloud Run)

## New env vars
Set these in your environment (Cloud Run or local):
- `DATABASE_URL` (Postgres connection string)
- `DATABASE_MAX_CONNECTIONS` (default 5)
- `GCP_PROJECT_ID` (e.g., `my-project`)
- `GCP_PUBSUB_TOPIC` (topic name or full topic path)
- `GCP_PUBSUB_SUBSCRIPTION_PREFIX` (optional, default `aria-health-events`)

## Cloud SQL (Postgres)
1. Create a Cloud SQL Postgres instance.
2. Create a database (e.g., `aria_health`) and user.
3. Make sure your Cloud Run service account has `Cloud SQL Client` role.

### Local dev (Cloud SQL Auth Proxy)
1. Download and run the proxy:
   ```bash
   ./cloud-sql-proxy <PROJECT>:<REGION>:<INSTANCE> --port 5432
   ```
2. Set:
   ```bash
   export DATABASE_URL='postgresql://USER:PASSWORD@127.0.0.1:5432/aria_health'
   ```
3. Start the app as usual; tables are created on startup.

### Cloud Run connection (Unix socket)
Use the Cloud SQL connection name in your Cloud Run service and set:
```bash
export DATABASE_URL='postgresql://USER:PASSWORD@/aria_health?host=/cloudsql/<PROJECT>:<REGION>:<INSTANCE>'
```

## Pub/Sub (for multi-instance streaming)
1. Enable Pub/Sub API.
2. Create a topic (e.g., `aria-health-events`).
3. Set:
   ```bash
   export GCP_PROJECT_ID='my-project'
   export GCP_PUBSUB_TOPIC='aria-health-events'
   ```
4. Ensure your Cloud Run service account has `Pub/Sub Publisher` and `Pub/Sub Subscriber` roles.

## Cloud Run deploy
1. Build a container.
2. Deploy with:
   - WebSockets enabled (default for Cloud Run)
   - Min instances (optional for low-latency)
   - Environment variables from above

## Notes
- If `GCP_PROJECT_ID` and `GCP_PUBSUB_TOPIC` are set but `google-cloud-pubsub` isn't installed, the app falls back to in-memory events (single instance only).
- If `DATABASE_URL` is not set, the app defaults to local SQLite.
