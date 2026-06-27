# BAFU Validation Examples: Brightway ↔ openLCA

Cross-check reference for four simple processes from the BAFU 2026 LCI database.
Calculated in Brightway 2.5 with EF v3.0 (climate change, GWP100).
Verify in openLCA with BAFU 2026 + EF 3.1 — expect ~1–3% difference due to method version.

---

## How to run these in openLCA

1. Open openLCA desktop with BAFU 2026 imported
2. Navigate to **Processes** and search for the process name below
3. Right-click → **Create product system** → check "Add connected processes automatically" → OK
4. Open the product system → **Calculate** → method: **EF 3.1 Method (adapted)**
5. Under results, look at **Climate change → GWP100** and compare to the Brightway value

---

## 1. Steel, converter, unalloyed (RER) — 1 kg

**Brightway result: 2.521 kg CO₂-eq**

A converter steel process with a rich upstream graph (~35 exchanges). Dominated
by pig iron production.

### Product graph

| Amount | Unit | Input | Location | CO₂-eq | Share |
|--------|------|-------|----------|--------|-------|
| 0.853 | kg | Pig iron, at plant | RER | 1.960 | 77.7% |
| 0.521 | MJ | Basic oxygen furnace gas, burned in power plant | RER | 0.309 | 12.2% |
| 0.048 | kg | Quicklime, in pieces, loose, at plant | CH | 0.057 | 2.3% |
| 0.030 | kg | Sinter, iron, at plant | RER | 0.020 | 0.8% |
| 0.079 | kg | Oxygen, liquid, at plant | RER | 0.017 | 0.7% |
| 0.097 | kg | Carbon dioxide, fossil | air (direct) | — | — |
| 0.004 | kg | Carbon monoxide, fossil | air (direct) | — | — |
| *other inputs* | | transport, scrap, gases, disposal | | 0.158 | 6.3% |

### Story
Almost 90% of the impact comes from making pig iron (the iron ore smelting step
in a blast furnace) and burning the by-product furnace gases. The converter
itself is a relatively clean refining step — the carbon footprint is inherited
from upstream iron-making.

---

## 2. Flat glass, uncoated (RER) — 1 kg

**Brightway result: 1.013 kg CO₂-eq**

A float glass process. Relatively shallow graph (~20 exchanges). Split between
direct CO₂ from the glass melt and upstream energy.

### Product graph

| Amount | Unit | Input | Location | CO₂-eq | Share |
|--------|------|-------|----------|--------|-------|
| 0.693 | kg | Carbon dioxide, fossil | air (direct) | — | — |
| 0.229 | kg | Soda, powder, at plant | RER | 0.097 | 9.6% |
| 4.560 | MJ | Natural gas, high pressure | RER | 0.081 | 8.0% |
| 0.111 | kWh | Electricity, medium voltage, ENTSO-E | ENTSO-E | 0.031 | 3.1% |
| 0.074 | kg | Heavy fuel oil | RER | 0.067 | 6.6% |
| 0.578 | kg | Silica sand, at plant | DE | 0.013 | 1.3% |
| 0.060 | tkm | Transport, lorry, fleet average | RER | 0.012 | 1.2% |
| 0.400 | kg | Limestone, milled | CH | 0.008 | 0.8% |
| *other inputs* | | refractory, disposal, plant capital | | 0.010 | 1.0% |

### Story
The 0.693 kg direct CO₂ comes from the decomposition of limestone and soda ash
during melting (process emissions, not energy). On top of that, natural gas and
heavy oil supply the heat for the furnace (~1600 °C). Result: ~1 kg CO₂ per kg
glass is a well-known benchmark.

---

## 3. Aluminium, production mix (RER) — 1 kg

**Brightway result: 4.886 kg CO₂-eq**

The simplest graph of the four — only 3 inputs. A blend of primary and secondary
aluminium representing the European production mix.

### Product graph

| Amount | Unit | Input | Location | CO₂-eq | Share |
|--------|------|-------|----------|--------|-------|
| 0.512 | kg | Aluminium, primary, at plant | RER | 4.652 | 95.2% |
| 0.175 | kg | Aluminium, secondary, from old scrap | RER | 0.117 | 2.4% |
| 0.313 | kg | Aluminium, secondary, from new scrap | RER | 0.116 | 2.4% |

### Story
Primary aluminium (electrolysis of bauxite) dominates entirely. Secondary
(recycled) aluminium costs roughly 95% less carbon than primary — visible here
in that 0.175 kg secondary contributes only 0.117 kg CO₂ while 0.512 kg primary
contributes 4.65 kg. The production mix is ~51% primary, which is why the
overall footprint is high. This makes a clean teaching example for recycled
content impact.

---

## 4. Yarn production, cotton fibres (GLO) — 1 kg

**Brightway result: 5.477 kg CO₂-eq**

Very shallow graph — 4 inputs plus one waste heat emission. Almost entirely
driven by electricity.

### Product graph

| Amount | Unit | Input | Location | CO₂-eq | Share |
|--------|------|-------|----------|--------|-------|
| 5.100 | kWh | Electricity, low voltage, at grid | CN | 3.843 | 70.2% |
| 3.400 | kWh | Electricity, low voltage, at grid | US | 1.527 | 27.9% |
| 0.450 | tkm | Transport, freight lorry 16–32t | RER | 0.103 | 1.9% |
| ~0 | unit | Packaging box production unit | RER | 0.005 | 0.1% |
| 30.6 | MJ | Heat, waste | direct emission | 0 | — |

### Story
This is the yarn *spinning* step only — cotton fibre is not modelled as an
input. The impact is 98% electricity: Chinese grid (coal-heavy, 5.1 kWh) plus
a US grid allocation (3.4 kWh). The high electricity intensity of textile
spinning, combined with a coal-dominated Chinese grid, explains why cotton yarn
scores higher than many synthetic fibres at the processing stage.

Note: this process does **not** include cotton farming, ginning, or dyeing.
A cradle-to-gate yarn would be significantly higher.

---

## Summary table

| Process | Location | Brightway (EF v3.0) | Expected openLCA (EF 3.1) |
|---------|----------|---------------------|--------------------------|
| Steel, converter, unalloyed | RER | 2.521 kg CO₂-eq / kg | ~2.5 |
| Flat glass, uncoated | RER | 1.013 kg CO₂-eq / kg | ~1.0 |
| Aluminium, production mix | RER | 4.886 kg CO₂-eq / kg | ~4.9 |
| Yarn production, cotton fibres | GLO | 5.477 kg CO₂-eq / kg | ~5.5 |

Differences of 1–5% between tools are expected due to EF 3.0 vs 3.1
characterization factors and BAFU 2025 vs 2026 minor inventory updates.

---

## Also: Plastic broom (the original benchmark)

| Input | Amount | CO₂-eq | Share |
|-------|--------|--------|-------|
| Polylactide (PLA), at plant | 0.52 kg | 1.452 | 83.1% |
| Nylon 6, at plant | 0.03 kg | 0.295 | 16.9% |
| **Total** | | **1.747 kg CO₂-eq** | |

Video (openLCA, EF 3.1): **~1.7 kg CO₂-eq** ✓

PLA breakdown: natural gas 51.6%, corn at farm 24.4%, electricity ENTSO-E 19.5%
