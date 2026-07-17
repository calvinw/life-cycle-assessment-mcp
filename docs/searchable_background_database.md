# Searching the LCA Background Database

This guide explains how a searchable background database helps us build better
Life Cycle Assessment (LCA) product graphs.

The important idea is simple: before calculating a product's environmental
impact, we can investigate the background data that will be used in the
calculation.

We do not need to know database language or write database queries. We can ask
questions in ordinary language, such as:

- What kinds of polylactide are available?
- Is there a Swiss version of this transport process?
- What does this cotton-yarn process actually include?
- Are there different aluminium mixes for cast and wrought products?
- Which processes use this particular material?
- Does this process emit carbon dioxide directly?

The LCA MCP translates those questions into searches of the background
inventory and returns understandable process names, locations, units, inputs,
and environmental flows.

The examples in this guide use real records returned by the remote LCA MCP
server on July 16, 2026.

## Why search before calculating?

A product graph describes the product we want to study. For example, a simple
plastic broom might contain:

- 0.52 kg of polylactide plastic;
- 0.03 kg of nylon; and
- transport of those materials to the assembly location.

That description makes sense to a person, but the LCA calculation needs more
specific information:

- Which polylactide production process should be used?
- Is it global, European, Swiss, or American?
- Does the process produce kilograms, tonnes, or another unit?
- Is the transport process a European or Swiss vehicle fleet?
- Does the selected material process include electricity, fuel, farming, and
  waste treatment?
- Are there several similarly named processes with different technologies?

If we calculate without answering those questions, the computer may produce a
precise number from a poorly understood model.

Searching lets us examine the available evidence first. We can then make the
product graph more explicit and explain why each background process was chosen.

## A simple mental model

Think of the background database as a very large recipe book.

Each background process is a recipe for making something:

```text
Recipe: make 1 kg of material

Needs:
  electricity
  natural gas
  transport
  other materials

Releases:
  carbon dioxide
  other emissions
  waste heat

Produces:
  1 kg of material
```

The things needed by one recipe are produced by other recipes. Electricity has
its own recipe. Natural gas has its own recipe. Transport has its own recipe.
This creates a large connected supply network.

```text
Plastic broom
    |
    +-- polylactide
    |      |
    |      +-- corn farming
    |      +-- electricity
    |      +-- natural gas
    |
    +-- nylon
    |      |
    |      +-- chemicals
    |      +-- energy
    |
    +-- freight transport
           |
           +-- trucks
           +-- diesel
```

The searchable database helps us look at the recipes and the direct
connections between them. Brightway then follows the complete network and
performs the LCA calculation.

## The two layers of a product graph

A useful product graph often combines two types of modeling.

### Foreground processes

These are the parts we describe ourselves because they define the product or
scenario being studied. Examples include:

- assembling one broom;
- making one T-shirt;
- combining several materials into a product casing; or
- transporting a finished product a specified distance.

### Background processes

These are established inventory datasets that provide the upstream recipes for
materials, electricity, fuel, transport, waste treatment, and other services.

The foreground graph might say that broom assembly needs 0.52 kg of PLA. The
background database supplies the much larger recipe behind that PLA.

```text
Foreground statement:   use 0.52 kg of PLA

Background detail:      corn production
                        electricity production
                        industrial heat
                        natural gas supply
                        freight transport
                        waste treatment
                        direct emissions
```

Search is the bridge between the short foreground statement and the detailed
background inventory.

## The main kinds of searches

### 1. Discovery search: “What is available?”

We use discovery search when we know the kind of material or service we need,
but we do not know the database's exact terminology.

Example questions:

- What cotton-fibre processes are available?
- Find processes related to recycled aluminium.
- What freight-transport processes are in the database?
- Are there any polylactide or PLA production processes?

Why this search matters:

Database names are often more technical than everyday language. A search can
look across process names, reference products, comments, categories,
classifications, and synonyms. It lets us discover the database rather than
guessing exact names.

### 2. Identity search: “Which exact record is this?”

We use identity search after finding a promising process. It confirms:

- its exact name;
- its database and unique code;
- its geographic location;
- its reference product; and
- its reference unit.

Why this search matters:

Two processes can have the same name but different locations. Two similar
names can represent different product forms. A unit mismatch can make an
otherwise sensible graph wrong by a factor of 1,000 or more.

### 3. Alternative search: “What other choices could we use?”

We use alternative search to find processes that could reasonably represent
the same foreground need.

Example questions:

- Is there both a global and a US process for PLA?
- Is there a European and a Swiss freight-transport process?
- Are there separate aluminium mixes for cast, wrought, and profile products?
- Are there electricity processes for different countries?

Why this search matters:

The first search result is not necessarily the best modeling choice. Location,
technology, recycled content, and production method can all affect the result.
Finding the alternatives makes those choices visible.

### 4. Recipe search: “What is inside this process?”

We use recipe search to inspect a process's direct inputs and releases.

Example questions:

- What materials and energy does this process consume?
- Which electricity grid does it use?
- Does it consume primary or recycled material?
- What does it release to the environment?
- Does it include transport or waste treatment?

Why this search matters:

A process name is only a label. Looking inside the recipe tells us what the
dataset actually models. This is one of the best ways to discover hidden
assumptions and incomplete system boundaries.

### 5. Comparison search: “How are these candidates different?”

We use comparison search after alternative search finds several plausible
records.

Example questions:

- How do global PLA and Nebraska PLA differ?
- How much primary and recycled aluminium is in each production mix?
- How do the European and Swiss truck fleets differ?
- Do two electricity datasets use different fuels?

Why this search matters:

Names alone rarely explain the important differences. Comparing recipe inputs
makes technology and supply assumptions concrete.

### 6. Boundary search: “Does this process include what we think it includes?”

We use boundary search when a process name appears to describe a complete
product system.

Example questions:

- Does “cotton yarn production” include cotton cultivation?
- Does a plastic process include making the polymer or only shaping it?
- Does a transport process include vehicle manufacture?
- Does an assembly process include the product materials?

Why this search matters:

An LCA can run successfully even when important life-cycle stages are missing.
Boundary search tests whether the selected recipe matches the intended scope of
the study.

### 7. Reverse search: “Who uses this material or process?”

Most product graphs move from a product to its suppliers. Reverse search moves
in the other direction.

Example questions:

- Which processes directly use this PLA dataset?
- Which products consume this electricity process?
- Where is this chemical used?
- Which activities release this particular environmental flow?

Why this search matters:

Reverse search helps us understand how important a dataset is across the wider
database. If a heavily used supplier is corrected or replaced, many product
systems may be affected.

### 8. Quality search: “Is anything missing or suspicious?”

We use quality search to look for potential data problems.

Example questions:

- Which processes have no location?
- Which records have no unit?
- Does a process have no environmental exchanges?
- Are any exchange amounts unexpectedly zero or negative?
- Are there formulas or uncertainty values attached to the inputs?

Why this search matters:

Search does not prove that a dataset is correct, but it can reveal records that
deserve closer review before they are used.

## Detailed example 1: choosing the PLA for a plastic broom

### The first product graph

We begin with a rough description:

```yaml
name: Plastic broom - 1 unit

functional_unit:
  description: 1 plastic broom
  amount: 1.0
  unit: unit

products:
  - { name: Plastic broom, unit: unit }

processes:
  - name: Plastic broom assembly
    reference_output: { flow: Plastic broom, amount: 1.0, unit: unit }
    inputs:
      - { flow: Polylactide granulate, amount: 0.52, unit: kg }
      - { flow: Nylon 6, amount: 0.03, unit: kg }
      - { flow: Freight transport, amount: 0.1055, unit: tkm }

reference_process: Plastic broom assembly

lcia:
  method_name: EF v3.1
```

This expresses the basic idea, but the background links are too vague.

### Search 1: discover available PLA processes

We ask the LCA MCP:

> Search the BAFU database for polylactide granulate.

Why we search:

“PLA” is an everyday abbreviation, while the database uses “Polylactide.” We
need to discover the available processes and their exact names.

The search finds two candidates:

| Process | Location | Unit | Database code |
|---|---:|---|---:|
| Polylactide, granulate, at plant | GLO | kilogram | `273090` |
| xxx Polylactide, granulate, NatureWorks Nebraska | US | kilogram | `594650` |

What we learn:

- There is not just one PLA process.
- Both candidates use kilograms, so either is compatible with the graph's
  material amount.
- One represents global production and the other identifies a US producer and
  location.

### Search 2: compare the PLA recipes

We ask:

> Compare the direct inputs of the global PLA process and the Nebraska PLA
> process. What are the important differences?

Why we search:

The two names suggest a geographic difference, but they do not tell us whether
the production technologies differ.

Both recipes contain:

- 18.46 MJ of industrial-furnace natural gas;
- 1.507 kg of US corn;
- 0.2 tonne-kilometres of European lorry transport;
- smaller quantities of fuel, waste treatment, and infrastructure; and
- direct waste heat and other environmental flows.

The clearest difference is electricity:

| PLA candidate | Direct electricity input per kg PLA |
|---|---|
| Global PLA | 1.828 kWh of ENTSO-E low-voltage electricity |
| Nebraska PLA | 1.9925 kWh of electricity at a wind farm |

What we learn:

The process choice changes more than the location label. It also changes the
electricity technology represented by the background recipe. That may affect
the calculated impacts.

### Search 3: identify the correct nylon process

We ask:

> Find Nylon 6 processes in the BAFU database.

Why we search:

We want ordinary Nylon 6, but there may be specialized products with similar
names.

The search finds:

- `Nylon 6, at plant`, located in RER; and
- `xx Nylon 6, glass-filled, at plant`, also located in RER.

What we learn:

Glass-filled nylon is a different material. The product graph should explicitly
use ordinary `Nylon 6, at plant` unless the broom design calls for glass-filled
nylon.

### Search 4: choose the transport geography

We ask:

> Find the 16-32 tonne fleet-average lorry transport processes.

Why we search:

The phrase identifies a vehicle class but not a regional fleet.

The database contains the same transport name in two locations:

| Transport process | Location | Unit | Code |
|---|---:|---|---:|
| 16-32t fleet-average freight lorry | RER | tonne-kilometre | `355963` |
| 16-32t fleet-average freight lorry | CH | tonne-kilometre | `491435` |

Looking inside the recipes shows that:

- the RER process is a mix of European diesel trucks from several emissions
  standards and duty cycles; and
- the CH process contains Swiss diesel trucks plus small shares of compressed
  gas, biomethane, and battery-electric vehicles.

What we learn:

The transport location is a real modeling assumption. If the material is moved
within Switzerland, CH may be the better choice. If it represents general
European transport, RER may be more appropriate.

### The improved graph

Assume this study is intended to represent generic global PLA, ordinary
European Nylon 6, and general European freight transport. The graph becomes:

```yaml
name: Plastic broom - 1 unit
goal: >
  Estimate the impacts of one plastic broom using global PLA, European Nylon 6,
  and European fleet-average freight transport.

functional_unit:
  description: 1 plastic broom
  amount: 1.0
  unit: unit

products:
  - { name: Plastic broom, unit: unit }

processes:
  - name: Plastic broom assembly
    reference_output: { flow: Plastic broom, amount: 1.0, unit: unit }
    inputs:
      - flow: Polylactide, granulate, at plant
        location: GLO
        database: bafu
        amount: 0.52
        unit: kg
      - flow: Nylon 6, at plant
        location: RER
        database: bafu
        amount: 0.03
        unit: kg
      - flow: Transport, freight, lorry, 16t-32t gross weight, fleet average
        location: RER
        database: bafu
        amount: 0.1055
        unit: tkm

reference_process: Plastic broom assembly

lcia:
  method_name: EF v3.1
```

### The advantage of search in this example

The original graph contained three reasonable human descriptions. Search
turned them into three explicit, reviewable background choices. It also found
two meaningful scenarios we could calculate later:

- global PLA versus Nebraska PLA; and
- European transport versus Swiss transport.

## Detailed example 2: checking what “cotton yarn” includes

### The proposed product graph

Suppose we want to model one kilogram of cotton fabric:

```yaml
name: Cotton fabric - 1 kg

functional_unit:
  description: 1 kg cotton fabric
  amount: 1.0
  unit: kg

products:
  - { name: Cotton fabric, unit: kg }

processes:
  - name: Cotton fabric production
    reference_output: { flow: Cotton fabric, amount: 1.0, unit: kg }
    inputs:
      - flow: Yarn production, cotton fibres
        location: GLO
        database: bafu
        amount: 1.05
        unit: kg

reference_process: Cotton fabric production

lcia:
  method_name: EF v3.1
```

The graph appears to use a cotton-yarn background process. But does that process
include growing the cotton?

### Search 1: confirm the process identity

We ask:

> Find the process named “Yarn production, cotton fibres.”

Why we search:

We first need to verify that the process exists and that its unit is compatible
with the graph.

The database finds one record:

| Process | Location | Unit | Code |
|---|---:|---|---:|
| Yarn production, cotton fibres | GLO | kilogram | `479017` |

The identity and unit look suitable.

### Search 2: inspect the process boundary

We ask:

> Show every direct material, energy, transport, and environmental exchange in
> the cotton-yarn process. Does it consume cotton fibre?

Why we search:

The process name could mean either:

1. production of yarn starting with cotton fibre; or
2. a complete cotton-yarn supply chain including farming and fibre production.

The direct recipe contains:

| Type | Input or release | Location | Amount |
|---|---|---:|---:|
| Energy | Low-voltage electricity | CN | 5.1 kWh |
| Energy | Low-voltage electricity | US | 3.4 kWh |
| Transport | 16-32t lorry transport | RER | 0.45 tkm |
| Packaging | Packaging box production | RER | extremely small |
| Environmental release | Waste heat | environment | 30.6 MJ |

There is no cotton-fibre input.

### What the search reveals

Despite its name, this process is essentially a yarn-spinning operation driven
by electricity. It does not model cotton cultivation or cotton-fibre
production.

If we use it as though it were complete cradle-to-gate cotton yarn, the
calculation can omit farming, irrigation, fertilizer, ginning, and fibre
preparation while still returning a plausible-looking result.

### Two possible modeling decisions

#### Decision A: keep a spinning-only boundary

If the study is intended to examine spinning, state that clearly:

```yaml
name: Cotton yarn spinning - 1 kg
goal: >
  Model the BAFU cotton-yarn spinning operation. Cotton cultivation and fibre
  production are outside this study boundary.

functional_unit:
  description: 1 kg of cotton-yarn spinning output
  amount: 1.0
  unit: kg

products:
  - { name: Cotton-yarn spinning output, unit: kg }

processes:
  - name: Cotton-yarn spinning model
    reference_output: { flow: Cotton-yarn spinning output, amount: 1.0, unit: kg }
    inputs:
      - flow: Yarn production, cotton fibres
        location: GLO
        database: bafu
        amount: 1.0
        unit: kg

reference_process: Cotton-yarn spinning model

lcia:
  method_name: EF v3.1
```

#### Decision B: build a broader cotton system

If the goal is cradle-to-gate cotton yarn, perform another discovery search for
cotton-fibre and farming processes. Add the selected fibre supply explicitly,
or choose a different background dataset that already includes it.

### The advantage of search in this example

Search did not merely help us spell a process name. It prevented a system
boundary mistake. It showed that the label “cotton yarn production” describes
a narrower recipe than a reader might assume.

## Detailed example 3: selecting aluminium for a product casing

### The first product graph

```yaml
name: Aluminium casing - 1 kg

functional_unit:
  description: 1 kg of aluminium casing material
  amount: 1.0
  unit: kg

products:
  - { name: Aluminium casing material, unit: kg }

processes:
  - name: Casing material supply
    reference_output: { flow: Aluminium casing material, amount: 1.0, unit: kg }
    inputs:
      - flow: Aluminium, production mix, at plant
        location: RER
        database: bafu
        amount: 1.0
        unit: kg

reference_process: Casing material supply

lcia:
  method_name: EF v3.1
```

This graph chooses a generic European aluminium mix. Before accepting it, we
should find out what alternatives exist.

### Search 1: discover aluminium production mixes

We ask:

> Find aluminium production-mix processes suitable for one kilogram of
> material. Include their product form and location.

Why we search:

“Aluminium” can mean cast alloy, wrought alloy, extrusion/profile material, or
a generic mix. Product form matters for a casing.

The database finds these candidates:

| Candidate | Location | Code |
|---|---:|---:|
| Generic aluminium production mix | RER | `436582` |
| Cast-alloy production mix | RER | `280747` |
| Wrought-alloy production mix | RER | `260403` |
| Aluminium-profile production mix, SZFF 2014 | CH | `398286` |

All four use kilograms, so unit compatibility does not decide between them.

### Search 2: compare primary and recycled aluminium

We ask:

> For each candidate, show how one kilogram is divided among primary
> aluminium, secondary aluminium from new scrap, and secondary aluminium from
> old scrap.

Why we search:

The amount of primary and recycled aluminium can strongly influence the
environmental impact. The process names do not reveal those percentages.

The recipes show:

| Candidate | Primary | New-scrap secondary | Old-scrap secondary |
|---|---:|---:|---:|
| Generic European mix | 51.226% | 31.301% | 17.473% |
| European cast alloy | 44.123% | 11.334% | 44.543% |
| European wrought alloy | 53.644% | 38.099% | 8.257% |
| Swiss profile mix | 48.343% | 42.456% | 9.201% |

### What the search reveals

The four records are not interchangeable:

- the cast-alloy mix contains the largest share of old-scrap aluminium;
- the wrought-alloy mix contains the largest primary-aluminium share;
- the Swiss profile mix represents a specific geography and product form; and
- the generic European mix is useful only if a more specific form is not
  justified.

### Choosing the graph

The right choice depends on the physical product:

- A cast housing should probably use the cast-alloy mix.
- A rolled or formed casing may be better represented by wrought alloy.
- An extruded Swiss profile may justify the Swiss profile process.
- A conceptual design with no manufacturing specification may retain the
  generic European mix and test other mixes as scenarios.

For a cast European casing, the revised input would be:

```yaml
processes:
  - name: Cast casing material supply
    reference_output: { flow: Aluminium casing material, amount: 1.0, unit: kg }
    inputs:
      - flow: Aluminium, production mix, cast alloy, at plant
        location: RER
        database: bafu
        amount: 1.0
        unit: kg
```

### The advantage of search in this example

Search turned a generic material assumption into an engineering question:
what type of aluminium product is the casing actually made from? It also
revealed why different choices may produce different LCA results.

## Detailed example 4: understanding the wider effect of changing a supplier

Suppose the broom model uses global PLA:

```yaml
inputs:
  - flow: Polylactide, granulate, at plant
    location: GLO
    database: bafu
    amount: 0.52
    unit: kg
```

Now imagine that the PLA dataset is corrected, replaced, or used in a
sensitivity scenario.

We can ask a reverse-search question:

> Which background processes directly consume the global PLA process with code
> `273090`?

Why we search:

The broom graph tells us that the broom consumes PLA. It does not tell us where
else that same PLA dataset is used. Reverse search follows the connection from
the supplier outward to all its direct consumers.

This kind of search can help us:

- find other products affected by a data correction;
- discover existing uses of the material that may guide our modeling;
- check whether typical use quantities resemble our assumption;
- identify highly connected datasets that need broader regression testing; and
- apply one material scenario consistently across several product studies.

The same search can be used for electricity, transport, chemicals, fuels,
waste treatment, and environmental flows.

## A practical search-first workflow

### Step 1: describe the product in simple terms

Write the functional unit and foreground processes without worrying about
perfect background names.

### Step 2: search for every background input

Ask what processes are available for each material, energy source, transport
service, and waste treatment need.

### Step 3: confirm identity and units

For every candidate, confirm the exact name, location, reference product, unit,
database, and code.

### Step 4: look for alternatives

Ask whether other regions, technologies, product forms, recycled-content
levels, or production methods are available.

### Step 5: inspect the recipes

Look inside the most plausible candidates. Ask what they consume, what they
release, and what stages they appear to include.

### Step 6: compare candidates in plain language

Ask the LCA MCP to summarize the important differences. Do not compare raw
amounts with different units as though they were environmental impact scores.

### Step 7: state the modeling decision

Update the graph with exact names and locations. Add a goal or note explaining
why the selected background process matches the study.

### Step 8: calculate with Brightway

Once the links are resolved, run the LCA. Brightway follows the complete supply
network, resolves loops and shared suppliers, and calculates the inventory and
impact scores.

### Step 9: use search again to investigate surprises

If an impact result is unexpectedly high or low, return to the selected
background recipes. Search for alternate datasets and use them to define
sensitivity scenarios.

## Questions we can ask the LCA MCP directly

The following prompts require no database language:

### Finding processes

- Search for processes related to recycled polyester.
- What cotton-fibre processes are available, and where are they located?
- Find Swiss and European freight-transport processes measured in
  tonne-kilometres.
- What processes produce low-voltage electricity?

### Checking a product graph

- Check whether every background input in this YAML exists.
- Are the locations and units in this product graph valid?
- Does any input name match more than one background process?
- Suggest the most plausible background candidates for each unresolved input,
  but do not choose between them without explaining the alternatives.

### Looking inside a process

- What are the direct inputs and environmental releases of this process?
- Does this yarn process include cotton fibre production?
- Which electricity grids does this material process use?
- Does this transport process include several vehicle technologies?

### Comparing alternatives

- Compare global PLA with Nebraska PLA in plain language.
- Compare the European and Swiss fleet-average lorry processes.
- Compare the primary and recycled content of the available aluminium mixes.
- Which candidate best matches a cast product, and why?

### Tracing connections

- Which processes directly consume this PLA process?
- Which processes use this electricity supplier?
- Which activities directly emit this carbon-dioxide flow?
- Where is this waste-treatment process used?

### Reviewing data quality

- Does this process have missing location or unit information?
- Does it have any direct environmental exchanges?
- Are any inputs negative, zero, formula-driven, or uncertain?
- Are there unusually large direct inputs that deserve review?

## What search can and cannot tell us

Search can tell us:

- what processes and environmental flows exist;
- how they are named and classified;
- where they are located;
- what units they use;
- what their direct recipes contain;
- how candidate recipes differ;
- which processes directly use a supplier; and
- where data may be missing or surprising.

Search alone cannot tell us:

- the complete upstream inventory of a product;
- the total impact of all connected suppliers;
- which input contributes the most climate impact;
- how circular supply relationships should be scaled;
- the final climate, acidification, toxicity, or other LCIA score; or
- which modeling choice is correct when the product specification is unknown.

Those questions require the calculation engine, an LCIA method, and sometimes
additional information from the modeler.

```text
Search helps us ask:       What data are we using, and what does it mean?

Brightway calculates:      What happens across the complete supply network?

LCIA methods interpret:    What environmental impacts are associated with the
                           resulting emissions and resource use?
```

## The main advantage

The main advantage is not simply that we can find process names faster.

The searchable database lets us challenge the assumptions hidden inside a
short product graph. It helps us see when several background choices are
available, when locations matter, when product forms differ, and when a process
name suggests a broader system boundary than its recipe actually contains.

That creates a better modeling sequence:

```text
describe the product
        |
        v
search the available background data
        |
        v
compare and explain the choices
        |
        v
correct the product graph
        |
        v
calculate with Brightway
        |
        v
interpret the result with clearer assumptions
```

The final LCA number is more useful because we understand what went into it.
