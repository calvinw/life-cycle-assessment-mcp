# BAFU Database Setup and Deployment

The server needs a pre-built Brightway database (biosphere3 + BAFU + LCIA
methods) to run LCA calculations. This is distributed as a tarball attached to
a GitHub release and downloaded automatically on first boot.

---

## What is in the tarball

`brightway_bafu_v1.tar.gz` (or later versions) contains the entire
`brightway_data/` directory with:

| Database | Size | Source |
|---|---|---|
| `biosphere3` | 4,709 flows | bw2io default |
| `bafu` | 11,947 processes | BAFU:2026 EcoSpold V1 from openLCA Nexus |
| LCIA methods | 1,246 methods | bw2io default (EF v3.1, ReCiPe, TRACI, etc.) |

---

## How the server uses it

On startup, `lca_engine.py` calls `_ensure_databases()` which checks if `bafu`
is present. If not, it downloads the tarball from the GitHub release and
extracts it into `brightway_data/`. This only happens once — subsequent boots
skip it entirely.

---

## How to build a new tarball (local)

Do this when upgrading to a new BAFU version or adding a new database.

### Prerequisites

Two input files in `data/bafu/` (gitignored):
- `BAFU-2026 v1_ecoSpold v1.zip` — download free from [openLCA Nexus](https://nexus.openlca.org/database/BAFU-2026)
- `elementary_flows_mapping.csv` — from [romainsacchi/BAFU2BW](https://github.com/romainsacchi/BAFU2BW)

### Steps

```bash
# 1. Import everything into brightway_data/ (takes ~5-10 min, idempotent)
python scripts/import_bafu.py

# 2. Verify the databases look correct
python -c "
import os; os.environ['BRIGHTWAY2_DIR'] = 'brightway_data'
import bw2data as bd
bd.projects.set_current('lca_server')
for name in bd.databases:
    print(name, len(bd.Database(name)))
print('methods:', len(list(bd.methods)))
"

# 3. Create the tarball (exclude the foreground scratch database and backups)
tar -czf brightway_bafu_v1.tar.gz \
    --exclude='brightway_data/lca_server.*/backups' \
    --exclude='brightway_data/lca_server.*/databases/foreground*' \
    brightway_data/

# Check compressed size
du -sh brightway_bafu_v1.tar.gz
```

### Upload to GitHub releases

```bash
# Create a new release and upload the tarball
gh release create lca-data-v1 brightway_bafu_v1.tar.gz \
    --title "LCA Database v1 — BAFU 2026" \
    --notes "biosphere3 + BAFU:2026 + 1246 LCIA methods"
```

Then update the `TARBALL_URL` constant in `lca_engine.py` to point to the new
release asset URL, e.g.:
```python
TARBALL_URL = (
    "https://github.com/calvinw/life-cycle-assessment-mcp"
    "/releases/download/lca-data-v3/brightway_bafu_v2.tar.gz"
)
```

---

## How to update to a new BAFU version

1. Download the new EcoSpold V1 zip from openLCA Nexus
2. Delete the old `bafu` database: `python -c "import bw2data as bd; bd.projects.set_current('lca_server'); del bd.databases['bafu']"`
3. Place the new zip in `data/bafu/` (remove or rename the old one)
4. Re-run `python scripts/import_bafu.py` — it skips biosphere3 and LCIA methods (already present) and only re-imports bafu
5. Build a new tarball and upload as a new GitHub release (e.g. `lca-data-v2`)
6. Update `TARBALL_URL` in `lca_engine.py` and redeploy

---

## Troubleshooting

**Import fails with "no XML files"** — the zip may have a different internal
folder structure. Check with `unzip -l data/bafu/*.zip | head -20`.

**LCIA scores are zero** — likely a biosphere flow name mismatch. Re-run
`import_bafu.py` with the correct `elementary_flows_mapping.csv`.

**Tarball download times out on server** — the GitHub release asset URL must
be the direct download link (not the HTML page). Use `gh release view` to get
the correct URL.
