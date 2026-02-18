# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅ Yes    |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Email: ariel@everestcapitalusa.com

Include in your report:
- Description of the vulnerability
- Steps to reproduce
- Potential impact assessment
- Suggested fix (if known)

**Response timeline:**
- Acknowledgement within 48 hours
- Status update within 7 days
- Fix deployed within 30 days for confirmed issues

## Security Controls

### Data Protection
- All API keys stored as GitHub Secrets or Modal secrets — never in code
- Supabase Row-Level Security (RLS) enforced on all user-facing tables
- Environment files (`.env`, `.env.production`) blocked via `.gitignore`

### Scraper Security
- Scrapers operate within workspace sandbox only
- No credentials logged or exposed in output
- AgentQL API key rotated if compromised

### Access Control
- Supabase auth gates all user-facing API routes
- Service role key never exposed to frontend
- Mapbox token scoped to allowed URLs in Mapbox dashboard

## Known Non-Issues

- The `NEXT_PUBLIC_MAPBOX_TOKEN` in the web app is a public token intentionally
  scoped to the `zonewise.ai` domain in the Mapbox dashboard. Rotating it does
  not improve security unless the domain restriction is also updated.

## Dependency Policy

Dependencies are audited on every PR via GitHub Dependabot.  
Critical CVEs block merges to `main`.
