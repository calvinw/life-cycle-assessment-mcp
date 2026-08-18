# Plain-English Explainer: Instant Foreground Editing with Background Intensities

Status: Explains the Tier 1 implementation and the proposed Tier 2 and Tier 3
experience  
Date: August 17, 2026  
Technical design: [`PLAN_precomputed_background_intensities.md`](PLAN_precomputed_background_intensities.md)

## The idea in one sentence

Precalculate the environmental impact of one unit of every background product,
then let a product graph multiply those known values by its editable foreground
amounts.

The precomputed value is called a **background cumulative intensity**. It means
the impact of one unit of a product, including its whole upstream supply chain.

For example, an illustrative climate-change intensity table could be:

| Background product | Cumulative climate intensity |
|---|---:|
| Polylactide granulate | 2.40 kg CO2-eq per kg |
| Nylon 6 | 6.00 kg CO2-eq per kg |
| Freight transport | 0.12 kg CO2-eq per tonne-km |

The 2.40 kg CO2-eq for polylactide already includes making the granulate, its
electricity, raw materials, transport, and their upstream inputs. The numbers
in this document are illustrative; the engine uses the selected Brightway
background database and LCIA method to calculate the real values.

## A fixed functional unit, with editable graph parameters

Suppose the functional unit is fixed at **one finished broom**. It is the target
the model must satisfy; it is not normally a slider during parameter editing.

An initial foreground process uses:

| Foreground exchange | Amount needed for one broom | Intensity | Impact |
|---|---:|---:|---:|
| Polylactide input | 0.52 kg | 2.40 kg CO2-eq/kg | 1.248 kg CO2-eq |
| Nylon input | 0.03 kg | 6.00 kg CO2-eq/kg | 0.180 kg CO2-eq |
| Freight input | 0.1055 tonne-km | 0.12 kg CO2-eq/tonne-km | 0.013 kg CO2-eq |
| Direct foreground emission | -- | -- | 0.050 kg CO2-eq |
| **Total for one broom** | | | **1.491 kg CO2-eq** |

The total is exact linear LCA arithmetic:

```text
total = direct foreground impact
      + (0.52 x 2.40)
      + (0.03 x 6.00)
      + (0.1055 x 0.12)
```

### Turning a graph amount into a slider

The editor can expose the polylactide exchange directly on the graph:

```text
Polylactide input to broom process
0.30 kg  [--------o--------------]  0.80 kg
                 0.52 kg
```

If a user drags it from 0.52 kg to 0.30 kg, while the functional unit remains
one broom, only that contribution changes:

| | Before | After slider change |
|---|---:|---:|
| Polylactide impact | 1.248 kg CO2-eq | 0.720 kg CO2-eq |
| Total impact for one broom | 1.491 kg CO2-eq | 0.963 kg CO2-eq |

The UI can immediately update the total, the edge width, and the polylactide
hotspot. No approximation is involved: it is `0.30 x 2.40` instead of
`0.52 x 2.40`.

Provider selection works the same way. If a user switches from a provider with
an intensity of 2.40 to one with an intensity of 1.20 kg CO2-eq/kg, the same
0.52 kg input contributes 0.624 rather than 1.248 kg CO2-eq.

### Sliders can change yields too

Some parameters change how much foreground activity is required to deliver the
fixed functional unit. For example, suppose a coating process initially yields
one broom per operation and uses 0.10 kg of paint per operation. If paint has a
background intensity of 5.00 kg CO2-eq/kg:

| Yield slider | Operations required to deliver one broom | Paint required | Paint impact |
|---:|---:|---:|---:|
| 1.00 broom per operation | 1.00 | 0.100 kg | 0.500 kg CO2-eq |
| 0.80 broom per operation | 1.25 | 0.125 kg | 0.625 kg CO2-eq |

The functional unit is still one broom. The small foreground solve adjusts the
process scale from 1.00 to 1.25 operations to meet it. The same applies to
foreground-to-foreground inputs, co-products, and other editable coefficients,
provided the edited foreground matrix remains solvable.

## The three tiers

### Tier 1: make the existing server calculation cheaper

At process startup, calculate and keep the cumulative intensity of every
background product for each needed LCIA category. The existing two-call pipeline
still runs, but Call 2 no longer has to factorize the large background transpose
matrix on every request.

This is implemented behind a default-off flag. On the BAFU broom workload, the
median Call 2 time fell from **891 ms to 756 ms**: a **135 ms** reduction. Tier
1 does not yet give the browser the numbers it needs to recalculate sliders
itself.

### Tier 2: make foreground sliders live

Call 1 returns the relevant background intensities alongside resolved providers:

```text
polylactide provider -> 2.40 kg CO2-eq/kg
nylon provider       -> 6.00 kg CO2-eq/kg
freight provider     -> 0.12 kg CO2-eq/tonne-km
```

The browser then holds both the foreground graph and the values needed to score
its background links. Moving an input, emission, yield, or provider slider can
update the score and foreground graph locally, while preserving the fixed
functional unit. This tier is not started; it changes the API and frontend
contract.

### Tier 3: make initial score calculation fast too

Today, the initial full calculation creates a temporary Brightway foreground
database because the application also needs inventory, detailed contributions,
and a physical Sankey. Tier 3 would add a score-only route that directly builds
the tiny foreground matrix from the product graph and combines it with the
precomputed background intensities.

That would make a newly edited graph score quickly without first building a
temporary Brightway database. It would still be exact, but it is a second
calculation route and has not been started or benchmarked.

## What remains server-calculated

The live score experience does not replace every existing result. The full
Brightway calculation remains necessary when the application needs:

- the complete aggregated life-cycle inventory;
- deep-background contribution analysis;
- a physical Sankey inside the background supply chain; or
- a new background database, method, or scenario not represented by the cached
  intensity values.

The intended experience is therefore: use the full calculation to establish a
trusted model, then use exact local arithmetic to explore foreground choices in
real time.
