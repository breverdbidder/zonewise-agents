#!/bin/bash

# ZoneWise Agents - GitHub Secrets Setup
# Run this AFTER creating Render service and getting deploy hook URL

set -e

REPO="breverdbidder/zonewise-agents"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔐 ZoneWise Agents - GitHub Secrets Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if gh CLI is installed
if ! command -v gh &> /dev/null; then
    echo "❌ GitHub CLI not found. Install: https://cli.github.com/"
    exit 1
fi

# Check if authenticated
if ! gh auth status &> /dev/null; then
    echo "❌ Not authenticated. Run: gh auth login"
    exit 1
fi

echo "📝 Enter the following values (press Enter to skip optional ones):"
echo ""

# Required secrets
read -p "Render Deploy Hook URL (required): " RENDER_DEPLOY_HOOK_URL
read -p "Supabase Service Role Key (required): " SUPABASE_KEY
read -p "Anthropic API Key (required): " ANTHROPIC_API_KEY

# Optional secrets
read -p "Google API Key (optional): " GOOGLE_API_KEY

echo ""
echo "🔄 Setting GitHub Secrets for $REPO..."
echo ""

# Set required secrets
if [ -n "$RENDER_DEPLOY_HOOK_URL" ]; then
    echo "$RENDER_DEPLOY_HOOK_URL" | gh secret set RENDER_DEPLOY_HOOK_URL --repo "$REPO"
    echo "✅ RENDER_DEPLOY_HOOK_URL set"
fi

# Supabase URL (hardcoded as it's consistent)
echo "https://mocerqjnksmhcjzxrewo.supabase.co" | gh secret set SUPABASE_URL --repo "$REPO"
echo "✅ SUPABASE_URL set"

if [ -n "$SUPABASE_KEY" ]; then
    echo "$SUPABASE_KEY" | gh secret set SUPABASE_KEY --repo "$REPO"
    echo "✅ SUPABASE_KEY set"
fi

if [ -n "$ANTHROPIC_API_KEY" ]; then
    echo "$ANTHROPIC_API_KEY" | gh secret set ANTHROPIC_API_KEY --repo "$REPO"
    echo "✅ ANTHROPIC_API_KEY set"
fi

if [ -n "$GOOGLE_API_KEY" ]; then
    echo "$GOOGLE_API_KEY" | gh secret set GOOGLE_API_KEY --repo "$REPO"
    echo "✅ GOOGLE_API_KEY set"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ GitHub Secrets configured successfully!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Next steps:"
echo "1. Push code to trigger deployment"
echo "2. Monitor at: https://dashboard.render.com/"
echo "3. Test API: https://zonewise-agents.onrender.com/health"
echo ""
