## About this analysis

A cradle-to-gate LCA for 1 kg of ginned cotton fiber, covering the production
of synthetic nitrogen fertilizer and the cotton farm. Numbers are illustrative,
calibrated to published ranges for irrigated cotton systems. The chain is kept
to two processes so the focus stays on the LCIA step — specifically the
surprising dominance of N2O and the different impacts of nitrogen emissions.

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

TRACI v2.1 (Tool for the Reduction and Assessment of Chemical and other environmental Impacts, version 2.1).
Two impact categories:

**Climate change (GWP100):**
- CO2: 1.0 kg CO2-Eq per kg
- N2O: 298.0 kg CO2-Eq per kg (IPCC AR4 value used in TRACI v2.1)

**Eutrophication potential:**
- NH3: 0.1186 kg N-Eq per kg
- N2O: 0 (not characterized in TRACI v2.1 eutrophication)

### LCIA results

**Climate change (GWP100):**

| Process | s | CO2 (×1.0) | N2O (×298.0) | Contribution |
|---|---|---|---|---|
| P1 Fertilizer production | 0.200 | 0.70 kg CO2-Eq | — | 0.70 kg CO2-Eq |
| P2 Cotton farming | 1.000 | 0.80 kg CO2-Eq | 4.47 kg CO2-Eq | 5.27 kg CO2-Eq |
| **Total** | | | | **5.97 kg CO2-Eq** |

**Eutrophication potential:**

| Process | s | NH3 (×0.1186) | Contribution |
|---|---|---|---|
| P1 Fertilizer production | 0.200 | — | 0.000 kg N-Eq |
| P2 Cotton farming | 1.000 | 0.00119 kg N-Eq | 0.00119 kg N-Eq |
| **Total** | | | **0.00119 kg N-Eq** |

### Key teaching points

**1. N2O dominates the climate footprint**

The raw N2O emission from the cotton field (0.015 kg) looks tiny compared to
the CO2 from the farm (0.8 kg) and fertilizer factory (0.2 × 3.5 = 0.7 kg).
But the TRACI v2.1 GWP100 characterization factor of 298 transforms it:
- 0.015 kg N2O → 4.47 kg CO2-Eq
- All CO2 combined → 1.50 kg CO2-Eq
- **N2O accounts for 75% of the total climate impact**

Cotton has a natural reputation. The problem is not the factory — it is the
field chemistry caused by synthetic nitrogen fertilizer.

**2. Different nitrogen emissions matter in different impact categories**

N2O is the climate-change hotspot in this example, while NH3 is the
eutrophication hotspot. TRACI v2.1 assigns N2O no eutrophication
characterization factor here, and assigns NH3 no climate-change
characterization factor. Studying only one impact category would therefore
miss an important part of the environmental picture.

**3. NH3 causes eutrophication but not climate change**

NH3 (ammonia) volatilised from the soil surface has no greenhouse warming
effect — its GWP characterization factor is zero. But it deposits nitrogen in
soils and waterways, causing eutrophication: excessive plant and algae growth
that depletes oxygen and damages aquatic ecosystems. NH3 is completely invisible
in a climate-only study, yet it is responsible for 100% of the eutrophication
impact here (N2O has no eutrophication characterization factor in TRACI v2.1).

### Simplifications

- Irrigation water source not modelled (groundwater pumping energy included in CO2)
- Pesticide and herbicide production not included
- Ginning (separating fiber from seed) not modelled as a separate process
- Transport between farm and spinning mill not included
- Land use change not included
- Seed production not included
