# Getting started (new session checklist)

Use this after cloning [AVA_faq_bot](https://github.com/ecalvesbert/AVA_faq_bot). Estimated time: **30–60 minutes** for a full FAQ bot on your org.

## 1. Prerequisites

| Requirement | Notes |
|-------------|--------|
| Genesys Cloud org | AI Experience + Knowledge Fabric |
| OAuth client | Scopes: `agentic-virtualagents-internal`, Knowledge upload APIs |
| Agentic Virtual Agent | Published version with a **KnowledgeSetting** tool |
| Python 3.10+ | 3.12 for Docker/Railway |
| Optional: Firecrawl API key | Better crawl limits ([firecrawl.dev](https://www.firecrawl.dev)) |
| Optional: Railway account | For hosted chat + admin |

## 2. Genesys auth (local CLI)

```bash
./setup_auth.sh
# or export GENESYS_CLIENT_ID / GENESYS_CLIENT_SECRET
```

Profile lives in `~/.gc/config.toml` (not committed).

## 3. End-to-end FAQ pipeline (CLI)

Replace the site URL with your FAQ/marketing site:

```bash
# 1. Crawl (homepage + one level of links)
python3 firecrawl_demo.py crawl-shallow "https://www.example.com/" \
  --output-dir artifacts/crawls/www.example.com

# 2. Clean / structure for Knowledge Fabric
python3 process_crawl.py \
  --input-dir artifacts/crawls/www.example.com \
  --output-dir artifacts/crawls/www.example.com/processed

# 3. Upload to Genesys Knowledge Fabric
python3 sync_faq_to_genesys.py \
  --input-dir artifacts/crawls/www.example.com/processed

# 4. Create knowledge setting + wire AVA tool (once per agent)
python3 setup_knowledge_config.py \
  --agent-id YOUR_AVA_ID \
  --version YOUR_DRAFT_VERSION \
  --publish
```

State files: `artifacts/knowledge-sync-state.json`, `artifacts/knowledge-config-state.json`.

## 4. Local web chat + Admin

```bash
pip install -r requirements.txt
cp .env.railway.example .env   # fill GENESYS_* and AVA_*
./run_web.sh
```

- **Chat:** http://localhost:8080  
- **Admin:** http://localhost:8080/?tab=admin (manual ingest + content browser)

AVA chat requires **Studio protocol** (`AVA_STUDIO_MODE=1`): NoOp greeting, `previousTurn` chaining, tool follow-up turns. See `app/genesys_ava.py`.

## 5. Deploy to Railway

```bash
npm install -g @railway/cli
export RAILWAY_API_TOKEN=...          # Account token, Workspace: "No workspace"
export RAILWAY_WORKSPACE="Your Workspace Name"
export USE_GC_PROFILE=1               # or set GENESYS_CLIENT_ID/SECRET
./deploy_railway.sh
```

Script creates project, deploys Docker image, sets env vars, mounts `/data` volume, prints **PIPELINE_API_KEY**.

**Ongoing deploys:** push to `main` triggers GitHub Actions → Railway (see [docs/cicd-railway.md](docs/cicd-railway.md)). One-time: add `RAILWAY_TOKEN` project secret to GitHub.

Sync existing local crawls to production:

```bash
export PIPELINE_API_KEY=...
python3 sync_local_to_railway.py --remote https://your-app.up.railway.app
```

## 6. Wire AVA in AI Studio

1. **Tools** → add **KnowledgeSetting** pointing at your knowledge configuration  
2. **Instructions** → answer from retrieved knowledge; end with `Source: {url}`  
3. **Publish** a new version; set `AVA_VERSION` on Railway to match  

## 7. Test

```bash
# CLI session (Studio-aligned)
./ava_interactive.sh start-studio
./ava_interactive.sh say "What is your product?"

# Or use the web chat UI
```

## Reference docs in this repo

| Doc | Purpose |
|-----|---------|
| [README.md](README.md) | Overview + command index |
| [AVA-SESSION-GUIDE.md](AVA-SESSION-GUIDE.md) | AVA Session API deep dive |
| [docs/](docs/) | HAR analysis, deployment checks, logging |

## Common IDs to collect

- **AVA agent ID** — AI Studio → Agentic Virtual Agents  
- **Knowledge source ID** — after first `sync_faq_to_genesys.py` (in state file)  
- **Knowledge setting ID** — after `setup_knowledge_config.py`  
- **Pipeline API key** — printed by `deploy_railway.sh` or set in Railway variables  
