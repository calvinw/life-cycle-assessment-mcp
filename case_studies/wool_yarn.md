---
# ─────────────────────────────────────────────────────────────
# LCA Teaching Reference — Wool Yarn
# Skills reference: skills_references/wool_yarn/
# ─────────────────────────────────────────────────────────────

name: Wool Yarn — 1 kg
goal: >
  Calculate the climate impact of producing 1 kg of wool yarn,
  tracing the supply chain from sheep farming through scouring and spinning.
  This is a 2-process chain designed to show how methane (CH4) from livestock
  completely dominates the climate impact once characterization factors are applied —
  even though the raw kg of CH4 looks small compared to the CO2 from processing.

functional_unit:
  description: 1 kg of wool yarn, ready for knitting or weaving
  amount: 1.0
  unit: kg

units:
  kg: Mass
  L: Volume

products:
  - { name: Raw wool,  unit: kg }
  - { name: Wool yarn, unit: kg }

elementary_flows:
  emissions:
    - { name: Carbon dioxide, compartment: air,   unit: kg }
    - { name: Methane,        compartment: air,   unit: kg }
  resources:
    - { name: Water,          compartment: water, unit: L  }

processes:
  - name: P1 — Sheep farming
    reference_output: { flow: Raw wool, amount: 1.0 }
    emissions:
      - { flow: Carbon dioxide, amount: 0.5 }
      - { flow: Methane,        amount: 0.4 }

  - name: P2 — Wool yarn production
    reference_output: { flow: Wool yarn, amount: 1.0 }
    inputs:
      - { flow: Raw wool, amount: 1.1 }
    emissions:
      - { flow: Carbon dioxide, amount: 2.0 }
    resources:
      - { flow: Water, amount: 30 }

reference_process: "P2 — Wool yarn production"

lcia:
  method_name: "TRACI v2.1"
---

## About this analysis

A cradle-to-gate LCA for 1 kg of wool yarn, covering the sheep farm and
the yarn production facility. Numbers are illustrative, calibrated to
published ranges for Merino wool systems.

### Supply chain

```
Sheep farming  →  Wool yarn production  [reference]
     P1                   P2
```

P2 needs 1.1 kg of raw wool to produce 1.0 kg of yarn — the 10% loss
occurs during scouring (washing the fleece) and carding (combing the fibers).

### Emission factors

| Process | Flow | Amount | Source |
|---|---|---|---|
| P1 Sheep farming | CO2 to air | 0.5 kg / kg raw wool | Farm energy, feed production |
| P1 Sheep farming | CH4 to air | 0.4 kg / kg raw wool | Enteric fermentation (digestion) |
| P2 Yarn production | CO2 to air | 2.0 kg / kg yarn | Scouring hot water, spinning energy |

### LCIA method

IPCC Sixth Assessment Report (AR6), GWP100. Characterization factors:
- CO2: 1.0 kg CO2 eq per kg
- CH4: 25.0 kg CO2-Eq per kg (fossil methane, TRACI v2.1; 20-year GWP is 81.2)

### Key teaching point

The raw CH4 emitted at the sheep farm (0.4 kg × 1.1 scaling = 0.44 kg) looks
modest compared to the CO2 from processing (2.0 kg). But once the GWP100
characterization factor of 27.9 is applied:

- CH4 contribution: 0.44 × 25.0 = **11.0 kg CO2-Eq**
- CO2 from farming: 0.55 kg CO2-Eq
- CO2 from processing: 2.0 kg CO2-Eq
- **Total: 13.55 kg CO2-Eq per kg of wool yarn**

The sheep farm is responsible for roughly 85% of the climate impact.
Wool's reputation as a "natural" fiber does not mean low-carbon.

### Simplifications

- Sheep feed production not modelled as a separate upstream process
- Land use change not included
- Transport between farm and mill not included
- Scouring wastewater treatment not included
