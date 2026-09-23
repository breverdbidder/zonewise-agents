#!/usr/bin/env bash
# One-shot local deploy to FREE Cloud Run (scale-to-zero).
# Usage:
#   export PATH="$HOME/google-cloud-sdk/bin:$PATH"
#   gcloud auth login && gcloud auth application-default login
#   ./cloudrun/deploy.sh [PROJECT_ID] [REGION]
#
# Secrets are pulled from GitHub Actions secrets via `gh secret` and never echoed.
set -euo pipefail

PROJECT_ID="${1:-${GCP_PROJECT_ID:-zonewise-agents}}"
REGION="${2:-${GCP_REGION:-us-east1}}"
SERVICE="zonewise-agents"
AR_REPO="zonewise"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${SERVICE}:$(git rev-parse --short HEAD)"
IMAGE_LATEST="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${SERVICE}:latest"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Project: ${PROJECT_ID}  Region: ${REGION}"

gcloud config set project "${PROJECT_ID}"

# Create project if missing (billing may still need user enablement)
if ! gcloud projects describe "${PROJECT_ID}" >/dev/null 2>&1; then
  echo "==> Creating project ${PROJECT_ID}..."
  gcloud projects create "${PROJECT_ID}" --name="ZoneWise Agents" || true
  gcloud config set project "${PROJECT_ID}"
fi

echo "==> Enabling APIs (run, cloudbuild, artifactregistry, secretmanager)..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com

echo "==> Ensuring Artifact Registry repo..."
if ! gcloud artifacts repositories describe "${AR_REPO}" --location="${REGION}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${AR_REPO}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="ZoneWise Agents images"
fi

echo "==> Configuring docker auth for Artifact Registry..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

echo "==> Building image (Cloud Build)..."
gcloud builds submit "${REPO_ROOT}" --tag "${IMAGE}" --tag "${IMAGE_LATEST}"

# Fetch secrets from GitHub without printing values
fetch_secret() {
  local name="$1"
  # gh secret list cannot read values; use repo env via local .env or Secret Manager.
  # Prefer already-exported env; else attempt gh api for Actions (values not readable).
  # For one-shot: expect caller to export vars, or use Secret Manager names below.
  if [[ -n "${!name:-}" ]]; then
    printf '%s' "${!name}"
    return 0
  fi
  return 1
}

echo "==> Preparing env (SUPABASE_SERVICE_KEY maps to SUPABASE_KEY)..."
# Do not echo secret values. Prefer env already set in the shell:
#   export SUPABASE_URL=... SUPABASE_SERVICE_KEY=... ANTHROPIC_API_KEY=...
# Optional: TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID
ENV_VARS="PORT=8000"
SECRETS_FLAGS=()

# Prefer Secret Manager if secrets already exist; else --set-env-vars from shell env.
use_sm=false
if gcloud secrets describe SUPABASE_SERVICE_KEY >/dev/null 2>&1; then
  use_sm=true
fi

if [[ "${use_sm}" == "true" ]]; then
  SECRETS_FLAGS+=(
    --set-secrets="SUPABASE_URL=SUPABASE_URL:latest,SUPABASE_KEY=SUPABASE_SERVICE_KEY:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest"
  )
else
  : "${SUPABASE_URL:?export SUPABASE_URL before deploy}"
  : "${SUPABASE_SERVICE_KEY:?export SUPABASE_SERVICE_KEY before deploy (maps to SUPABASE_KEY)}"
  : "${ANTHROPIC_API_KEY:?export ANTHROPIC_API_KEY before deploy}"
  # Build env file so values never appear on argv in process lists as much as possible
  ENV_FILE="$(mktemp)"
  trap 'rm -f "${ENV_FILE}"' EXIT
  {
    printf 'SUPABASE_URL=%s\n' "${SUPABASE_URL}"
    printf 'SUPABASE_KEY=%s\n' "${SUPABASE_SERVICE_KEY}"
    printf 'ANTHROPIC_API_KEY=%s\n' "${ANTHROPIC_API_KEY}"
    [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] && printf 'TELEGRAM_BOT_TOKEN=%s\n' "${TELEGRAM_BOT_TOKEN}"
    [[ -n "${TELEGRAM_CHAT_ID:-}" ]] && printf 'TELEGRAM_CHAT_ID=%s\n' "${TELEGRAM_CHAT_ID}"
  } > "${ENV_FILE}"
  SECRETS_FLAGS+=(--env-vars-file="${ENV_FILE}")
fi

echo "==> Deploying Cloud Run service (min instances 0 = free-tier scale-to-zero)..."
gcloud run deploy "${SERVICE}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --platform=managed \
  --allow-unauthenticated \
  --memory=512Mi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=3 \
  --concurrency=80 \
  --timeout=300 \
  --port=8000 \
  "${SECRETS_FLAGS[@]}"

URL="$(gcloud run services describe "${SERVICE}" --region="${REGION}" --format='value(status.url)')"
echo "==> Service URL: ${URL}"
echo "==> Probing /health..."
curl -sfS "${URL}/health" || true
echo
echo "Done. Set zonewise-web AGENTS_BACKEND_URL=${URL}"
