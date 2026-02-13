# ZoneWise Agents - Render Deployment Guide

## 🚀 ONE-TIME SETUP (2 minutes)

### Step 1: Create Render Service
1. Go to https://render.com
2. Click "New +" → "Web Service"
3. Click "Build and deploy from a Git repository"
4. Select GitHub repo: `breverdbidder/zonewise-agents`
5. Configure:
   - **Name**: `zonewise-agents`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn server.main:app --host 0.0.0.0 --port $PORT`
   - **Plan**: Free (or Starter $7/mo for production)

### Step 2: Add Environment Variables
In Render dashboard → Environment section, add:

```bash
SUPABASE_URL=https://mocerqjnksmhcjzxrewo.supabase.co
SUPABASE_KEY=[from GitHub Secrets or Supabase dashboard]
ANTHROPIC_API_KEY=[your Anthropic API key]
GOOGLE_API_KEY=[optional - for Google services]
```

### Step 3: Get Deploy Hook URL
1. In Render service settings → "Settings" tab
2. Scroll to "Deploy Hook"
3. Copy the URL (looks like: `https://api.render.com/deploy/srv-xxx...`)

### Step 4: Add to GitHub Secrets
```bash
# Using GitHub CLI or web UI
gh secret set RENDER_DEPLOY_HOOK_URL --repo breverdbidder/zonewise-agents

# Or via web:
# GitHub repo → Settings → Secrets → Actions → New secret
# Name: RENDER_DEPLOY_HOOK_URL
# Value: [paste deploy hook URL]
```

---

## ✅ AFTER SETUP - 100% Automated

Every push to `main` branch will:
1. Trigger GitHub Action
2. Call Render Deploy Hook
3. Render rebuilds and deploys automatically
4. Available at: `https://zonewise-agents.onrender.com`

---

## 🔍 Verification

### Test Health Endpoint
```bash
curl https://zonewise-agents.onrender.com/health
# Expected: {"status": "healthy", "version": "1.1.0"}
```

### Test Streaming Chat
```bash
curl -X POST https://zonewise-agents.onrender.com/api/query/stream \
  -H "Content-Type: application/json" \
  -d '{"query":"What are setbacks for R-1 in Brevard County?"}'
```

### Test Stats API
```bash
curl https://zonewise-agents.onrender.com/api/stats
```

---

## 📊 Monitoring

- **Render Dashboard**: https://dashboard.render.com/
- **Logs**: Render Dashboard → zonewise-agents → Logs tab
- **Metrics**: Auto-tracked by Render (CPU, memory, response times)

---

## 🔄 Manual Deploy (if needed)

```bash
# Trigger via GitHub Actions UI
# Go to: Actions → Deploy to Render → Run workflow

# Or via CLI
gh workflow run deploy-render.yml --repo breverdbidder/zonewise-agents
```

---

## 💰 Cost Estimate

- **Free Tier**: $0/month (spins down after 15min inactivity, 750hrs/month)
- **Starter**: $7/month (always on, better performance)
- **Production**: Recommended Starter for ZoneWise launch

---

## 🐛 Troubleshooting

### Build Fails
- Check Python version (should be 3.11)
- Verify requirements.txt is present
- Check Render build logs

### Health Check Fails
- Verify Start Command includes `--host 0.0.0.0`
- Check PORT environment variable is used
- Ensure `/health` endpoint returns 200

### API Returns Errors
- Verify all environment variables are set
- Check Supabase credentials are correct
- Test Anthropic API key separately

---

## 📝 Next Steps After Deployment

1. Update zonewise-web to use production API URL
2. Configure CORS if needed
3. Set up monitoring/alerts
4. Load test with expected traffic

