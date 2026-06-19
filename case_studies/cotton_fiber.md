---
# ─────────────────────────────────────────────────────────────
# LCA Teaching Reference — Cotton Fiber
# Skills reference: skills_references/cotton_fiber/
# ─────────────────────────────────────────────────────────────

name: Cotton Fiber — 1 kg
goal: >
  Calculate the climate and eutrophication impact of producing 1 kg of cotton
  fiber, tracing the supply chain from synthetic fertilizer production through
  cotton farming. This is a 2-process chain that introduces two impact
  categories at once — climate change (GWP100) and terrestrial eutrophication
  (EP-terrestrial) — and shows how the same emission (N2O from fertilised soil)
  contributes to both categories simultaneously. The key teaching moment is
  that cotton's "natural" reputation hides a chemistry problem in the field:
  N2O is 273 times more potent than CO2, and NH3 damages waterways and
  ecosystems independently of its climate contribution.

functional_unit:
  description: 1 kg of ginned cotton fiber, ready for spinning
  amount: 1.0
  unit: kg

units:
  kg: Mass
  L: Volume

products:
  - { name: N-fertilizer,  unit: kg }
  - { name: Cotton fiber,  unit: kg }

elementary_flows:
  emissions:
    - { name: Carbon dioxide, compartment: air, unit: kg }
    - { name: Nitrous oxide,  compartment: air, unit: kg }
    - { name: Ammonia,        compartment: air, unit: kg }
  resources:
    - { name: Water,          compartment: water, unit: L }

processes:
  - name: P1 — Fertilizer production
    reference_output: { flow: N-fertilizer, amount: 1.0 }
    emissions:
      - { flow: Carbon dioxide, amount: 3.5 }

  - name: P2 — Cotton farming
    reference_output: { flow: Cotton fiber, amount: 1.0 }
    inputs:
      - { flow: N-fertilizer, amount: 0.2 }
    emissions:
      - { flow: Carbon dioxide, amount: 0.8   }
      - { flow: Nitrous oxide,  amount: 0.015 }
      - { flow: Ammonia,        amount: 0.010 }
    resources:
      - { flow: Water, amount: 8000 }

reference_process: "P2 — Cotton farming"

lcia:
  method_name: "TRACI 2.2"
---

## About this analysis

A cradle-to-gate LCA for 1 kg of ginned cotton fiber, covering the production
of synthetic nitrogen fertilizer and the cotton farm. Numbers are illustrative,
calibrated to published ranges for irrigated cotton systems. The chain is kept
to two processes so the focus stays on the LCIA step — specifically the
surprising dominance of N2O and the dual-category role of nitrogen emissions.

### Supply chain

```
Fertilizer production  →  Cotton farming  [reference]
          P1                     P2
```

P2 applies 0.2 kg of synthetic nitrogen fertilizer per kg of cotton fiber
produced. All of that fertilizer comes from P1, so P1's scaling factor is 0.2.

### Scaling factors (s)

| Process | Scaling factor s | How it is calculated |
|---|---|---|
| P2 — Cotton farming | 1.000 | Reference process — always 1 |
| P1 — Fertilizer production | 0.200 | 0.2 kg fertilizer needed per kg cotton fiber |

### Emission factors

| Process | Flow | Amount (per process unit) | Source |
|---|---|---|---|
| P1 Fertilizer production | CO2 to air | 3.50 kg / kg N-fertilizer | Haber-Bosch synthesis, high energy input |
| P2 Cotton farming | CO2 to air | 0.80 kg / kg cotton fiber | Machinery, irrigation pumping |
| P2 Cotton farming | N2O to air | 0.015 kg / kg cotton fiber | Microbial conversion of N in fertilised soil |
| P2 Cotton farming | NH3 to air | 0.010 kg / kg cotton fiber | Volatilisation from soil surface |

### LCIA method

EF 3.0 (European Commission Environmental Footprint, version 3.0).
Two impact categories:

**Climate change (GWP100):**
- CO2: 1.0 kg CO2 eq per kg
- N2O: 273.0 kg CO2 eq per kg (IPCC AR6 value used in EF 3.0)

**Terrestrial eutrophication (EP-terrestrial):**
- NH3: 3.54 mol N eq per kg (nitrogen content drives eutrophication)
- N2O: 0.27 mol N eq per kg (partial nitrogen content)

### LCIA results

**Climate change (GWP100):**

| Process | s | CO2 (×1.0) | N2O (×273.0) | Contribution |
|---|---|---|---|---|
| P1 Fertilizer production | 0.200 | 0.70 kg CO2 eq | — | 0.70 kg CO2 eq |
| P2 Cotton farming | 1.000 | 0.80 kg CO2 eq | 4.10 kg CO2 eq | 4.90 kg CO2 eq |
| **Total** | | | | **5.60 kg CO2 eq** |

**Terrestrial eutrophication (EP-terrestrial):**

| Process | s | NH3 (×3.54) | N2O (×0.27) | Contribution |
|---|---|---|---|---|
| P1 Fertilizer production | 0.200 | — | — | 0.000 mol N eq |
| P2 Cotton farming | 1.000 | 0.035 mol N eq | 0.004 mol N eq | 0.039 mol N eq |
| **Total** | | | | **0.039 mol N eq** |

### Key teaching points

**1. N2O dominates the climate footprint**

The raw N2O emission from the cotton field (0.015 kg) looks tiny compared to
the CO2 from the farm (0.8 kg) and fertilizer factory (0.2 × 3.5 = 0.7 kg).
But the GWP100 characterization factor of 273 transforms it:
- 0.015 kg N2O → 4.10 kg CO2 eq
- All CO2 combined → 1.50 kg CO2 eq
- **N2O accounts for 73% of the total climate impact**

Cotton has a natural reputation. The problem is not the factory — it is the
field chemistry caused by synthetic nitrogen fertilizer.

**2. N2O appears in both impact categories**

N2O contributes to GWP100 (as a greenhouse gas) AND to EP-terrestrial (because
it contains nitrogen that eventually deposits in ecosystems). The same emission
causes two different types of environmental damage simultaneously. This is why
studying only one impact category gives an incomplete picture.

**3. NH3 causes eutrophication but not climate change**

NH3 (ammonia) volatilised from the soil surface has no greenhouse warming
effect — its GWP characterization factor is zero. But it deposits nitrogen in
soils and waterways, causing eutrophication: excessive plant and algae growth
that depletes oxygen and damages aquatic ecosystems. NH3 is completely invisible
in a climate-only study, yet it is responsible for 90% of the eutrophication
impact here.

### Simplifications

- Irrigation water source not modelled (groundwater pumping energy included in CO2)
- Pesticide and herbicide production not included
- Ginning (separating fiber from seed) not modelled as a separate process
- Transport between farm and spinning mill not included
- Land use change not included
- Seed production not included
