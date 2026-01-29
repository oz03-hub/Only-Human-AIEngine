# GCP Cloud Run Deployment Guide

This guide walks through deploying AIEngine to Google Cloud Platform using Cloud Run and Cloud SQL.

## Prerequisites

1. **GCP Project** with billing enabled
2. **gcloud CLI** installed and authenticated: `gcloud auth login`
3. **Docker** installed locally
4. **GCP APIs enabled**:
   ```bash
   gcloud services enable \
     run.googleapis.com \
     sqladmin.googleapis.com \
     secretmanager.googleapis.com \
     cloudbuild.googleapis.com \
     artifactregistry.googleapis.com
   ```

## Step 1: Set Up Environment Variables

```bash
export PROJECT_ID="your-gcp-project-id"
export REGION="us-central1"  # Choose your region
export SERVICE_NAME="aiengine"
export DB_INSTANCE_NAME="aiengine-db"
export DB_NAME="aiengine"
export DB_USER="aiengine_user"

gcloud config set project $PROJECT_ID
```

## Step 2: Create Cloud SQL Instance

### 2.1 Create PostgreSQL instance

```bash
gcloud sql instances create $DB_INSTANCE_NAME \
  --database-version=POSTGRES_16 \
  --tier=db-f1-micro \
  --region=$REGION \
  --storage-type=SSD \
  --storage-size=10GB \
  --storage-auto-increase \
  --backup-start-time=03:00 \
  --maintenance-window-day=SUN \
  --maintenance-window-hour=4
```

**Note**: Use `db-f1-micro` for dev/testing. For production, use `db-custom-2-7680` or higher.

### 2.2 Create database and user

```bash
# Set root password
gcloud sql users set-password postgres \
  --instance=$DB_INSTANCE_NAME \
  --password="CHANGE_ME_SECURE_PASSWORD"

# Create database
gcloud sql databases create $DB_NAME \
  --instance=$DB_INSTANCE_NAME

# Create application user
gcloud sql users create $DB_USER \
  --instance=$DB_INSTANCE_NAME \
  --password="CHANGE_ME_SECURE_PASSWORD"
```

### 2.3 Get connection name

```bash
gcloud sql instances describe $DB_INSTANCE_NAME --format="value(connectionName)"
# Output: PROJECT_ID:REGION:INSTANCE_NAME
```

## Step 3: Store Secrets in Secret Manager

```bash
# Create OpenAI API Key secret
echo -n "sk-proj-YOUR_OPENAI_KEY" | \
  gcloud secrets create openai-api-key --data-file=-

# Create API Key secret (generate secure key first)
openssl rand -base64 32 | \
  gcloud secrets create api-key --data-file=-

# Grant Cloud Run access to secrets
gcloud secrets add-iam-policy-binding openai-api-key \
  --member="serviceAccount:aiengine-sa@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding api-key \
  --member="serviceAccount:aiengine-sa@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

## Step 4: Create Service Account

```bash
# Create service account
gcloud iam service-accounts create aiengine-sa \
  --display-name="AIEngine Service Account"

# Grant Cloud SQL Client role
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:aiengine-sa@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/cloudsql.client"
```

## Step 5: Build and Push Docker Image

### 5.1 Create Artifact Registry repository

```bash
gcloud artifacts repositories create aiengine \
  --repository-format=docker \
  --location=$REGION \
  --description="AIEngine Docker repository"
```

### 5.2 Configure Docker authentication

```bash
gcloud auth configure-docker $REGION-docker.pkg.dev
```

### 5.3 Build and push image

```bash
# Build image
docker build -t $REGION-docker.pkg.dev/$PROJECT_ID/aiengine/aiengine:latest .

# Push to Artifact Registry
docker push $REGION-docker.pkg.dev/$PROJECT_ID/aiengine/aiengine:latest
```

## Step 6: Update Cloud Run Service Configuration

Edit `cloudrun-service.yaml` and replace placeholders:
- `PROJECT_ID` → Your GCP project ID
- `REGION` → Your chosen region (e.g., us-central1)
- `INSTANCE_NAME` → Your Cloud SQL instance name
- `USER` → Database user (e.g., aiengine_user)
- `PASSWORD` → Database password
- `DATABASE` → Database name (e.g., aiengine)

## Step 7: Deploy to Cloud Run

### Option A: Using service.yaml (recommended)

```bash
gcloud run services replace cloudrun-service.yaml \
  --region=$REGION
```

### Option B: Using gcloud command

```bash
gcloud run deploy $SERVICE_NAME \
  --image=$REGION-docker.pkg.dev/$PROJECT_ID/aiengine/aiengine:latest \
  --platform=managed \
  --region=$REGION \
  --service-account=aiengine-sa@$PROJECT_ID.iam.gserviceaccount.com \
  --add-cloudsql-instances=$PROJECT_ID:$REGION:$DB_INSTANCE_NAME \
  --set-env-vars="DATABASE_URL=postgresql+asyncpg://$DB_USER:PASSWORD@/$DB_NAME?host=/cloudsql/$PROJECT_ID:$REGION:$DB_INSTANCE_NAME" \
  --set-secrets="OPENAI_API_KEY=openai-api-key:latest,API_KEY=api-key:latest" \
  --set-env-vars="ENV=production,LOG_LEVEL=INFO,MODEL_PATH=models/rf_classifier.pkl,LLM_MODEL=gpt-4o-mini" \
  --cpu=2 \
  --memory=2Gi \
  --timeout=300 \
  --min-instances=0 \
  --max-instances=10 \
  --allow-unauthenticated
```

## Step 8: Run Database Migrations

The Dockerfile automatically runs migrations on startup via:
```bash
alembic upgrade head
```

To manually run migrations:

```bash
# Connect to Cloud SQL via proxy
cloud-sql-proxy $PROJECT_ID:$REGION:$DB_INSTANCE_NAME &

# Run migrations locally
DATABASE_URL="postgresql+asyncpg://$DB_USER:PASSWORD@localhost/$DB_NAME" \
  alembic upgrade head
```

## Step 9: Verify Deployment

```bash
# Get service URL
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME \
  --region=$REGION \
  --format="value(status.url)")

echo "Service URL: $SERVICE_URL"

# Test health endpoint
curl $SERVICE_URL/health

# Test API with authentication
curl -H "X-API-Key: YOUR_API_KEY" $SERVICE_URL/api/endpoint
```

## Step 10: Set Up Continuous Deployment (Optional)

### Using Cloud Build

Create `cloudbuild.yaml`:

```yaml
steps:
  # Build Docker image
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', '${_REGION}-docker.pkg.dev/$PROJECT_ID/aiengine/aiengine:$SHORT_SHA', '.']

  # Push to Artifact Registry
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', '${_REGION}-docker.pkg.dev/$PROJECT_ID/aiengine/aiengine:$SHORT_SHA']

  # Deploy to Cloud Run
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
      - 'run'
      - 'deploy'
      - '${_SERVICE_NAME}'
      - '--image=${_REGION}-docker.pkg.dev/$PROJECT_ID/aiengine/aiengine:$SHORT_SHA'
      - '--region=${_REGION}'
      - '--platform=managed'

substitutions:
  _SERVICE_NAME: aiengine
  _REGION: us-central1

images:
  - '${_REGION}-docker.pkg.dev/$PROJECT_ID/aiengine/aiengine:$SHORT_SHA'
```

Connect to GitHub:
```bash
gcloud builds triggers create github \
  --repo-name=AIEngine \
  --repo-owner=YOUR_GITHUB_USERNAME \
  --branch-pattern="^main$" \
  --build-config=cloudbuild.yaml
```

## Monitoring and Logging

### View logs
```bash
gcloud run services logs read $SERVICE_NAME --region=$REGION --limit=50
```

### Monitor in Cloud Console
- **Cloud Run**: https://console.cloud.google.com/run
- **Cloud SQL**: https://console.cloud.google.com/sql
- **Logs**: https://console.cloud.google.com/logs

## Cost Optimization

### Development/Staging
- Cloud SQL: `db-f1-micro` (~$10/month)
- Cloud Run: `minScale: 0` (scales to zero when idle)
- CPU: 1 CPU, 512Mi memory

### Production
- Cloud SQL: `db-custom-2-7680` or higher with high availability
- Cloud Run: `minScale: 1` (always-on for faster response)
- CPU: 2-4 CPUs, 2-4Gi memory

## Troubleshooting

### Cannot connect to Cloud SQL
1. Verify Cloud SQL Proxy annotation in `cloudrun-service.yaml`
2. Check service account has `roles/cloudsql.client` role
3. Verify `DATABASE_URL` format matches: `postgresql+asyncpg://USER:PASSWORD@/DB?host=/cloudsql/CONNECTION_NAME`

### Migrations failing on startup
1. Manually run migrations via Cloud SQL Proxy
2. Check database user has necessary permissions
3. Review logs: `gcloud run services logs read $SERVICE_NAME`

### Secrets not accessible
1. Verify secrets exist: `gcloud secrets list`
2. Check service account has `roles/secretmanager.secretAccessor`
3. Verify secret references in `cloudrun-service.yaml`

## Rollback

```bash
# List revisions
gcloud run revisions list --service=$SERVICE_NAME --region=$REGION

# Rollback to previous revision
gcloud run services update-traffic $SERVICE_NAME \
  --to-revisions=REVISION_NAME=100 \
  --region=$REGION
```

## Cleanup

```bash
# Delete Cloud Run service
gcloud run services delete $SERVICE_NAME --region=$REGION

# Delete Cloud SQL instance
gcloud sql instances delete $DB_INSTANCE_NAME

# Delete secrets
gcloud secrets delete openai-api-key
gcloud secrets delete api-key

# Delete Artifact Registry repository
gcloud artifacts repositories delete aiengine --location=$REGION
```
