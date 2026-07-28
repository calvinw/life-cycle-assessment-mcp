# Explanation: The Lazy Two-Call LCA Pipeline

Status: Explanatory companion to
[`lazy-calculate-lca-engine-plan.md`](lazy-calculate-lca-engine-plan.md)
Date: July 28, 2026

This document walks the whole pipeline start to finish as a sequence of steps.
Each step says what we do, which call does it, what it costs, and what it hands
to the next step. It exists to explain *why* the design is shaped this way,
especially the adjoint solve and the optimizations that follow from it.

---

## Phase A — Setup (paid once per request)

### Step 1. Build the foreground

Parse the YAML spec, create a uniquely-named temporary Brightway database, and
write one activity per process with its technosphere exchanges (to other
foreground processes or to named background providers) and its direct biosphere
exchanges. Delete the database when the request ends.

This is disk-and-metadata work in `bd`, not linear algebra, and it is the single
largest fixed cost we pay — on the order of 2.5 s for the BAFU-scale examples.
Everything else in Phase A is small by comparison. Keep it inside a lock and a
`try/finally`, because Brightway project state is process-global.

### Step 2. Instantiate the LCA object

```python
lca = bc.LCA(demand={ref_act: fu_amount}, method=method_tuples[0])
```

This assembles three sparse matrices and the index maps we will need for the
rest of the request:

- **A** — technosphere, rows = products, columns = activities
- **B** — biosphere, rows = elementary flows, columns = activities
- **C** — characterization, diagonal over elementary flows, one per impact
  category
- `lca.dicts.activity`, `.product`, `.biosphere`, each with a `.reversed` map
  back to Brightway node ids

### Step 3. Factorize A and solve the primal system

```python
lca.lci(factorize=True)
```

One LU factorization of **A**, then one back-substitution to solve

```
A s = f
```

where `f` is the functional-unit demand vector. This gives:

- `lca.supply_array` = **s**, the scaling vector — how much of every product in
  the entire system, foreground and background, is needed
- `lca.inventory` = **B · diag(s)**, elementary flows × activities

`factorize=True` matters: it keeps the LU factors on the object so later solves
are back-substitutions rather than fresh factorizations. This is the only
forward solve the whole request will ever need.

---

## Phase B — Everything that is cheap once A is factorized

### Step 4. Aggregate the inventory (LCI)

Row-sum the inventory and map each row index back through
`lca.dicts.biosphere.reversed` to a flow name and unit. Drop near-zero rows.

```python
total_inv = np.asarray(lca.inventory.sum(axis=1)).ravel()
```

One sparse reduction. Effectively free.

### Step 5. Compute the impact category totals listed in the YAML

```python
configured_methods = resolve_methods(spec["lcia"]["categories"])
for i, method_tuple in enumerate(configured_methods):
    if i:
        lca.switch_method(method_tuple)
    lca.lcia()
    lcia[label] = float(lca.score)
```

`switch_method` swaps only **C**. `lcia()` forms `C · B · diag(s)` and sums.
**Neither re-solves anything** — `s` is already known and is independent of the
impact category. Even so, the engine deliberately computes only the explicitly
listed categories so it does not build, serialize, transfer, or display unused
direct-contribution tables.

Each iteration leaves `lca.characterized_inventory` available, which is the
input to the next step.

### Step 6. Direct scores for every activity, foreground and background, for each listed category

Inside the same loop, sum down the columns:

```python
column_totals = np.asarray(lca.characterized_inventory.sum(axis=0)).ravel()
```

Entry *j* is the impact emitted **directly** by activity *j* at its solved scale
— no upstream. Every column is here: our foreground processes, and every
ecoinvent activity the supply chain touches.

Walk the nonzero entries, map each index through `lca.dicts.activity.reversed`
to a node, and emit a row tagged `scope: "foreground"` or `"background"`
depending on whether the node belongs to our temporary database.

Two things to note. First, this is a complete, exact decomposition — the direct
scores over all activities sum to the total, so we assert reconciliation and
there is no residual to explain away. Second, and this is the important one:
**this is a full contribution table that required no graph traversal at all.**
"Which processes emit the most, directly" is answerable for every category
listed in the YAML in Phase B. Only the *tree* — who consumed whom, and
cumulative-through-the-chain numbers — needs Phase C.

### Step 7. Physical flow Sankey from the scaling vector

Walk the YAML's declared processes and exchanges, and for each link use `s` to
get the actual amount flowing. This is the mass/energy picture — kg of yarn, kWh
of electricity — not an impact picture. It is pure bookkeeping over the spec
plus a lookup into `s`, so it belongs here in the cheap phase.

### Step 8. Bound the background topology

For the background providers our foreground attaches to, walk their technosphere
exchanges outward to build a structural graph the client can expand locally
without another round trip.

Bound it by **topology only**: max depth, max unique activities, max exchanges,
max direct biosphere records. Do not cut by exchange magnitude — the graph mixes
kg, kWh, tkm and m³, and comparing raw magnitudes across units silently
privileges whichever units happen to be large. Do not cut by impact either;
impact is category-specific and that is precisely what we are deferring. Record
*which* limit stopped each branch so the client can render "bounded here"
honestly rather than implying completeness.

### Call 1 returns

After step 8: inventory, the YAML-listed category totals, scaling vector,
direct-score contributions for those categories, physical Sankey, bounded
background topology, and a `result_id` = hash of the normalized YAML plus
method name.

---

## Phase C — The lazy part: one impact category's contribution tree

This is what a user triggers by opening a category. It needs cumulative scores —
for each node in the tree, the impact of that node *including everything upstream
of it*.

### Step 9. Understand what the tree actually needs

A priority-first traversal expands the highest-scoring unexpanded node, and stops
at `cutoff × total_score`, at `max_depth`, or at a node budget. To decide whether
a child is worth expanding it needs that child's cumulative score. So the one
quantity the traversal repeatedly asks for is:

> for one unit of product *p*, what is the total impact of producing it, whole
> supply chain included?

Call that `unit_score[p]`. The naive way to get it is a linear solve per
product: set demand to `e_p`, solve, characterize. For our examples that is
700–900 solves per category, and it is the entire reason a contribution tree
costs seconds instead of milliseconds.

### Step 10. Get all of them at once with the adjoint solve

Write the naive computation out. Let **c** be the characterization vector for
this category. The direct-intensity row is

```
d = cᵀB          (one entry per activity: impact emitted per unit of activity output)
```

and the naive per-product answer is

```
unit_score[p] = (cᵀB) · A⁻¹ · e_p
```

That is a row vector, times an inverse, times a basis vector. Regroup by
associativity — push the inverse onto the *left* factor instead of the right:

```
unit_score[p] = ( A⁻ᵀ (cᵀB)ᵀ )ᵀ e_p  =  y_p        where     Aᵀ y = Bᵀc
```

Nothing is approximated. The naive loop is solving the same system 800 times
with 800 different right-hand sides `e_p` and extracting one number from each.
Transposing the system lets us solve **once**, with the single right-hand side
`Bᵀc`, and read off *all* 800 numbers — in fact all products' numbers — from the
answer vector.

```
A s = f        primal — one demand, all supplies
Aᵀ y = Bᵀc     adjoint — one impact category, all cumulative intensities
```

It is the same structure as reverse-mode autodiff: one backward pass gives the
sensitivity of a single scalar output to every input at once, rather than one
forward pass per input.

The vocabulary, so the two vectors don't get confused:

| | indexed by | meaning |
|---|---|---|
| `d = Bᵀc` | activities | impact **directly** emitted per unit of that activity |
| `y = A⁻ᵀd` | **products** | impact **cumulatively** caused per unit of that product |

`y` is indexed by the rows of A, which are products, not activities. In a
database with non-diagonal production or multi-output activities those differ,
and getting it wrong produces errors exactly where they are hardest to spot.
Keep the two index spaces separate in the code.

Immediate correctness check: `yᵀf` must equal `lca.score`.

### Step 11. Factorize Aᵀ

The factorization from step 3 is of **A**, and we need **Aᵀ**. SuperLU objects
can in principle solve transposed, but the factorization bw2calc keeps is wrapped
in a closure that does not expose that option, so plan on doing our own:

```python
from scipy.sparse.linalg import splu

lu_T = splu(lca.technosphere_matrix.tocsc().T.tocsc())
```

One extra factorization. Against 800 back-solves, this is a large net win on any
platform and with any backend, so it is not worth engineering around.

### Step 12. Solve for this category and traverse with pure arithmetic

```python
d = np.asarray((C @ B).sum(axis=0)).ravel()   # direct intensities, per activity
y = lu_T.solve(d)                             # cumulative intensities, per product
```

Now every number the tree needs is a multiplication. With `A` in CSC form so a
column is O(nnz):

- **cumulative score** of an occurrence of product *p* supplied at amount *s*:
  `y[p] * s`
- **direct score** of activity *j* at supply `s_j`: `d[j] * s_j`
- **edge i → j**: amount consumed is `-A[i, j] * s_j` (inputs sit as negative
  off-diagonal entries); its cumulative score is `y[i] * (-A[i, j] * s_j)`
- **biosphere flow k at activity j**: amount `B[k, j] * s_j`, score
  `c[k] * B[k, j] * s_j`
- **unexpanded score** at a node: `cumulative − direct − Σ(children cumulative)`.
  This stays exactly right even though the displayed tree is truncated, because
  `y` already accounts for cycles and infinite regress analytically — truncation
  affects only what we *render*, never the totals.

The traversal is then: pull column *j*, multiply by `y`, sort children by score,
recurse where `|score| > cutoff × total`, stop at the depth and node bounds.
Sparse arithmetic and bookkeeping, no solves.

### Step 13. Serve the tree and the impact Sankey from the same object

A Sankey over impact is the same node-and-edge set as the contribution tree, with
edge widths taken from the cumulative score already attached to each edge. Build
the graph once and derive both views. No separate Sankey endpoint, no second
traversal, no risk of the two views disagreeing.

Note the two Sankeys are different things and both are worth having: the one from
step 7 is physical flows and is free in Call 1; this one is impact flows for a
specific category and belongs in Call 2.

### Call 2 returns

One contribution graph for one category.

---

## Phase D — The optimizations, in the order they become worth doing

Everything below is optional and each is independent. This is a ladder; climb it
only as far as measurement justifies.

### Optimization 1 — batch categories within a single Call 2

`lu_T` from step 11 does not depend on the impact category. Only the right-hand
side `Bᵀc` does. So for *k* categories in one request:

```
1 foreground build  +  1 factorization of A  +  1 factorization of Aᵀ
+  k back-substitutions  +  k sparse traversals
```

The marginal cost of the second, third, tenth category in the same request is a
back-substitution and some sparse arithmetic — milliseconds. This means the
endpoint should accept a **list** of categories, not one, even if the client
initially sends lists of length one. Once that shape is in place, the client can
prefetch on hover, or fetch the three categories a user is most likely to open,
at nearly the price of one.

It also means the reason to stay lazy is now purely **payload size**, not time.
Computing all 25 categories eagerly would be cheap; shipping 12 MB of JSON to a
browser would not be. Laziness is a bandwidth-and-parse decision, and it survives
every optimization below.

### Optimization 2 — reuse the setup across calls, keyed by `result_id`

Call 1 returns `result_id = hash(normalized_yaml + method_name)`, and Call 2
accepts it. Initially the server ignores it and rebuilds everything. That keeps
the first implementation fully stateless — no sessions, no cache invalidation, no
polling.

When the fixed ~2.7 s setup becomes the bottleneck, cache behind that key with a
TTL: the foreground database, the factorization of A, and the factorization of
Aᵀ. On a hit, Call 2 drops to a back-substitution plus traversal — tens of
milliseconds. On a miss, rebuild. Neither the API contract nor the client
changes.

The field costs nothing to add now and cannot be retrofitted later without a
client change, so add it now even though nothing reads it.

### Optimization 3 — precompute `y` for the categories most likely to be opened

Once setup is cached, we can go further: during Call 1, after step 5, also
factorize Aᵀ and solve for the two or three highest-scoring categories, and stash
the `y` vectors alongside the cached factorization. Then those categories' Call
2s are traversal-only.

This is speculative work, so gate it on evidence that users actually open the
top-scoring categories. It is cheap to add and cheap to remove.

### Optimization 4 — return the tree progressively

If very large trees are still slow to render, the traversal in step 12 can emit
nodes in priority order and stop at a client-supplied node budget, with a
continuation token to fetch deeper. Since `y` is fully known before traversal
begins, resuming a traversal is free — there is no state to reconstruct beyond
the frontier. Only do this if payload remains a problem after per-category
laziness.

### Optimization 5 — lock granularity

The foreground build in step 1 needs exclusivity because Brightway's project
state is global. The linear algebra in Phases B and C does not touch global state
and does not need the lock. Splitting the lock so it covers only database
creation and teardown lets concurrent requests overlap on the expensive-but-safe
parts. Worth doing before any multi-user deployment; unnecessary for single-user
work.

---

## What we verify, and when

**At step 10, before anything is built on it:** compare `y[p]` against a
per-product naive solve `d · A⁻¹e_p` for a sample of products on a real BAFU
example. Comparing the intensity vectors directly localizes any bug to either the
math or the indexing; comparing final tree scores does not.

**At step 12:** assert `yᵀf == lca.score`, and that the reconstructed cumulative
score at the root equals the category total from step 5. Two independent paths to
the same number.

**At step 6:** assert direct scores over all activities sum to the total, per
category.

**Across the split:** Call 1 plus Call 2 for a given category must produce
numerically identical output to a single combined run with that category
requested. Assert this in tests against the fast mock examples so it runs on
every change.

**On the benchmark suite:** record Call 1 and Call 2 times separately, before and
after the adjoint change, so the ladder in Phase D is climbed on evidence rather
than intuition.
