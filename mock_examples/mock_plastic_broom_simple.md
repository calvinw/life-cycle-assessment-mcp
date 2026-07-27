## About this analysis

This intentionally fictional example calculates one simple plastic broom using
two activities from the bundled `mock_background` database:

- 0.52 kg of mock polypropylene granulate; and
- 0.1055 ton-kilometers of direct-emissions-only mock small-truck freight.

Only polypropylene consumes mock grid electricity. The freight activity is a
leaf process with direct emissions but no technosphere inputs, giving the
contribution graph one branch that continues upstream and one that terminates.
Use this example for teaching, UI development, and deterministic integration
tests—not environmental claims.

Using EF v3.1, the expected climate-change result is approximately
**0.945495 kg CO2-Eq**.
