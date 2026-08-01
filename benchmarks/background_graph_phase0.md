# Phase 0 Background Graph Benchmark

Measured: 2026-07-28T03:37:09.248990+00:00

Re-run with:

```sh
uv run python scripts/benchmark_background_graphs.py
```

LCIA-only time is one complete current engine run with contribution graphs disabled (foreground setup, factorized LCI, every LCIA category, and core-result assembly). Per-category traversal time covers the existing Brightway traversal plus schema-3 graph adaptation. All-nonzero time is one complete engine run with independent traversal for every numerically nonzero category. Times are medians of the recorded samples.

Response sizes cover the core result without REST SVG strings and use compact UTF-8 JSON plus deterministic gzip level 9. Counts sum the current independent schema-3 category graphs; union nodes use the benchmark-only category-independent occurrence-path fingerprint.

| Example | LCIA only | All nonzero | Categories | Nodes | Edges | Flows | Union nodes | Raw | Gzip |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| cotton_fiber_bafu.yaml | 2.712 s | 31.387 s | 9 | 3,264 | 3,255 | 1,179 | 1,417 | 4.8 MB | 570.3 KB |
| plastic_broom.yaml | 2.757 s | 98.208 s | 25 | 7,854 | 7,829 | 2,641 | 2,342 | 12.0 MB | 1.4 MB |
| polyester_tshirt_bafu.yaml | 2.651 s | 32.831 s | 9 | 2,828 | 2,819 | 1,424 | 881 | 4.5 MB | 544.0 KB |
| wool_yarn_bafu.yaml | 2.556 s | 27.382 s | 9 | 2,385 | 2,376 | 913 | 1,228 | 3.6 MB | 446.5 KB |
| mock_plastic_broom.yaml | 0.171 s | 0.164 s | 5 | 30 | 25 | 20 | 6 | 61.9 KB | 5.5 KB |
| mock_plastic_broom_simple.yaml | 0.157 s | 0.165 s | 5 | 25 | 20 | 15 | 5 | 55.7 KB | 4.8 KB |
| mock_storage_bin.yaml | 0.155 s | 0.161 s | 5 | 20 | 15 | 10 | 4 | 43.4 KB | 3.9 KB |

## cotton_fiber_bafu.yaml

| Category | Traversal | Calculations | Nodes | Edges | Flows | Graph raw | Graph gzip |
|---|---:|---:|---:|---:|---:|---:|---:|
| acidification \| acidification potential (AP) | 1.552 s | 45 | 47 | 46 | 19 | 68.3 KB | 9.1 KB |
| ecotoxicity: freshwater \| ecotoxicity: freshwater | 4.003 s | 539 | 541 | 540 | 331 | 784.0 KB | 96.2 KB |
| eutrophication \| eutrophication potential | 3.732 s | 428 | 430 | 429 | 113 | 544.0 KB | 66.8 KB |
| climate change \| global warming potential (GWP100) | 1.625 s | 58 | 60 | 59 | 20 | 86.5 KB | 11.3 KB |
| human toxicity: carcinogenic \| human toxicity: carcinogenic | 4.500 s | 605 | 607 | 606 | 161 | 809.1 KB | 94.6 KB |
| human toxicity: non-carcinogenic \| human toxicity: non-carcinogenic | 4.337 s | 574 | 576 | 575 | 317 | 833.6 KB | 99.7 KB |
| photochemical oxidant formation \| maximum incremental reactivity (MIR) | 2.241 s | 122 | 124 | 123 | 30 | 176.8 KB | 23.0 KB |
| ozone depletion \| ozone depletion potential (ODP) | 4.786 s | 779 | 781 | 780 | 129 | 987.0 KB | 107.3 KB |
| particulate matter formation \| particulate matter formation potential (PMFP) | 2.050 s | 96 | 98 | 97 | 59 | 153.2 KB | 20.5 KB |

## plastic_broom.yaml

| Category | Traversal | Calculations | Nodes | Edges | Flows | Graph raw | Graph gzip |
|---|---:|---:|---:|---:|---:|---:|---:|
| material resources: metals/minerals \| abiotic depletion potential (ADP): elements (ultimate reserves) | 4.008 s | 354 | 356 | 355 | 96 | 483.1 KB | 58.9 KB |
| energy resources: non-renewable \| abiotic depletion potential (ADP): fossil fuels | 4.689 s | 569 | 571 | 570 | 62 | 742.0 KB | 83.6 KB |
| acidification \| accumulated exceedance (AE) | 3.473 s | 204 | 206 | 205 | 116 | 310.0 KB | 41.9 KB |
| eutrophication: terrestrial \| accumulated exceedance (AE) | 3.137 s | 170 | 172 | 171 | 73 | 263.1 KB | 34.2 KB |
| ecotoxicity: freshwater \| comparative toxic unit for ecosystems (CTUe) | 3.445 s | 162 | 164 | 163 | 71 | 247.2 KB | 33.7 KB |
| ecotoxicity: freshwater, inorganics \| comparative toxic unit for ecosystems (CTUe) | 4.335 s | 336 | 338 | 337 | 89 | 473.0 KB | 58.9 KB |
| ecotoxicity: freshwater, organics \| comparative toxic unit for ecosystems (CTUe) | 0.535 s | 15 | 17 | 16 | 23 | 31.9 KB | 4.7 KB |
| human toxicity: carcinogenic \| comparative toxic unit for human (CTUh) | 4.985 s | 438 | 440 | 439 | 210 | 631.8 KB | 75.5 KB |
| human toxicity: carcinogenic, inorganics \| comparative toxic unit for human (CTUh) | 5.201 s | 463 | 465 | 464 | 193 | 659.4 KB | 78.4 KB |
| human toxicity: carcinogenic, organics \| comparative toxic unit for human (CTUh) | 3.998 s | 302 | 304 | 303 | 105 | 418.1 KB | 47.5 KB |
| human toxicity: non-carcinogenic \| comparative toxic unit for human (CTUh) | 5.330 s | 379 | 381 | 380 | 249 | 596.5 KB | 77.7 KB |
| human toxicity: non-carcinogenic, inorganics \| comparative toxic unit for human (CTUh) | 5.523 s | 413 | 415 | 414 | 241 | 633.9 KB | 80.5 KB |
| human toxicity: non-carcinogenic, organics \| comparative toxic unit for human (CTUh) | 3.335 s | 199 | 201 | 200 | 83 | 296.3 KB | 37.6 KB |
| eutrophication: freshwater \| fraction of nutrients reaching freshwater end compartment (P) | 3.616 s | 315 | 317 | 316 | 90 | 431.7 KB | 50.9 KB |
| eutrophication: marine \| fraction of nutrients reaching marine end compartment (N) | 2.334 s | 85 | 87 | 86 | 42 | 134.8 KB | 18.1 KB |
| climate change \| global warming potential (GWP100) | 3.557 s | 236 | 238 | 237 | 94 | 354.0 KB | 45.7 KB |
| climate change: biogenic \| global warming potential (GWP100) | 2.939 s | 220 | 222 | 221 | 54 | 301.7 KB | 36.4 KB |
| climate change: fossil \| global warming potential (GWP100) | 3.548 s | 236 | 238 | 237 | 93 | 356.9 KB | 45.7 KB |
| climate change: land use and land use change \| global warming potential (GWP100) | 4.606 s | 796 | 798 | 797 | 156 | 1.0 MB | 113.5 KB |
| ionising radiation: human health \| human exposure efficiency relative to u235 | 3.052 s | 369 | 371 | 370 | 35 | 469.9 KB | 51.0 KB |
| particulate matter formation \| impact on human health | 3.841 s | 216 | 218 | 217 | 109 | 335.8 KB | 43.6 KB |
| ozone depletion \| ozone depletion potential (ODP) | 5.485 s | 567 | 569 | 568 | 72 | 729.7 KB | 82.8 KB |
| land use \| soil quality index | 2.284 s | 108 | 110 | 109 | 44 | 143.8 KB | 19.5 KB |
| photochemical oxidant formation: human health \| tropospheric ozone concentration increase | 4.226 s | 353 | 355 | 354 | 166 | 536.2 KB | 67.5 KB |
| water use \| user deprivation potential (deprivation-weighted water consumption) | 3.950 s | 299 | 301 | 300 | 75 | 413.7 KB | 49.9 KB |

## polyester_tshirt_bafu.yaml

| Category | Traversal | Calculations | Nodes | Edges | Flows | Graph raw | Graph gzip |
|---|---:|---:|---:|---:|---:|---:|---:|
| acidification \| acidification potential (AP) | 3.013 s | 205 | 207 | 206 | 133 | 314.7 KB | 40.8 KB |
| ecotoxicity: freshwater \| ecotoxicity: freshwater | 3.965 s | 391 | 393 | 392 | 374 | 634.1 KB | 80.1 KB |
| eutrophication \| eutrophication potential | 2.654 s | 252 | 254 | 253 | 114 | 345.5 KB | 43.7 KB |
| climate change \| global warming potential (GWP100) | 2.147 s | 155 | 157 | 156 | 58 | 226.9 KB | 27.7 KB |
| human toxicity: carcinogenic \| human toxicity: carcinogenic | 3.576 s | 358 | 360 | 359 | 148 | 510.8 KB | 61.4 KB |
| human toxicity: non-carcinogenic \| human toxicity: non-carcinogenic | 3.991 s | 423 | 425 | 424 | 255 | 633.2 KB | 76.2 KB |
| photochemical oxidant formation \| maximum incremental reactivity (MIR) | 3.575 s | 282 | 284 | 283 | 116 | 417.1 KB | 51.7 KB |
| ozone depletion \| ozone depletion potential (ODP) | 3.842 s | 446 | 448 | 447 | 46 | 565.6 KB | 61.5 KB |
| particulate matter formation \| particulate matter formation potential (PMFP) | 3.416 s | 298 | 300 | 299 | 180 | 460.5 KB | 56.4 KB |

## wool_yarn_bafu.yaml

| Category | Traversal | Calculations | Nodes | Edges | Flows | Graph raw | Graph gzip |
|---|---:|---:|---:|---:|---:|---:|---:|
| acidification \| acidification potential (AP) | 0.728 s | 15 | 17 | 16 | 12 | 26.6 KB | 3.8 KB |
| ecotoxicity: freshwater \| ecotoxicity: freshwater | 3.435 s | 334 | 336 | 335 | 212 | 493.6 KB | 63.9 KB |
| eutrophication \| eutrophication potential | 1.061 s | 35 | 37 | 36 | 38 | 61.2 KB | 8.9 KB |
| climate change \| global warming potential (GWP100) | 2.079 s | 74 | 76 | 75 | 35 | 113.9 KB | 15.9 KB |
| human toxicity: carcinogenic \| human toxicity: carcinogenic | 3.224 s | 241 | 243 | 242 | 77 | 337.7 KB | 43.7 KB |
| human toxicity: non-carcinogenic \| human toxicity: non-carcinogenic | 4.094 s | 435 | 437 | 436 | 239 | 636.2 KB | 80.5 KB |
| photochemical oxidant formation \| maximum incremental reactivity (MIR) | 3.318 s | 259 | 261 | 260 | 125 | 391.8 KB | 51.3 KB |
| ozone depletion \| ozone depletion potential (ODP) | 5.615 s | 923 | 925 | 924 | 131 | 1.1 MB | 130.1 KB |
| particulate matter formation \| particulate matter formation potential (PMFP) | 1.277 s | 51 | 53 | 52 | 44 | 89.2 KB | 12.2 KB |

## mock_plastic_broom.yaml

| Category | Traversal | Calculations | Nodes | Edges | Flows | Graph raw | Graph gzip |
|---|---:|---:|---:|---:|---:|---:|---:|
| acidification \| accumulated exceedance (AE) | 0.002 s | 4 | 6 | 5 | 4 | 8.7 KB | 1.5 KB |
| climate change \| global warming potential (GWP100) | 0.002 s | 4 | 6 | 5 | 4 | 9.0 KB | 1.5 KB |
| climate change: fossil \| global warming potential (GWP100) | 0.002 s | 4 | 6 | 5 | 4 | 9.0 KB | 1.5 KB |
| particulate matter formation \| impact on human health | 0.002 s | 4 | 6 | 5 | 4 | 9.1 KB | 1.5 KB |
| photochemical oxidant formation: human health \| tropospheric ozone concentration increase | 0.002 s | 4 | 6 | 5 | 4 | 9.1 KB | 1.5 KB |

## mock_plastic_broom_simple.yaml

| Category | Traversal | Calculations | Nodes | Edges | Flows | Graph raw | Graph gzip |
|---|---:|---:|---:|---:|---:|---:|---:|
| acidification \| accumulated exceedance (AE) | 0.002 s | 3 | 5 | 4 | 3 | 7.4 KB | 1.4 KB |
| climate change \| global warming potential (GWP100) | 0.002 s | 3 | 5 | 4 | 3 | 7.6 KB | 1.3 KB |
| climate change: fossil \| global warming potential (GWP100) | 0.002 s | 3 | 5 | 4 | 3 | 7.6 KB | 1.3 KB |
| particulate matter formation \| impact on human health | 0.002 s | 3 | 5 | 4 | 3 | 7.7 KB | 1.4 KB |
| photochemical oxidant formation: human health \| tropospheric ozone concentration increase | 0.002 s | 3 | 5 | 4 | 3 | 7.7 KB | 1.4 KB |

## mock_storage_bin.yaml

| Category | Traversal | Calculations | Nodes | Edges | Flows | Graph raw | Graph gzip |
|---|---:|---:|---:|---:|---:|---:|---:|
| acidification \| accumulated exceedance (AE) | 0.002 s | 2 | 4 | 3 | 2 | 5.5 KB | 1.1 KB |
| climate change \| global warming potential (GWP100) | 0.001 s | 2 | 4 | 3 | 2 | 5.6 KB | 1.1 KB |
| climate change: fossil \| global warming potential (GWP100) | 0.001 s | 2 | 4 | 3 | 2 | 5.6 KB | 1.1 KB |
| particulate matter formation \| impact on human health | 0.001 s | 2 | 4 | 3 | 2 | 5.7 KB | 1.1 KB |
| photochemical oxidant formation: human health \| tropospheric ozone concentration increase | 0.001 s | 2 | 4 | 3 | 2 | 5.7 KB | 1.1 KB |

## Synthetic serialization fixture

1,000 nodes, 999 edges, and 1,500 flows serialize to 1.1 MB raw and 94.9 KB gzipped.
