PROJECT_ID="project-80a32569-9882-44bc-933"
REGION="us-central1"

docker build -t $REGION-docker.pkg.dev/$PROJECT_ID/aiengine/aiengine:latest .

docker push $REGION-docker.pkg.dev/$PROJECT_ID/aiengine/aiengine:latest
