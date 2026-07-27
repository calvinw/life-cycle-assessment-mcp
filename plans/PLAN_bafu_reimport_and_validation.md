# Plan: Reimport and Validate BAFU for Brightway

## Status

Deferred until the mock-background contribution graph and web-app behavior are
implemented and stable.

## Summary

Replace the current lossy BAFU import with a reproducible, isolated import that
preserves the elementary-flow identities, units, geographic distinctions, and
LCIA compatibility needed to reproduce OpenLCA results.

Do not debug the background contribution graph and the BAFU importer at the
same time. Complete the contribution graph against `mock_background` first.
BAFU then becomes a separately validated database integration.

Use the OpenLCA BAFU database and OpenLCA LCIA Methods 2.8.0 package as the
cross-engine reference. Do not replace the existing Brightway database until a
candidate import passes inventory, linkage, and all-category LCIA checks.

---

## Why a Reimport Is Necessary

The current importer:

1. Parses a non-standard BAFU EcoSpold 1 export with a custom parser.
2. Rewrites BAFU biosphere flow names and categories through a CSV crosswalk.
3. Collapses regional flows such as `Water, CH`, `Water, ES`, and `Water, DE`
   into generic `Water`.
4. Links biosphere exchanges by name and category without requiring unit
   equality.
5. Allows kilogram water exchanges to link to cubic-metre biosphere flows.
6. Drops unlinked exchanges.
7. Installs Brightway's default EF v3.1 methods instead of the OpenLCA
   `EF 3.1 Method (adapted)` flow vocabulary used for the reference result.

This produces a mathematically valid Brightway matrix whose biosphere and LCIA
semantics are not equivalent to the OpenLCA BAFU database.

The plastic broom demonstrates the failure:

| Result | Water use |
|---|---:|
| Current Brightway REST result | 16.4141017036 m3 world eq. deprived |
| OpenLCA EF 3.1 adapted reference | 0.101175803168 m3 world eq |
| Current/OpenLCA ratio | 162.233 |

The OpenLCA Water-use category contains 12,924 characterization factors,
including regional resource-water flows. The installed Brightway category has
only five generic Water-to-air factors, all with a factor of 42.95.

---

## External Evidence

- Brightway's import documentation says EcoSpold 1 identifiers cannot always
  be trusted and describes import/linking as an iterative harmonization
  process.
- The same documentation gives the exact ecoinvent 2 migration relevant here:
  Water-to-air exchanges in kilograms must be converted to cubic metres with a
  `0.001` multiplier, including rescaling uncertainty data.
- Brightway's standard EcoSpold 1 importer includes `unit` in technosphere
  matching and its LCIA importer links characterization factors using name,
  category, unit, and location.
- Chris Mutel has stated that the current BAFU EcoSpold 1 files are not
  compliant with the specification and do not work with
  `SingleOutputEcospold1Importer`; the proposed alternative import was still
  described as work in progress.

References:

- https://docs.brightway.dev/en/latest/content/overview/importing.html
- https://stackoverflow.com/questions/79861324/how-to-resolve-a-failure-when-trying-to-import-bafu-db-using-brightway

---

## Goals

1. Preserve stable BAFU activity, product-flow, and elementary-flow identities.
2. Preserve flow units, flow properties, compartments, and regional identity.
3. Import an LCIA method whose factors reference the same elementary flows.
4. Produce a complete audit of linked, unlinked, converted, and omitted
   exchanges.
5. Reproduce the OpenLCA plastic-broom results across all 25 EF 3.1 adapted
   categories within an agreed tolerance.
6. Keep the current BAFU database available for comparison and rollback until
   the replacement is accepted.
7. Make future BAFU versions repeatable through pinned artifacts and automated
   validation.

## Non-Goals

- Implementing the contribution graph.
- Debugging contribution cutoffs or web rendering.
- Silently forcing every BAFU flow into `biosphere3`.
- Declaring success based only on climate change and acidification.
- Dropping unmatched exchanges without an explicit reviewed allowlist.

---

## Reference Artifacts

Pin and record checksums for:

1. BAFU-2026 v1 OpenLCA database archive.
2. BAFU-2026 v1 OpenLCA JSON-LD archive.
3. BAFU-2026 v1 EcoSpold 1 archive.
4. OpenLCA LCIA Methods 2.8.0 archive.
5. Plastic-broom foreground JSON-LD and YAML.
6. The 25 OpenLCA EF 3.1 adapted scores supplied for one plastic broom.

The existing provider manifest already pins the three foreground provider
UUIDs and Brightway codes. Preserve that identity check in the new validation
suite.

---

## Import Candidates

Evaluate both candidates in disposable Brightway projects. Do not choose based
only on which one imports first.

### Candidate A — OpenLCA JSON-LD as source of truth

1. Import BAFU activities, product flows, and elementary flows from the
   OpenLCA JSON-LD archive.
2. Preserve UUIDs as Brightway codes.
3. Import the OpenLCA EF 3.1 adapted method and its referenced flows.
4. Keep the BAFU/OpenLCA biosphere namespace separate from `biosphere3`.
5. Verify whether process count differences between the OpenLCA and EcoSpold
   archives represent aggregation, omitted datasets, or export structure.

This is the preferred candidate because it minimizes transformations and keeps
the database and LCIA method on the same flow vocabulary.

### Candidate B — Corrected EcoSpold import

1. Retain the BAFU-specific parser required by the non-compliant files.
2. Replace the current generic crosswalk with explicit, versioned migrations.
3. Make every migration unit-aware and region-aware.
4. Create or retain a BAFU-specific biosphere database instead of collapsing
   flows into `biosphere3`.
5. Map the OpenLCA EF 3.1 adapted factors to preserved BAFU flow identities.
6. Use Brightway's exchange-rescaling utilities so amounts, uncertainty
   parameters, and formulas are converted together.

Use this candidate only if JSON-LD cannot preserve the process graph or
calculation behavior needed by Brightway.

---

## Phase 1 — Freeze the Reference

1. Add the 25 OpenLCA plastic-broom scores to a machine-readable fixture.
2. Record category names, units, method name, database version, and foreground
   provider UUIDs.
3. Add a comparison report showing absolute and relative Brightway/OpenLCA
   differences.
4. Record current-import counts: activities, technosphere exchanges,
   biosphere exchanges, unlinked exchanges, and LCIA factors.

## Phase 2 — Build an Isolated Import Harness

1. Create a disposable Brightway project per import attempt.
2. Never mutate the active `lca_server` project during evaluation.
3. Emit a structured import report rather than relying on console output.
4. Fail on unit-incompatible links.
5. Fail when unlinked exchanges remain unless each is in a reviewed allowlist.
6. Record every migration with source identity, target identity, multiplier,
   and rationale.

## Phase 3 — Evaluate Candidate A

1. Import the BAFU OpenLCA JSON-LD database.
2. Import the OpenLCA LCIA method package.
3. Verify external references and default providers.
4. Verify the three plastic-broom provider UUIDs.
5. Run inventory and EF 3.1 adapted calculations.
6. Produce the full 25-category comparison.

## Phase 4 — Evaluate Candidate B if Needed

1. Audit EcoSpold deviations from the specification.
2. Implement explicit migrations, beginning with water kg-to-m3 conversion.
3. Preserve regional water identities.
4. Import or construct a compatible BAFU biosphere namespace.
5. Link the adapted LCIA factors.
6. Produce the same full comparison report used for Candidate A.

## Phase 5 — Select and Harden

1. Select the candidate with complete graph linkage and best reference parity.
2. Add deterministic tests for parsing, migrations, units, and identities.
3. Add a no-silent-drop test.
4. Add database version and source checksums to Brightway metadata.
5. Benchmark startup, search projection, and LCA calculation time.
6. Document upgrade and rollback procedures.

## Phase 6 — Controlled Cutover

1. Install the candidate under a versioned database name.
2. Run the complete test suite and OpenLCA comparison again.
3. Switch the application alias/configuration only after acceptance.
4. Retain the old database until the new version has been exercised by the
   REST API and contribution-graph integration.
5. Remove the old import only in a separate, explicitly approved cleanup.

---

## Validation Matrix

### Structural validation

- Activity and product-flow counts are explained and stable.
- Every technosphere input resolves to the intended provider.
- Every biosphere exchange resolves to a unit-compatible flow.
- Regional flows remain regional where the method requires regional factors.
- No unmatched exchange is silently discarded.
- No duplicate provider identity is introduced by name-based matching.

### Numerical validation

- The plastic broom matches all 25 OpenLCA EF 3.1 adapted scores.
- Climate change and acidification remain close to their existing baselines.
- Water use matches approximately `0.101175803168 m3 world eq`.
- Toxicity and ecotoxicity categories are validated explicitly because the
  current import differs materially in several of them.
- At least two additional BAFU activities from different sectors are compared
  with OpenLCA to avoid overfitting the importer to the broom.

### Operational validation

- REST calculation works with the versioned candidate database.
- Search and activity-input endpoints expose the expected activities.
- Import reports and comparison reports are reproducible from pinned inputs.
- The active production project is unchanged by failed candidate imports.

---

## Acceptance Criteria

The BAFU reimport is complete only when:

1. A clean, pinned import can be reproduced in a new Brightway project.
2. No source/target unit mismatch is silently linked.
3. No unlinked exchange is silently dropped.
4. Regional BAFU water flows and adapted EF factors retain compatible
   identities.
5. All 25 plastic-broom scores match OpenLCA within the agreed tolerance or
   have a documented, reviewed explanation.
6. Provider identities and recursive technosphere linkage are verified.
7. At least two non-broom BAFU datasets pass cross-engine checks.
8. Import, validation, upgrade, and rollback procedures are documented.
9. The validated database can be used by the already-tested background
   contribution graph without graph-engine changes.
