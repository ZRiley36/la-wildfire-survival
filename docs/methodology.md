# Methodology (Step 2)

This covers everything from the raw files to validated models and grouped destruction rates. `make pipeline` (or
`python -m wildfire`) reruns all of it in about a minute and a half. Every number here comes from that run's log
and from `data/processed/model_metrics.json`. The data itself is described in `data_inventory.md`.

| Step | Module | Output | What it does |
|---|---|---|---|
| 1 | `ingest.py` | `01_*.parquet` | Reproject to EPSG:3310, repair geometry, clip to 1 km around both perimeters |
| 2 | `clean.py` | `02_*.parquet` | Residential DINS, outcome labels, APNs, year built, hazard-zone classes |
| 3 | `join.py` | `03_buildings` | DINS to footprints and parcels, perimeter bands |
| 4 | `features.py` + `raster.py` | `04_features` | Terrain, fuels, wildland distance, neighbors, age, zones |
| 5 | `evaluate.py` + `model.py` | `model_metrics.json`, `05_predictions` | Spatial validation, baselines, importance, sensitivities |
| 6 | `analyze.py` | `aggregates/*.csv` | Destruction rates by group |
| | `spotcheck.py` | log only | Re-derives buildings straight from the raw files |

Choices that a new hazard or city would change are in `config/config.yaml`, not in the code. `ingest.read_vector()`
and everything in `raster.py` know nothing about fires.

## Decisions

**Projection: EPSG:3310, California Albers, in meters.** The feature buffers (10, 30, 50, 100, 300 m) and LANDFIRE's
30 m cells are all metric. It's equal-area, so "share of a buffer that's burnable" is a true area share. And it covers
the whole state, so the same code would work for any California fire. CA State Plane V (EPSG:2229) would also have
worked for these two fires, but it's in feet and stops at the zone edge.

**Population: residential buildings inside their fire's perimeter.** That means DINS Single Residence, Multiple
Residence and Mixed Commercial/Residential points. The 81 Inaccessible ones are dropped, which leaves **16,306
buildings**: 8,560 in Eaton and 7,746 in Palisades. A sensitivity run adds the band up to 300 ft outside the
perimeter, for 20,546.

**Outcome: Destroyed (>50%).** The full ordinal class is kept too (`damage_ordinal`). Major+Destroyed runs as a
sensitivity, but Major is so small (97 buildings) that it changes nothing.

**One row per DINS building, including on multi-building parcels.** 4,335 buildings (19.6%) are on a parcel with
more than one building. Each keeps its own row, its own year built from DINS, and a `multi_building_parcel` flag.

**Hazard-zone baseline: the map in effect in January 2025.** That's CAL FIRE's 2023 SRA map (effective April 1,
2024) where it applies, and the LA County Fire Department's CAL FIRE map everywhere else. The March 2025 LRA map is
reported alongside it but labeled as published after the fires.

**Distance to the perimeter is not a feature.** The perimeter is drawn around where the fire went, so a building's
distance from it encodes the outcome. It's kept as `perimeter_dist_m` for describing results only.

**Wildland proximity is distance to the nearest contiguous burnable fuel patch** of at least 10 ha in LANDFIRE
2023. That's the pre-fire version of "how close is this house to the wildland".

## Building table

| Join | Result |
|---|---|
| DINS point inside a 2023 footprint | 21,222 of 22,152 (95.8%) |
| Nearest footprint within 5 m | 628 (2.8%) |
| No footprint | 302 (1.4%). Features use the DINS point instead |
| Parcel by APN | 22,096 (99.7%) |
| Parcel by point-in-polygon (APN missing or unmatched) | 33 |
| No parcel | 23 |
| Year built from DINS | 98.3% |
| Year built from the parcel's first building | 0.7% |
| Year built missing | 1.0% |

Where both DINS and the parcel have a year built, they agree exactly 99.1% of the time. 189 footprints hold more
than one DINS point (390 buildings, mostly condos and duplexes). Those buildings share their footprint features.

## Features

Everything here describes the building and its surroundings before January 7, 2025.

| Feature | How | Main population |
|---|---|---|
| `elevation_m` | 3DEP 1/3 arc-second DEM, cell under the building, native EPSG:4269 | 2 to 1,708 m |
| `slope_deg`, `aspect_sin`, `aspect_cos` | DEM warped to 10 m in EPSG:3310 (bilinear), Horn's 3x3 method. Aspect as sine (east) and cosine (north) | median slope 3.7° |
| `fuel_burnable_at_building` | LF2023 FBFM40 cell under the building is burnable (codes 101-204) | 5.2% |
| `burnable_share_30m/100m/300m` | Share of a circle that's burnable. 30 m cells split 6x6 so partial cells count | |
| `dist_wildland_m` | Distance from the footprint to the nearest burnable patch of 10 ha or more | median 323 m, 6.8% touching |
| `dist_nearest_building_m` | Footprint edge to the nearest other 2023 building outline, garages and sheds included | median 2.5 m |
| `n_buildings_10m/30m/50m` | Other building outlines within each distance | medians 2, 8, 17 |
| `footprint_area_m2` | | median 157 m² |
| `year_built`, `built_after_2008` | Assessor year, and a flag for California's Chapter 7A WUI code | 605 built after 2008 |

The only raster that gets warped is the DEM, because slope needs a grid in meters. LANDFIRE is read in its native
EPSG:5070 grid and the DEM elevation in its native grid. Buildings are transformed to each raster's CRS to sample it.

The terrain helpers have unit tests. One caught a sign error in my aspect formula before any results were computed,
which would have flipped every slope's direction.

## Validation

### Why there are no random splits

Neighbors share outcomes. Whole blocks either burned or didn't, often because one house ignited the next. If a
random split puts a house in the test set and its next-door neighbor in training, the model gets graded on a
near-copy of something it already saw, and the score comes out higher than it deserves. So every split here keeps
whole areas apart:

**Cross-fire.** Train on Eaton and test on Palisades, then the reverse. This is the hardest and most honest test. It
asks whether what predicted destruction in one fire carries over to a different one.

**Block CV.** The study area is cut into 500 m grid cells (284 of them hold buildings), and whole cells are dealt into
5 folds of about 3,260 buildings each. A cell is never on both sides of a split, and a test checks that.

Logistic regression and boosting are scikit-learn `Pipeline`s, so the imputer and scaler are fit inside each
training fold and never see the test fold. The hazard-zone baseline is fit the same way: it predicts each zone's destruction rate *in the
training fold*. The seed is fixed (20250107) and the whole run reproduces exactly.

### Metrics

70% of buildings in the main population were destroyed, in both fires. Predicting "destroyed" for everyone would be
70% accurate, so accuracy is useless here. Instead:

- **ROC AUC:** how well the scores rank destroyed homes above survivors. 0.5 is no better than random.
- **PR AUC:** the same idea, focused on the destroyed class. The floor is the base rate, about 0.70.
- **Brier score:** mean squared error of the probabilities. Predicting the base rate for everyone scores 0.209.

For block CV I report the mean across folds. A model that predicts a constant per fold gets different constants in
different folds, and pooling them invents a ranking that isn't there (the constant model scores 0.46 pooled).

### Results

| Model | Block CV ROC AUC | PR AUC | Brier | Eaton → Palisades AUC | Palisades → Eaton AUC |
|---|---|---|---|---|---|
| Constant (base rate) | 0.500 | 0.704 | 0.209 | 0.500 | 0.500 |
| Hazard zone in effect, Jan 2025 | 0.539 | 0.723 | 0.209 | 0.500 | 0.500 |
| 2025 LRA hazard zone (post-fire) | 0.518 | 0.714 | 0.210 | 0.468 | 0.437 |
| Logistic regression | 0.679 | 0.813 | 0.190 | 0.476 | 0.591 |
| **Gradient boosting** | **0.758** | **0.873** | **0.171** | **0.700** | **0.601** |

The AUC gap between gradient boosting and the in-effect hazard zone is 0.20 to 0.32 (95% interval from 500
bootstrap resamples of whole 500 m blocks). Boosting beats logistic regression by 0.05 to 0.11.

Within block CV, boosting does better in Palisades (AUC 0.81) than in Eaton (0.71). Its calibration is good: in
every tenth of predictions the observed destruction rate is within 0.03 of the predicted one.

The hazard zone carries almost no information inside the burn areas. In Palisades every building is in a Very High
zone. In Eaton the zone points the wrong way: 57.6% of buildings in a Very High zone were destroyed, against 74.3%
of buildings outside any zone. Across fires it can only predict a constant (AUC exactly 0.5). The 2025 LRA map does
no better.

### Cross-fire transfer and the elevation problem

Training on one fire and testing on the other costs a lot. Boosting drops from 0.76 to 0.70 (Eaton → Palisades) and
0.60 (Palisades → Eaton). Logistic regression trained on Eaton does worse than a coin flip on Palisades, with a Brier
score of 0.653, three times worse than predicting the base rate.

That turned out to be elevation. In Eaton, homes higher up toward the foothills burned more, so logistic regression
learned a strong positive slope. Palisades homes range from sea level to 684 m, far outside Eaton's 291 to 554 m, so
the model extrapolated and gave 71% of Palisades homes under a 5% chance of destruction. Within one fire, absolute
elevation is mostly a stand-in for *where in that fire* a home sits. That's real information, but it doesn't
transfer. Without elevation:

| | Block CV AUC | Eaton → Palisades | Palisades → Eaton |
|---|---|---|---|
| Boosting, with elevation | 0.758 | 0.700 | 0.601 |
| Boosting, without | 0.715 | 0.703 | 0.596 |
| Logistic, with elevation | 0.679 | 0.476 (Brier 0.653) | 0.591 |
| Logistic, without | 0.671 | 0.685 (Brier 0.207) | 0.603 |

Boosting doesn't extrapolate past the training range, so elevation can't hurt it much across fires. But it does
inflate its within-fire score. The main model keeps elevation as specified, and both versions are reported.

### What drives the predictions

Permutation importance for gradient boosting, as the drop in test-fold ROC AUC when a feature is shuffled:

| Feature | Block CV | Cross-fire |
|---|---|---|
| `elevation_m` | 0.084 | 0.022 |
| `dist_wildland_m` | 0.037 | 0.036 |
| `year_built` | 0.033 | 0.049 |
| `n_buildings_50m` | 0.021 | 0.010 |
| `dist_nearest_building_m` | 0.020 | 0.014 |
| `burnable_share_300m` | 0.007 | 0.044 |
| everything else | under 0.005 | under 0.007 |

Year built, distance to wildland, and how tightly packed the buildings are hold up in both kinds of test. Elevation
mostly matters within a fire. Partial-dependence curves for the top features are in `model_metrics.json` and become
figures in Step 3.

Several of these effects run the opposite way from the usual wildland-urban-interface story. Homes *farther* from
wildland, with *less* burnable fuel around them and on *flatter* ground, were destroyed more often. Close neighbors
mattered too: in both fires, homes with a neighbor within 2 m were destroyed 79-86% of the time, against about 40%
for homes with no building within 20 m. That fits IBHS's account of these fires, where wind-driven fire spread from
structure to structure through dense neighborhoods once it got in ([Monroy et al. 2025](https://doi.org/10.82346/KYXN-NS13)).

**One caution about wildland distance.** Part of its effect is selection. The study only includes homes inside the
perimeter, and the perimeter is drawn around what burned. Homes deep in the interior are only inside the perimeter
because the fire got to them. So "far from wildland, more likely destroyed" partly means "deep enough inside the
burn area to be in this study". The cross-fire tests reduce this problem but can't remove it.

### Sensitivities

| Variant | Boosting AUC | Hazard zone AUC |
|---|---|---|
| Main (Destroyed, inside perimeters) | 0.758 | 0.539 |
| Major + Destroyed | 0.756 | 0.539 |
| Adding the 300 ft band outside (20,546 buildings, 56.8% destroyed) | 0.791 | 0.530 |
| Without elevation | 0.715 | 0.539 |

The buffer run scores higher only because it adds an easy group. Homes just outside the perimeter were almost all
spared, and the model can tell they're on the edge.

### Leakage demo (not part of the main model)

To show why the post-fire DINS fields are kept out, I trained the same boosting model with them, under the same
block CV:

| Features | ROC AUC (pooled out-of-fold) |
|---|---|
| Pre-fire only (the main model) | 0.761 |
| Post-fire inspection fields only | 0.942 |
| Pre-fire plus post-fire | 0.956 |
| Logistic on just the "Unknown" flags | 0.895 |

A model using those fields looks spectacular, and it would be meaningless. The "Unknown" flags alone get to 0.895.
They don't describe the house at all. They describe whether there was enough of it left to inspect.

## Aggregates

`data/processed/aggregates/` has destruction rates by community, block group, hazard zone (both maps), build era and
neighbor distance, each split by fire. A few highlights:

| Group | Eaton | Palisades |
|---|---|---|
| Altadena / Pacific Palisades | 73.4% of 8,051 | 79.9% of 5,113 |
| Palisades Highlands | | 30.2% of 692 |
| Built before 1940 | 74.5% | 88.6% |
| Built 1980-1999 | 38.9% | 43.4% |
| Built 2009 or later | 48.8% of 43 | 74.0% of 408 |
| Nearest building within 2 m | 78.6% | 86.2% |
| Nearest building over 20 m | 39.0% | 43.9% |

Block groups with at least 30 buildings range from 0% to 96% destroyed (median 65%).

The newest homes don't follow the age trend in Palisades, where 74% of homes built after 2008 were destroyed. I
wouldn't read that as the Chapter 7A code failing, at least not from this table. 91% of those new homes are in the
Pacific Palisades community (against 74% of older ones), which was the hardest hit, and within that community new
and old homes burned at about the same rate (81.5% against 79.7%). Under winds like these, a newer house surrounded
by older burning ones may not have had much chance either way. The model weighs year built alongside location, which
is the fairer test.

## Checks

`spotcheck.py` re-derives six buildings from the raw files: destroyed and surviving homes in each fire, one matched
to its footprint by the 5 m fallback, and one on a multi-building parcel. It checks the outcome against the raw DINS
record, elevation against the raw DEM, fuel against the raw LANDFIRE clip, hazard zone against the raw zone layers,
and nearest-building distance by brute force against the raw footprints. All six agree, including one whose DINS
year built was 0 and which correctly took 1935 from its parcel.

`pytest` (26 tests) covers APN normalization, the point-to-footprint join (inside, snapping, too far, shared walls),
neighbor distance and counts on a toy row of squares, slope and aspect on known planes, buffer shares, wildland
patch filtering, and the spatial folds: no block appears on both sides of a split, folds are reproducible, and the
cross-fire splits are disjoint.
