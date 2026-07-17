# Python engine and MCP separation

The calculation engine is available as the installable `lca_core` Python
package. It has no dependency on FastMCP, Starlette, FastAPI, or Uvicorn.
`lca_server.py` is now an adapter: its MCP tools and HTTP routes call the same
public `LCAEngine` API that another Python program can call directly.

```text
Python application ──┐
                    ├──> lca_core.LCAEngine ──> Brightway + search + SVG
MCP / HTTP client ──> lca_server.py ──┘
```

## Install

Install only the reusable engine and its Brightway dependencies:

```bash
uv sync
```

Install the engine plus the MCP and HTTP server dependencies:

```bash
uv sync --extra server
```

The Docker image installs the `server` extra automatically.

## Use from Python

Set the Brightway configuration before importing `lca_core` when custom paths
or project names are needed:

```python
import os

os.environ["BRIGHTWAY2_DIR"] = "/var/lib/my-app/brightway"
os.environ["BRIGHTWAY_PROJECT"] = "my_lca_app"

from lca_core import LCAEngine

engine = LCAEngine()
engine.ensure_ready()

result = engine.run(product_graph_yaml)
matches = engine.search_activities("polypropylene", database="bafu")
schema = engine.get_database_schema()
```

`ensure_ready()` initializes the selected Brightway project and ensures that
the BAFU and searchable projection databases are available. Calculation and
query methods also perform this check, so calling it explicitly is useful for
startup validation but is not required before every operation.

The public facade also exposes contribution analysis, top emissions,
background activity comparison, method and database listing, read-only SQL,
activity inputs, and SVG generation. Transport-specific behavior such as MCP
tool registration, HTTP request parsing, and case-study routes remains in
`lca_server.py`.

## Compatibility

The former top-level modules (`lca_engine`, `lca_search`, `lca_svg`, and
`lca_svg_engine`) remain as compatibility aliases. Existing scripts can keep
using them while new code should import `LCAEngine` from `lca_core`.
