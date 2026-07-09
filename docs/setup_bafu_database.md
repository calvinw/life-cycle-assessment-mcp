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

**Requires Python 3.11.** The import script is incompatible with Python 3.14+
due to a `bw2io`/`bw2data` type mismatch in `bw2setup`. The Docker container
uses Python 3.11 and is the safest environment to run this.

### Input files in `data/bafu/` (gitignored)

Three zip formats are available from [openLCA Nexus](https://nexus.openlca.org/database/BAFU-2026):

| File | Used? | Notes |
|---|---|---|
| `BAFU-2026 v1_ecoSpold v1.zip` | **Yes** | Used by `import_bafu.py` |
| `BAFU-2026 v1 openLCA_JSON.zip` | No | JSON-LD format; potential future use with `openlca2bw` |
| `BAFU-2026 v1_openLCA.zip` | No | Native openLCA format; requires a running openLCA instance |

You also need `elementary_flows_mapping.csv` from
[romainsacchi/BAFU2BW](https://github.com/romainsacchi/BAFU2BW) — this maps
BAFU biosphere flow names/categories to their biosphere3 equivalents.

### Known import losses

The EcoSpold V1 format has no UUIDs for technosphere cross-references, so
linking is name+location based. A small number of exchanges are dropped:

- **~8,774 total unlinked edges dropped** (246 unique biosphere flows, 5 technosphere)
- Biosphere losses are mostly noise flows (`Noise, road, lorry...`) and a few
  obscure flows with missing category mappings in `elementary_flows_mapping.csv`
- Technosphere losses are 5 processes (ENTSO-E electricity, direct air capture)
  that don't exist in BAFU itself
- **94,072 biosphere flows successfully remapped** via the crosswalk

This is the expected baseline — it matches the reference implementation
([romainsacchi/BAFU2BW](https://github.com/romainsacchi/BAFU2BW)).

### Steps

```bash
# 1. Dry-run audit (optional — confirms what will be dropped before writing)
REPO_DIR=$(pwd) \
BRIGHTWAY2_DIR=$(pwd)/brightway_data \
BRIGHTWAY_PROJECT=lca_server \
uv run python scripts/audit_bafu.py

# 2. Import everything into brightway_data/ (takes ~5-10 min, idempotent)
uv run python scripts/import_bafu.py

# 3. Verify the databases look correct
uv run python -c "
import os; os.environ['BRIGHTWAY2_DIR'] = 'brightway_data'
import bw2data as bd
bd.projects.set_current('lca_server')
for name in bd.databases:
    print(name, len(bd.Database(name)))
print('methods:', len(list(bd.methods)))
"

# 4. Create the tarball (exclude foreground scratch database and backups)
tar -czf brightway_bafu_v1.tar.gz \
    --exclude='brightway_data/lca_server.*/backups' \
    --exclude='brightway_data/lca_server.*/databases/foreground*' \
    brightway_data/

# Check compressed size
du -sh brightway_bafu_v1.tar.gz
```

### Upload to GitHub releases

```bash
gh release create lca-data-v2 brightway_bafu_v1.tar.gz \
    --title "LCA Database v2 — BAFU 2026" \
    --notes "biosphere3 + BAFU:2026 + 1246 LCIA methods"
```

Then update the `TARBALL_URL` constant in `lca_engine.py`:
```python
TARBALL_URL = (
    "https://github.com/calvinw/life-cycle-assessment-mcp"
    "/releases/download/lca-data-v3/brightway_bafu_v2.tar.gz"
)
```

---

## How to update to a new BAFU version

1. Download the new EcoSpold V1 zip from openLCA Nexus
2. Delete the old `bafu` database:
   ```bash
   uv run python -c "
   import os; os.environ['BRIGHTWAY2_DIR'] = 'brightway_data'
   import bw2data as bd
   bd.projects.set_current('lca_server')
   del bd.databases['bafu']
   "
   ```
3. Place the new zip in `data/bafu/` (remove or rename the old one)
4. Re-run `uv run python scripts/import_bafu.py` — it skips biosphere3 and
   LCIA methods (already present) and only re-imports bafu
5. Build a new tarball and upload as a new GitHub release
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

**`bw2setup` crashes with `ValueError: Can't understand elementary flow identifier`**
— you are running Python 3.14+. Use Python 3.11.
