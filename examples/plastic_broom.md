# Plastic Broom

The product graph is defined in [plastic_broom.yaml](plastic_broom.yaml).

## Foreground-only transport scenarios

These scenarios substitute the explicit 0.1055 tkm transport provider in the
foreground. They do not edit the BAfU database or the transport embedded inside
the PLA dataset.

- [plastic_broom_euro_vi.yaml](plastic_broom_euro_vi.yaml) uses an RER 32t
  diesel lorry, 2020, EURO VI, long haul.
- [plastic_broom_rail.yaml](plastic_broom_rail.yaml) models a complete modal
  shift of the explicit freight demand to RER rail.

## Scenario comparison

Production MCP results using EF v3.1:

| Scenario | Climate change (kg CO2-Eq) | Change | Acidification (mol H+-Eq) | Change |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 1.708973 | — | 0.00651655 | — |
| EURO VI 32t long haul | 1.701326 | -0.45% | 0.00647746 | -0.60% |
| Rail freight | 1.687383 | -1.26% | 0.00643834 | -1.20% |
| NatureWorks Nebraska PLA sensitivity | 1.452419 | -15.01% | 0.00572701 | -12.12% |

The EURO VI scenario is a truck-technology comparison. The rail scenario is a
modal-shift sensitivity case and is only appropriate when rail can provide the
same transport service. Run scenarios sequentially because the current engine
rebuilds a shared temporary `foreground` database for each calculation.

## PLA sensitivity scenario

[plastic_broom_natureworks_pla.yaml](plastic_broom_natureworks_pla.yaml)
substitutes the complete 0.52 kg PLA foreground input with `xxx Polylactide,
granulate, NatureWorks Nebraska` (US). All other inputs remain at baseline.

The candidate has the same main direct requirements as the baseline PLA, but
uses 1.9925 kWh of RER wind-farm electricity per kg rather than 1.828 kWh of
ENTSO-E low-voltage electricity. The production result also falls from
25.7364 to 19.6431 MJ for non-renewable energy (-23.67%) and from 16.4141 to
3.88010 m3 world-eq deprived for water use (-76.36%).

This is a complete activity substitution, so the score differences cannot be
attributed exclusively to electricity. The activity name begins with `xxx`,
which indicates that it may be legacy or inactive, and the BAfU metadata ties
it to a specific NatureWorks plant. Use it as a sensitivity result unless its
representativeness and status are independently validated.
