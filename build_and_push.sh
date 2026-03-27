PROJECT_ID="project-80a32569-9882-44bc-933"
REGION="us-central1"
SERVICE_NAME="aiengine"

docker build -t $REGION-docker.pkg.dev/$PROJECT_ID/aiengine/aiengine:latest .

docker push $REGION-docker.pkg.dev/$PROJECT_ID/aiengine/aiengine:latest

gcloud run deploy $SERVICE_NAME \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/aiengine/aiengine:latest \
  --region $REGION \
  --project $PROJECT_ID \
  --set-env-vars APPLICATION_WEBHOOK_URL=https://next-fullstack-template-git-dev-vsp-socratic-sciences.vercel.app,ENV=production,LOG_LEVEL=INFO \
  --set-secrets OPENAI_API_KEY=openai-api-key:latest,API_KEY=api-key:latest,DATABASE_URL=database-url:latest
