# Deployment

AIEngine runs on GCP Cloud Run (us-central1) backed by Cloud SQL (PostgreSQL 18).

## Current infrastructure

| Resource | Name | Details |
|---|---|---|
| Cloud Run (prod) | `aiengine-prod` | 1 CPU, 1Gi RAM, 1 instance, concurrency 20 |
| Cloud Run (staging) | `aiengine` | 1 CPU, 1Gi RAM, 1 instance, concurrency 20 |
| Cloud SQL | `aiengine-db` | PostgreSQL 18, `db-f1-micro`, `us-central1-a` |
| Artifact Registry | `aiengine` | Docker, `us-central1` |
| Service Account | `aiengine-sa` | Roles: `cloudsql.client`, `secretmanager.secretAccessor` |
| GCP Project | `project-80a32569-9882-44bc-933` | |

Staging points to the Vercel dev frontend. Prod points to `https://app.onlyhuman.us/`.

Both Cloud Run services share the same Cloud SQL instance but use separate database secrets (`database-url` vs `prod-database-url`).

### Why CPU is always allocated

Cloud Run throttles CPU to near-zero after an HTTP response is returned. The webhook endpoint responds 200 immediately and then runs the facilitation pipeline inside FastAPI's `BackgroundTasks`. Without `--no-cpu-throttling` / `CPU is always allocated`, the background task gets starved mid-pipeline (OpenAI calls, DB writes). This is the single most important config detail.

Since `min-instances=1` keeps the container alive anyway, always-on CPU adds no cost.

---

## Secrets (Secret Manager)

| Secret name | Used by |
|---|---|
| `openai-api-key` | Both services |
| `api-key` | Both services |
| `database-url` | Staging |
| `prod-database-url` | Prod |

---

## Deploying a new version

```bash
export PROJECT_ID="project-80a32569-9882-44bc-933"
export REGION="us-central1"
export REPO="us-central1-docker.pkg.dev/$PROJECT_ID/aiengine/aiengine"

# Build and push
docker build -t $REPO:latest .
docker push $REPO:latest

# Deploy to prod
gcloud run services update aiengine-prod \
  --image=$REPO:latest \
  --region=$REGION

# Deploy to staging
gcloud run services update aiengine \
  --image=$REPO:latest \
  --region=$REGION
```

Or use `build_and_push.sh` (not tracked in git) which wraps the above.

---

## Deploying from scratch

### 1. Enable APIs

```bash
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com
```

### 2. Create Artifact Registry repo

```bash
gcloud artifacts repositories create aiengine \
  --repository-format=docker \
  --location=us-central1

gcloud auth configure-docker us-central1-docker.pkg.dev
```

### 3. Create Cloud SQL instance

```bash
gcloud sql instances create aiengine-db \
  --database-version=POSTGRES_18 \
  --tier=db-f1-micro \
  --region=us-central1 \
  --zone=us-central1-a \
  --storage-type=SSD \
  --storage-size=10GB \
  --storage-auto-increase \
  --backup-start-time=03:00

gcloud sql databases create aiengine --instance=aiengine-db
gcloud sql databases create aiengine_staging --instance=aiengine-db

gcloud sql users create aiengine_user \
  --instance=aiengine-db \
  --password="CHANGE_ME"
```

Get the connection name for use in `DATABASE_URL`:
```bash
gcloud sql instances describe aiengine-db --format="value(connectionName)"
# project-80a32569-9882-44bc-933:us-central1:aiengine-db
```

`DATABASE_URL` format for Cloud Run (uses Unix socket via Cloud SQL proxy sidecar):
```
postgresql+asyncpg://aiengine_user:PASSWORD@/aiengine?host=/cloudsql/project-80a32569-9882-44bc-933:us-central1:aiengine-db
```

### 4. Create service account and secrets

```bash
gcloud iam service-accounts create aiengine-sa \
  --display-name="AIEngine Service Account"

SA="aiengine-sa@project-80a32569-9882-44bc-933.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding project-80a32569-9882-44bc-933 \
  --member="serviceAccount:$SA" --role="roles/cloudsql.client"

# Create secrets
echo -n "sk-proj-..." | gcloud secrets create openai-api-key --data-file=-
openssl rand -hex 32 | gcloud secrets create api-key --data-file=-
echo -n "postgresql+asyncpg://..." | gcloud secrets create database-url --data-file=-
echo -n "postgresql+asyncpg://..." | gcloud secrets create prod-database-url --data-file=-

# Grant access
for SECRET in openai-api-key api-key database-url prod-database-url; do
  gcloud secrets add-iam-policy-binding $SECRET \
    --member="serviceAccount:$SA" \
    --role="roles/secretmanager.secretAccessor"
done
```

### 5. Deploy Cloud Run services

```bash
IMAGE="us-central1-docker.pkg.dev/project-80a32569-9882-44bc-933/aiengine/aiengine:latest"
SA="aiengine-sa@project-80a32569-9882-44bc-933.iam.gserviceaccount.com"
SQL_CONN="project-80a32569-9882-44bc-933:us-central1:aiengine-db"

# Prod
gcloud run deploy aiengine-prod \
  --image=$IMAGE \
  --region=us-central1 \
  --service-account=$SA \
  --add-cloudsql-instances=$SQL_CONN \
  --set-env-vars="ENV=production,LOG_LEVEL=INFO,APPLICATION_WEBHOOK_URL=https://app.onlyhuman.us/" \
  --set-secrets="OPENAI_API_KEY=openai-api-key:latest,API_KEY=api-key:latest,DATABASE_URL=prod-database-url:latest" \
  --cpu=1 --memory=1Gi \
  --timeout=300 \
  --concurrency=20 \
  --min-instances=1 --max-instances=1 \
  --no-cpu-throttling \
  --allow-unauthenticated

# Staging
gcloud run deploy aiengine \
  --image=$IMAGE \
  --region=us-central1 \
  --service-account=$SA \
  --add-cloudsql-instances=$SQL_CONN \
  --set-env-vars="ENV=production,LOG_LEVEL=INFO,APPLICATION_WEBHOOK_URL=https://next-fullstack-template-git-dev-vsp-socratic-sciences.vercel.app" \
  --set-secrets="OPENAI_API_KEY=openai-api-key:latest,API_KEY=api-key:latest,DATABASE_URL=database-url:latest" \
  --cpu=1 --memory=1Gi \
  --timeout=300 \
  --concurrency=20 \
  --min-instances=1 --max-instances=1 \
  --no-cpu-throttling \
  --allow-unauthenticated
```

### 6. Run migrations

Migrations run automatically on startup (Dockerfile `CMD` runs `alembic upgrade head` before starting uvicorn).

To run manually via Cloud SQL proxy:
```bash
cloud-sql-proxy project-80a32569-9882-44bc-933:us-central1:aiengine-db &
DATABASE_URL="postgresql+asyncpg://aiengine_user:PASSWORD@localhost/aiengine" \
  alembic upgrade head
```

---

## Verify

```bash
# Health check
curl https://aiengine-prod-568669320764.us-central1.run.app/health

# View recent logs
gcloud run services logs read aiengine-prod --region=us-central1 --limit=50
```

---

## Rollback

```bash
gcloud run revisions list --service=aiengine-prod --region=us-central1

gcloud run services update-traffic aiengine-prod \
  --to-revisions=REVISION_NAME=100 \
  --region=us-central1
```
