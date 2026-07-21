## About this analysis

This intentionally fictional example calculates one plastic broom using two
activities from the bundled `mock_background` database:

- 0.52 kg of mock polypropylene granulate
- 0.1055 ton-kilometers of mock small-truck freight

The polypropylene and freight activities both consume mock grid electricity,
so the calculation exercises a background supply chain rather than treating
the inputs as isolated emission factors. Use this example for teaching, UI
development, and deterministic integration tests—not environmental claims.

Using EF v3.1, the expected climate-change result is approximately
**0.948871 kg CO2-Eq**. This is the sum of the fictional direct and upstream
carbon-dioxide inventories; other nonzero EF results include acidification,
particulate matter, and photochemical ozone formation.
