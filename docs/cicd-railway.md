# CI/CD: GitHub → Railway

Push to `main` triggers a GitHub Actions workflow that runs `railway up` against the **ava-faq-chat** production service.

## One-time setup

### 1. Create a Railway project token

1. Open [Railway](https://railway.com) → project **ava-faq-chat**
2. **Settings → Tokens** (or **Project Settings → Tokens**)
3. **New Token** → name it `github-actions` → environment **production**
4. Copy the token (shown once)

This is a **project token**, not your account `RAILWAY_API_TOKEN`.

### 2. Add the token to GitHub

1. [GitHub repo → Settings → Secrets and variables → Actions](https://github.com/ecalvesbert/AVA_faq_bot/settings/secrets/actions)
2. **New repository secret**
3. Name: `RAILWAY_TOKEN`
4. Value: paste the project token from step 1

### 3. Push the workflow

The workflow lives at `.github/workflows/deploy-railway.yml`. After the secret exists:

```bash
git add .github/workflows/deploy-railway.yml
git commit -m "Add GitHub Actions deploy to Railway."
git push origin main
```

Watch the run under **Actions** on GitHub. A successful run deploys to https://ava-faq-chat-production.up.railway.app

## What stays on Railway (not in git)

These are already configured on the service and are **not** overwritten by deploy:

| Variable | Purpose |
|----------|---------|
| `GENESYS_CLIENT_ID` / `SECRET` | OAuth |
| `AVA_AGENT_ID` / `AVA_VERSION` | Target AVA |
| `PIPELINE_API_KEY` | Admin / ingest API |
| `FIRECRAWL_API_KEY` | Crawl on Railway |
| `/data` volume | Crawls + sync state |

Initial setup: `./deploy_railway.sh` (local, one-time). CI only redeploys the Docker image from git.

## Avoid double deploys

Pick **one** deploy trigger:

| Approach | When to use |
|----------|-------------|
| **GitHub Actions** (this repo) | Deploy logic in git; visible in Actions tab |
| **Railway native GitHub** | Connect repo in Railway service settings |

If Railway is already connected to GitHub for this service, **disconnect it** or leave autodeploy off — otherwise every push may deploy twice.

## Manual redeploy

- **GitHub:** Actions → Deploy to Railway → Run workflow (after adding `workflow_dispatch` if desired)
- **Railway dashboard:** Service → Deployments → Redeploy
- **CLI:** `railway up --detach -y` (with `railway login` or `RAILWAY_API_TOKEN`)

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Project Token not found` | Regenerate token; confirm secret name is exactly `RAILWAY_TOKEN` |
| Workflow skipped / no run | Push must be to `main` |
| Deploy OK but old UI | Hard-refresh browser; check deployment timestamp in Railway |
| CLI auth errors in Actions | Token must be **project** token for **production**, not account token |

Railway IDs in the workflow (safe to commit): project `d99d96ef-…`, environment `afd021e9-…`, service `790998ce-…`. Update these if you recreate the Railway project.
