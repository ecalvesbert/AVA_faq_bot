# Artifacts (local / Railway volume)

Generated at runtime — **not committed to git**. Layout:

```
artifacts/
├── crawls/{hostname}/           # raw Firecrawl markdown + manifest.json
├── crawls/{hostname}/processed/ # cleaned files for Knowledge Fabric upload
├── knowledge-sync-state.json    # Genesys source ID + last sync
├── knowledge-config-state.json  # Knowledge setting + AVA wiring
└── jobs/{job-id}.json           # pipeline run history (Railway: under DATA_DIR/jobs)
```

Create by running the pipeline locally or via the web app **Admin** tab.

Push local crawls to Railway:

```bash
export PIPELINE_API_KEY=your-key
python3 sync_local_to_railway.py
```
