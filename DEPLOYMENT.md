# ZoneWise Agents — Deployment Guide

**Primary host: Google Cloud Run (free tier, scale-to-zero).**  
Render is deprecated for this service (workspace billing dispute / suspension). Do **not** use Render.

---

## Google Cloud Run (FREE)

### Why Cloud Run
- Scale-to-zero (`--min-instances=0`) → $0 when idle
- HTTPS URL auto-provisioned
- Docker/FastAPI friendly; `PORT` injected by platform
- Generous free tier (CPU/memory/requests) for low traffic

### Dockerfile
Image listens on `$PORT` (fallback `8000`):

```dockerfile
CMD uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Health: `GET /health` → `{"status":"healthy"|"degraded", ...}`.  
`status` is `healthy` when `SUPABASE_KEY` is set (server reads **`SUPABASE_KEY`**, not `SUPABASE_SERVICE_KEY`).

### One-shot local deploy (after gcloud login)

```bash
export PATH="$HOME/google-cloud-sdk/bin:$PATH"
gcloud auth login
gcloud auth application-default login

# Export app secrets into the shell (never commit). Map names carefully:
export SUPABASE_URL='...'
export SUPABASE_SERVICE_KEY='...'   # mapped to SUPABASE_KEY in container
export ANTHROPIC_API_KEY='...'
# optional: TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID

./cloudrun/deploy.sh zonewise-agents us-east1
```

Or equivalent flags:

```bash
gcloud run deploy zonewise-agents \
  --source=. \
  --region=us-east1 \
  --platform=managed \
  --allow-unauthenticated \
  --memory=512Mi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=3 \
  --port=8000 \
  --env-vars-file=<(printf 'SUPABASE_URL=%s\nSUPABASE_KEY=%s\nANTHROPIC_API_KEY=%s\n' \
      "$SUPABASE_URL" "$SUPABASE_SERVICE_KEY" "$ANTHROPIC_API_KEY")
```

Reference: `cloudrun/service.yaml`, `cloudrun/deploy.sh`.

### GitHub Actions auto-deploy
Workflow template: `cloudrun/deploy-cloudrun.yml` — copy to `.github/workflows/deploy-cloudrun.yml` once a GitHub token with `workflow` scope is available (or paste via GitHub UI).

1. Create a GCP project (e.g. `zonewise-agents`) and **link a billing account** (required even for free tier).
2. Enable APIs: Cloud Run, Cloud Build, Artifact Registry (script/Action does this).
3. Add GitHub Actions secrets (repo → Settings → Secrets):

| Secret | Purpose |
|--------|---------|
| `GCP_PROJECT_ID` | GCP project id |
| `GCP_SA_KEY` **or** WIF trio | Auth (`GCP_WORKLOAD_IDENTITY_PROVIDER` + `GCP_SERVICE_ACCOUNT`) |
| `SUPABASE_URL` | already set |
| `SUPABASE_SERVICE_KEY` | already set → mapped to `SUPABASE_KEY` |
| `ANTHROPIC_API_KEY` | already set |

4. Merge to `main` or run **Actions → Deploy to Cloud Run → Run workflow**.
5. Until `GCP_*` secrets exist, the workflow **skips** (green) with a setup message.

### Cost / free-tier posture
- `--min-instances=0` (scale-to-zero)
- 512Mi memory, 1 CPU, max 3 instances
- Idle ≈ **$0/month** within Always Free allowances
- Billing account must still be attached to the project

### Verify
```bash
curl https://YOUR-SERVICE-XXXX-ue.a.run.app/health
# Expect: {"status":"healthy","database":"connected",...} or degraded if key missing
```

### Point zonewise-web at Cloud Run
In `zonewise-web`:
1. Set Cloudflare Worker / Pages secret `AGENTS_BACKEND_URL` = Cloud Run HTTPS URL (no trailing slash).
2. Optionally change default fallback in `app/api/chat/route.ts` from `https://zonewise-agents.onrender.com` to the Cloud Run URL.

---

## Legacy: Render (DO NOT USE)

Workspace suspended / unpaid invoice dispute. Kept only for historical reference.

Previous URL: `https://zonewise-agents.onrender.com`  
Config: `render.yaml`, workflow `deploy-render.yml` (leave disabled / ignore).

### Old Render env mapping
- Render used `SUPABASE_KEY` directly
- `.env.example` documents `SUPABASE_SERVICE_KEY` — same value; Cloud Run deploy maps it

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Container won't listen | Ensure Dockerfile uses `${PORT:-8000}` shell form |
| `/health` → `degraded` / `no_key` | Set `SUPABASE_KEY` (from `SUPABASE_SERVICE_KEY`) |
| Image build huge / Playwright | Package installs without browsers; `/health` does not need browsers. If build fails, remove `playwright`/`agentql` from runtime image |
| gcloud auth errors | `gcloud auth login` + `gcloud auth application-default login` on the agent box desktop |
| Billing required | Enable billing on the GCP project (free tier still applies with min instances 0) |
