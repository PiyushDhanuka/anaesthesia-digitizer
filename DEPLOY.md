# Deploy to Google Cloud Run

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com aiplatform.googleapis.com

# From the anaesthesia-digitizer folder (where the Dockerfile is):
gcloud run deploy anaesthesia-digitizer \
  --source . --region us-central1 --allow-unauthenticated \
  --memory 2Gi --max-instances 1 --min-instances 1 \
  --set-env-vars GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
```

- `--max-instances 1` is required: the active case, OCR cache and SQLite DB live in one instance's memory/disk.
- The Cloud Run service account needs the role **Vertex AI User** for the Gemini summary
  (or set `GEMINI_API_KEY` instead). Without either, reports use the rule-based summary.
- SQLite on Cloud Run is ephemeral (data is lost on restart). Fine for a demo; mention Firestore/Cloud SQL as next step.
- Open `https://<service-url>/app/index.html` (HTTPS makes the real webcam work) and `/simulator/index.html`.
