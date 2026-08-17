# Proposed UI: Interactive LCA Scenario Explorer

## Product concept

An interactive web application for exploring life-cycle-assessment product-design
scenarios. The user edits a product graph while keeping the functional unit
fixed and sees environmental impacts update immediately.

Example product: a plastic broom.

Functional unit: deliver **1 broom** with defined performance.

The question is not “what is the impact of ten brooms?” It is: “how does the
impact of one equivalent broom change if we use less plastic, change a
supplier, improve yield, or reduce emissions?”

## Core model

The BAFU-linked [`product-graphs/plastic_broom.yaml`](../product-graphs/plastic_broom.yaml)
has **one foreground activity** and **three background-provider activities at
the foreground/background boundary**:

- Foreground activity: Plastic broom assembly.
- Background provider: Polylactide, granulate, at plant (GLO): 0.52 kg.
- Background provider: Nylon 6, at plant (RER): 0.03 kg.
- Background provider: Transport, freight, lorry, 16t–32t gross weight, fleet
  average (RER): 0.1055 tkm.
- Functional unit: 1 plastic broom.

The user can change meaningful foreground parameters, such as PLA mass, nylon
mass, transport demand, or a material supplier. Future product graphs could
also expose assembly electricity or direct-emission controls, but neither is an
exchange in this particular broom YAML.

The editable value belongs to the foreground activity’s **technosphere input
exchange**. It is not an elementary-flow inventory result.

## Main screen: structure mode while editing

Show a simplified product structure rather than a fully scaled LCA network
while the user is dragging a control.

```text
[ Polylactide, granulate, at plant — GLO ] ── 0.52 kg ──┐
[ Nylon 6, at plant — RER ] ────────────────── 0.03 kg ──┼──> [ Plastic broom assembly ] ──> [ 1 plastic broom ]
[ Freight lorry 16t–32t, fleet average — RER ] 0.1055 tkm┘
             background-provider activities                  foreground activity       functional unit
```

Make Plastic broom assembly the focal card. Its inputs appear in or adjacent to
that activity.

```text
┌──────────────────────────────────────┐
│  Plastic broom assembly              │
│  Output: 1 plastic broom             │
│                                      │
│  BACKGROUND INPUTS                   │
│  Polylactide granulate, GLO          │
│  0.40 kg ────────●──────── 0.70 kg   │
│                                      │
│  Nylon 6, RER          0.03 kg       │
│  Freight lorry, RER    0.1055 tkm    │
│                                      │
│  [ Reset ]        [ Scenario notes ] │
└──────────────────────────────────────┘
```

When PLA changes from 0.52 kg to 0.40 kg:

- Keep the graph structurally stable.
- Highlight and visually narrow the PLA edge.
- Highlight the upstream Polylactide branch; mute the unchanged Nylon 6 and
  freight branches.
- Do not show calculated inventory quantities, activity scales, contribution
  widths, or Sankey widths while dragging: they are stale until the exact
  calculation refreshes.

## Live impact panel

Update each selected LCIA category in real time while the slider moves.

```text
LIVE SCENARIO
Functional unit: 1 broom

PLA input: 0.52 kg → 0.40 kg

Climate change       baseline → preview
Acidification        baseline → preview
```

Use a compact animated delta: old value in soft gray, new value prominent, a
green arrow for a reduction, and amber/red for an increase. Climate change and
acidification are the two categories listed in the current BAFU-linked broom
YAML. The user can select more compatible categories in a future scenario; any
numerical values in a design illustration should be labelled illustrative.

These live score previews use preloaded cumulative impact intensities for the
affected background supplies. The computation per edit is a small set of
multiplications and additions per selected category.

## Normalization and weighting panel

Keep raw category scores visible. Below them, offer optional, transparent
normalization and weighting.

```text
DECISION VIEW

Normalization method: EF reference values
Weighting set: User-defined / policy profile

Climate change        0.014   × 30% = 0.0042
Water scarcity        0.009   × 20% = 0.0018
Resource use          0.018   × 25% = 0.0045
Human toxicity        0.006   × 25% = 0.0015

Weighted decision score
62.4  →  58.7
```

Show the normalization source and category weights. Label the total clearly as
a decision score, rather than an inherent or objective LCA result.

## Interaction sequence

1. The user opens “Plastic broom — 1 broom.”
2. They tap the Polylactide input on Plastic broom assembly.
3. They drag the slider from 0.52 kg to 0.40 kg.
4. The graph remains in Structure mode.
5. Raw category scores, normalized values, and weighted score animate
   immediately.
6. The Polylactide branch is highlighted and the Nylon 6 and freight branches
   are muted.
7. On release or a short pause, the app requests an exact full LCA refresh.
8. The detailed view refreshes activity scaling, elementary-flow inventory,
   contribution tables, and Sankey widths together.

## Exact-detail mode after editing

After the server result returns, offer detail views.

```text
DETAIL VIEW
[ Structure ] [ Inventory ] [ Contributions ] [ Sankey ]

Top changed inventory flows:
- Fossil CO₂ to air          −0.19 kg
- Methane to air             −0.0003 kg
- Water withdrawal           −8.4 L
- Crude oil extraction       −0.11 kg

Top changed supply-chain contributors:
1. PLA granulate production
2. Feedstock production
3. Upstream freight
```

The underlying supply chain is a network with shared suppliers and loops. A
tree can be used for readability, but it should be presented as an explanatory
view rather than the full mathematical network.

## Modelling behaviour and constraints

Changing PLA from 0.52 kg to 0.40 kg with the functional unit fixed at one
broom means: “make one equivalent broom using 0.40 kg of PLA instead of
0.52 kg.”

By default:

- PLA demand and its upstream supply chain decrease.
- Nylon and transport remain at 0.03 kg and 0.1055 tkm respectively; the
  one-broom output remains unchanged.
- The detailed elementary-flow inventory changes downstream: CO₂, methane,
  water use, resource extraction, and many other flows.
- Each LCIA category can change differently.

Do not automatically alter nylon or transport unless the scenario defines an
engineering constraint. For example:

```text
Total material mass fixed at 0.55 kg
nylon = 0.55 kg − PLA
```

Here reducing PLA automatically increases nylon. This is an explicit design
rule, not an automatic LCA rule.

## Design principles

- Keep the functional unit fixed while comparing design alternatives.
- Expose meaningful named parameters, not arbitrary matrix edits.
- Make units, defaults, ranges, assumptions, and scenario notes visible.
- Keep raw categories visible alongside weighting and normalization.
- Distinguish fast score previews from exact detailed results.
- Use clear cards or panels, a simple graph, and progressive disclosure rather
  than dense desktop-LCA tables.

## Product framing

**An interactive environmental tradeoff explorer for a fixed product
function.** It makes LCA accessible without claiming that a slider change alone
proves the revised product is physically feasible.
