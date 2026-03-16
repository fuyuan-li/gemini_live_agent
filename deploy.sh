#!/bin/bash
# deploy.sh — Deploy the Live Agent Companion server to Google Cloud Run
#
# Prerequisites:
#   - gcloud CLI installed and authenticated (gcloud auth login)
#   - GOOGLE_API_KEY stored in Secret Manager as "GOOGLE_API_KEY"
#     (one-time manual step: gcloud secrets create GOOGLE_API_KEY --data-file=- <<< "YOUR_KEY")
#
# Usage:
#   ./deploy.sh [PROJECT_ID] [REGION]
#
# Examples:
#   ./deploy.sh                                  # uses gcloud default project, us-central1
#   ./deploy.sh my-project-id                    # explicit project
#   ./deploy.sh my-project-id europe-west1       # explicit project + region

set -e

SERVICE="adk-agent-orchestrator"
PROJECT_ID="${1:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${2:-us-central1}"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}▶${NC} $*"; }
warn()  { echo -e "${YELLOW}!${NC} $*"; }
error() { echo -e "${RED}✗${NC} $*"; exit 1; }

[ -z "$PROJECT_ID" ] && error "No GCP project set. Run: gcloud config set project YOUR_PROJECT_ID"

echo ""
echo "  Live Agent Companion — Cloud Run Deploy"
echo "  ─────────────────────────────────────────"
echo "  Service : $SERVICE"
echo "  Project : $PROJECT_ID"
echo "  Region  : $REGION"
echo ""

# ── 1. Enable required GCP APIs ───────────────────────────────────────────────
info "Enabling required GCP APIs..."
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    secretmanager.googleapis.com \
    --project="$PROJECT_ID" \
    --quiet

# ── 2. Verify the secret exists ───────────────────────────────────────────────
info "Verifying GOOGLE_API_KEY secret exists in Secret Manager..."
if ! gcloud secrets describe GOOGLE_API_KEY --project="$PROJECT_ID" &>/dev/null; then
    error "Secret 'GOOGLE_API_KEY' not found in project '$PROJECT_ID'.\n  Create it with:\n  gcloud secrets create GOOGLE_API_KEY --project=$PROJECT_ID --data-file=- <<< \"YOUR_KEY\""
fi

# ── 3. Deploy to Cloud Run ────────────────────────────────────────────────────
info "Deploying $SERVICE to Cloud Run (this builds the container from source)..."
gcloud run deploy "$SERVICE" \
    --source . \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --allow-unauthenticated \
    --set-secrets="GOOGLE_API_KEY=GOOGLE_API_KEY:latest" \
    --quiet

# ── 4. Print service URL ──────────────────────────────────────────────────────
echo ""
SERVICE_URL=$(gcloud run services describe "$SERVICE" \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --format="value(status.url)")
echo -e "  ${GREEN}Deploy complete!${NC}"
echo ""
echo "  Service URL: $SERVICE_URL"
echo "  WebSocket:   ${SERVICE_URL/https/wss}/ws/local_user"
echo ""
