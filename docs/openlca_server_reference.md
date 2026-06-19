# openLCA Server Reference

This document covers everything you need to know to work with the openLCA
gdt-server in this project: how the database is set up, how to start and stop
the server, and how to query it from Python.

---

## What the server is

The openLCA **gdt-server** is a lightweight calculation engine that runs in the
background as a Docker container (think of Docker as a self-contained box that
holds the software and everything it needs). You communicate with it by sending
requests to `http://localhost:8080` — the server sits on your machine, listens
on port 8080, and answers questions like "calculate the LCA of this product
system" or "list all LCIA methods installed."

The server is **not** the full openLCA desktop application. It has no graphical
interface — it only does calculations and responds to API requests.

---

## The database

The server loads a database of background data when it starts. This project
uses a pre-built database called **`lca_methods`**, stored at
`~/olca-data/databases/lca_methods` on the Codespace machine.

### What is in the lca_methods database

The database was assembled from the
[openLCA LCIA methods pack](https://www.openlca.org/download/) (version 2.8.0,
released 2026-06-18) and contains:

- **45 LCIA methods** — including TRACI 2.2, ReCiPe 2016 (all variants),
  CML-IA, EF 3.1, IPCC 2021, USEtox 2, and more (full list below)
- **FEDEFL elementary flows** — the US EPA's Federal Elementary Flow List,
  which provides the standard names for emissions (Carbon dioxide, Sulfur
  dioxide, etc.) and resources that recipe cards must use
- **Unit groups and flow properties** — the conversion factors that allow the
  server to understand units like kg, kWh, and m³

It does **not** contain ecoinvent background inventory data. All supply chain
processes are defined in the recipe cards themselves.

### How the database gets installed

`setup_olca.sh` handles this automatically the first time:

1. Downloads `lca_methods-LCIA-methods-2.8.0-2026-06-18.tar.gz` (87 MB) from
   the project's GitHub Releases page
2. Extracts it to `~/olca-data/databases/lca_methods`
3. Builds the gdt-server Docker image (once only)
4. Starts the container pointed at that database

On every subsequent session, `start_olca.sh` skips the download and build and
just starts the container directly (much faster).

### Optional: ecoinvent database

A separate script `start_olca_ecoinvent.sh` can start the server with a full
ecoinvent background database instead. This requires:
- An ecoinvent license
- Access to the private GitHub repository `calvinw/ecoinvent-lca-db`
- Being logged in to the GitHub CLI (`gh auth login`)

To switch back from ecoinvent to the free lca_methods database, just run
`bash start_olca.sh`.

---

## Starting and stopping the server

| What you want to do | Command |
|---|---|
| First-time setup (new Codespace) | `bash setup_olca.sh` |
| Start at the beginning of a session | `bash start_olca.sh` |
| Start with ecoinvent database | `bash start_olca_ecoinvent.sh` |
| Stop the server | `bash stop_olca.sh` |
| Check if the server is running | `curl -s http://localhost:8080/api/version` |

A running server responds to the version check with something like:
```
{"version":"2.0.25","isBlasEnabled":true,"isUmfpackEnabled":true}
```

If you get `Connection refused` or no response, the server is not running —
start it with `bash start_olca.sh`.

---

## Connecting from Python — use RestClient, not ipc.Client

This is the most important thing to get right. The `olca_ipc` package ships
two different client classes that talk to the server in different ways:

| Client | Endpoint | Works with gdt-server? |
|---|---|---|
| `olca_ipc.rest.RestClient` | `http://localhost:8080/` | **Yes — use this one** |
| `olca_ipc.Client` (ipc.Client) | `http://localhost:8080` (JSON-RPC) | No — returns 404 |

Always use `RestClient`. The `ipc.Client` expects a different protocol that
the gdt-server does not support.

```python
from olca_ipc.rest import RestClient
import olca_schema as o

client = RestClient("http://localhost:8080/")
```

Note the trailing slash on the URL — include it.

---

## Useful queries

### Check the server version

```python
import requests
r = requests.get("http://localhost:8080/api/version")
print(r.json())
# → {"version": "2.0.25", "isBlasEnabled": true, ...}
```

### List all installed LCIA methods

```python
from olca_ipc.rest import RestClient
import olca_schema as o

client = RestClient("http://localhost:8080/")
methods = client.get_all(o.ImpactMethod)
for m in methods:
    print(m.name)
```

### Find a specific LCIA method by name

```python
methods = client.get_all(o.ImpactMethod)
match = next((m for m in methods if m.name == "TRACI 2.2"), None)
print(match.id if match else "not found")
```

### List all elementary flows (emissions and resources)

```python
flows = client.get_all(o.Flow)
elementary = [f for f in flows if f.flow_type == o.FlowType.ELEMENTARY_FLOW]
for f in elementary:
    print(f.name)
```

### List all LCIA categories for a method

```python
method = next(m for m in client.get_all(o.ImpactMethod) if m.name == "TRACI 2.2")
full_method = client.get(o.ImpactMethod, method.id)
for cat in full_method.impact_categories:
    print(cat.name, cat.ref_unit)
```

---

## All 45 installed LCIA methods

```
AWARE
AWARE 1.2
BEES+
Berger et al 2014 (Water Scarcity)
Boulay et al 2011 (Human Health)
Boulay et al 2011 (Water Scarcity)
CML-IA baseline
CML-IA non-baseline
Crustal Scarcity Indicator
Cumulative Energy Demand (HHV)
Cumulative Energy Demand (LHV)
Cumulative Exergy Demand
ECO-COSTS 2025 V2.1
EDIP 2003
EF 2.0 Method (adapted)
EF 3.0 Method (adapted)
EF 3.1 Method (adapted)
Ecological Scarcity 2006 (Water Scarcity)
Ecological Scarcity 2013
Ecosystem Damage Potential
EPD 2018
EPS 2015d
EPS 2015dx
Environmental Prices
Hoekstra et al 2012 (Water Scarcity)
ILCD 2011 Midpoint+
IMPACT 2002+
IPCC 2013
IPCC 2021
IPCC 2021 (ISO 14067)
Motoshita et al 2010 (Human Health)
Pfister et al 2009 (Eco-indicator 99)
Pfister et al 2009 (Water Scarcity)
Pfister et al 2010 (ReCiPe)
ReCiPe 2016 Endpoint (E)
ReCiPe 2016 Endpoint (H)
ReCiPe 2016 Endpoint (I)
ReCiPe 2016 Midpoint (E)
ReCiPe 2016 Midpoint (H)
ReCiPe 2016 Midpoint (I)
Selected LCI results
TRACI 2.1
TRACI 2.2
USEtox 2 (recommended only)
USEtox 2 (recommended + interim)
```

---

## How the analysis script uses the server

`lca_scripts/lca_analysis.py` follows this sequence:

1. Connects via `RestClient("http://localhost:8080/")`
2. Creates unit groups, flow properties, flows, and unit processes in the
   server's in-memory working space (Steps 3–6)
3. Links them into a product system and submits a `CalculationSetup` (Step 7
   and 11)
4. Calls `result.get_total_flows()` for the LCI inventory and
   `result.get_total_impacts()` for the LCIA scores (Step 12 and 14)
5. Calls `result.dispose()` to free server memory when done

The `lcia:` section of a recipe card controls which method is used at step 4.
Changing `method_name` in the recipe card is the only thing you need to do to
switch methods — the script looks up the method by name and passes it to the
calculation.

---

## Common errors

| Error | Cause | Fix |
|---|---|---|
| `Connection refused` on port 8080 | Server is not running | `bash start_olca.sh` |
| `404 Not Found` on POST requests | Using `ipc.Client` instead of `RestClient` | Switch to `RestClient` |
| LCIA scores all zero for a category | Flow name does not match FEDEFL | Check spelling in recipe card (e.g. `Carbon dioxide` not `CO2`) |
| `method not found` warning | Method name typo in recipe card | Copy the name exactly from the list above |
