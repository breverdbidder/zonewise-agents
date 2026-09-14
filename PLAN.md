# PLAN: Ecosystem security gate for zonewise-agents

## Objective
Embed the ecosystem security stack (gitleaks blocking gate, trufflehog nightly verified sweep, zizmor + trivy advisory) into zonewise-agents CI, matching the rollout already merged on biddeed-web, claude-code-telegram-control, cliproxy-gateway, gods-eye-view, and zonewise-web.

## Files Changed
- `.github/workflows/security.yml` (new): 4-job security workflow, pinned-release scanner binaries, SHA-pinned checkout, top-level `permissions: {}`.
- `.gitleaks.toml` (new): shared secret rule set (Telegram bot token, OpenRouter, Mapbox sk., Supabase service-role/PAT, Cloudflare, fal.ai) extending gitleaks defaults.
- `.gitleaksignore` (new): baseline of 1 pre-existing finding triaged dead by a trufflehog verified sweep; gate fails closed on NEW secrets only.
- `.pre-commit-config.yaml` (new): optional local gitleaks gate.

## Approach
Open implementation PR from branch `security-gate`. Gitleaks scans PR diff on pull_request and full history on push (blocking). TruffleHog runs nightly + workflow_dispatch, `--only-verified`, Raw values stripped from output. Zizmor and Trivy run advisory (continue-on-error) for one week, then flip to blocking after the fix wave. No changes to application code, no new runtime dependencies, no secrets added.

## Risks
- Advisory jobs show red in job detail until baseline triage lands (cosmetic; workflow concludes success).
- Full-history gitleaks on push could flag an old commit not in the baseline; mitigation: baseline was generated from an actual full-history scan of this repo.
- Plan-enforcement Gate 1 requires this plan PR to be architect-approved before the implementation PR merges (this document exists for exactly that).

## NOT Doing
- No flipping of zizmor/trivy to blocking mode yet.
- No remediation of the 34 pre-existing zizmor high findings in this repo (separate fix wave).
- No changes to deploy workflows, runner config, or Actions secrets.

## Estimated Complexity
Low - 4 additive config files, no code changes, pattern already proven green on 5 repos.