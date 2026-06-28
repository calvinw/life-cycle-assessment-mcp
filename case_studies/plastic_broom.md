---
name: Plastic Broom — 1 unit
goal: >
  Calculate the climate change and acidification impact of producing one plastic
  broom made from 0.52 kg PLA and 0.03 kg nylon 6, including transport of
  materials to the assembly site.

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
      - { flow: "Polylactide, granulate, at plant",                               location: GLO, database: bafu, amount: 0.52,   unit: kg }
      - { flow: "Nylon 6, at plant",                                             location: RER, database: bafu, amount: 0.03,   unit: kg }
      - { flow: "Transport, freight, lorry, 16t-32t gross weight, fleet average", location: RER, database: bafu, amount: 0.1055, unit: tkm }

reference_process: "Plastic broom assembly"

lcia:
  method_name: "EF v3.1"
---
