---
# ─────────────────────────────────────────────────────────────
# LCA Teaching Reference — Polyester T-shirt
# Skills reference: skills_references/polyester_tshirt/
# ─────────────────────────────────────────────────────────────

name: Polyester T-shirt — 1 unit
goal: >
  Calculate the climate impact of producing one polyester T-shirt,
  tracing the supply chain from crude oil extraction through polyester
  fiber production to garment assembly. This is a 3-process, 2-layers-deep
  chain designed to show how compound scaling works — and how the emissions
  from an oil well are attributed to a shirt hanging in a clothing store,
  even though the well is two steps back in the supply chain.

functional_unit:
  description: 1 polyester T-shirt, ready for sale (approximately 200 g of fabric)
  amount: 1.0
  unit: unit

units:
  kg: Mass
  unit: Item

products:
  - { name: Crude oil,       unit: kg }
  - { name: Polyester fiber, unit: kg }
  - { name: T-shirt,         unit: unit }

elementary_flows:
  emissions:
    - { name: Carbon dioxide, compartment: air, unit: kg }
    - { name: Methane,        compartment: air, unit: kg }

processes:
  - name: P1 — Oil extraction
    reference_output: { flow: Crude oil, amount: 1.0 }
    emissions:
      - { flow: Carbon dioxide, amount: 0.20 }
      - { flow: Methane,        amount: 0.05 }

  - name: P2 — Polyester fiber production
    reference_output: { flow: Polyester fiber, amount: 1.0 }
    inputs:
      - { flow: Crude oil, amount: 1.5 }
    emissions:
      - { flow: Carbon dioxide, amount: 5.5 }

  - name: P3 — T-shirt assembly
    reference_output: { flow: T-shirt, amount: 1.0 }
    inputs:
      - { flow: Polyester fiber, amount: 0.2 }
    emissions:
      - { flow: Carbon dioxide, amount: 1.0 }

reference_process: "P3 — T-shirt assembly"

lcia:
  method_name: "TRACI 2.2"
---

## About this analysis

A cradle-to-gate LCA for one polyester T-shirt, covering oil extraction,
fiber production, and garment assembly. Numbers are illustrative, calibrated
to published ranges for virgin polyester systems. The chain is deliberately
kept to three processes so the compound scaling step stays easy to follow.

### Supply chain

```
Oil extraction  →  Polyester fiber production  →  T-shirt assembly  [reference]
      P1                      P2                          P3
```

P3 needs 0.2 kg of polyester fiber to assemble one T-shirt.
P2 needs 1.5 kg of crude oil to produce 1 kg of polyester fiber.
This means P1 must supply 0.2 × 1.5 = **0.3 kg of crude oil per shirt**.

That compound calculation — multiplying across two steps — is the key
teaching moment for the scaling vector concept.

### Scaling factors (s)

| Process | Scaling factor s | How it is calculated |
|---|---|---|
| P3 — T-shirt assembly | 1.000 | Reference process — always 1 |
| P2 — Polyester fiber production | 0.200 | 0.2 kg fiber needed per shirt |
| P1 — Oil extraction | 0.300 | 0.2 kg fiber × 1.5 kg oil per kg fiber |

### Emission factors

| Process | Flow | Amount (per process unit) | Source |
|---|---|---|---|
| P1 Oil extraction | CO2 to air | 0.20 kg / kg crude oil | Well energy, flaring |
| P1 Oil extraction | CH4 to air | 0.05 kg / kg crude oil | Fugitive leaks from wells and pipelines |
| P2 Polyester fiber | CO2 to air | 5.50 kg / kg fiber | Polymerisation, high-temp energy |
| P3 T-shirt assembly | CO2 to air | 1.00 kg / shirt | Cutting, sewing, factory electricity |

### LCIA results (GWP100, IPCC AR6)

| Process | s | CO2 direct | CH4 (×27.9) | Contribution |
|---|---|---|---|---|
| P3 T-shirt assembly | 1.000 | 1.00 kg CO2 eq | — | 1.00 kg CO2 eq |
| P2 Polyester fiber | 0.200 | 1.10 kg CO2 eq | — | 1.10 kg CO2 eq |
| P1 Oil extraction | 0.300 | 0.06 kg CO2 eq | 0.42 kg CO2 eq | 0.48 kg CO2 eq |
| **Total** | | | | **2.58 kg CO2 eq** |

### Key teaching point — "Your T-shirt is oil"

Polyester is not a plant-based or natural fibre — it is a petroleum product,
chemically converted from crude oil. The oil feedstock is tracked as a process
input (1.5 kg oil per kg fiber), so the supply chain diagram shows a physical
connection from the well to the shirt.

The compound scaling calculation reveals something invisible in everyday life:
producing one shirt requires the oil extraction process to run at 30% of its
full scale (s = 0.3). That means **0.3 kg of crude oil** is directly embodied
in every polyester T-shirt, before the factory has burned a single watt of
electricity.

The methane from oil wells (CH4, a fugitive — meaning leaked, not burned)
is only 0.05 kg per kg of crude oil extracted, but its GWP100 factor of 27.9
turns those 0.015 kg of CH4 (0.3 × 0.05) into 0.42 kg CO2 eq — nearly as
large as the factory's direct emissions from sewing.

### Simplifications

- Transport between stages not included
- Fabric dyeing and finishing not modelled
- Use phase (washing, drying) and end-of-life not included (cradle-to-gate only)
- A single T-shirt weight of 200 g used; actual garments vary from 150–300 g
- Oil refining is combined with extraction in P1 for simplicity
