# Data Inventory (Step 1)

I generated this on 2026-10-28 with `src/wildfire/inventory.py`. The full machine-readable output is in
`docs/data_inventory.json`. `python -m wildfire.download` fetched every file, and each folder in `data/raw/` has a
`SOURCE.txt` with the URL, fetch time and exactly what was asked for. All 29 files come to about 670 MB.

Distances and areas in this document are measured in EPSG:3310 (California Albers, meters). 300 ft is 91.44 m.

## Files on disk

```
data/raw/
  dins_master/              CAL FIRE DINS master, both fires, every field          30,565 points
  dins_public_palisades/    CAL FIRE DINS 2025 Palisades public view (4 fields)     12,081 points
  dins_public_eaton/        CAL FIRE DINS 2025 Eaton public view (4 fields)         18,428 points
  parcels_dins/             LA County 2025 Parcels with DINS data                   24,462 parcels
  buildings_2023_dins/      LA County Buildings_2023_with_DINS                      45,433 footprints
  perimeters_calfire/       CAL FIRE FRAP 2025 perimeters, Palisades and Eaton      2 multipolygons
  perimeters_lacounty/      LA County "Palisades and Eaton" dissolved perimeter     1 multipolygon (Eaton only)
  fhsz_lacounty/            LA County Fire Hazard Severity Zones (CAL FIRE data)    165 polygons
  fhsz_sra_2023/            CAL FIRE FHSZ in SRA, adopted April 1, 2024             56 polygons
  fhsz_lra_2025/            CAL FIRE FHSZ in LRA, map dated March 24, 2025          252 polygons
  vhfhsz_la_city/           City of LA Very High FHSZ (2019)                        7 polygons
  landfire_fbfm40/          LF2023 FBFM40, one 30 m clip per fire                   2 GeoTIFFs
  usgs_3dep/                3DEP 1/3 arc-second DEM tile n35w119, 2024-02-07        1 GeoTIFF (458 MB)
  census/                   2024 cartographic block groups, California              1 zip
```

All vector layers were saved as GeoJSON, so they arrive in EPSG:4326 whatever their service CRS was (DINS master is
natively EPSG:6414, the LA County layers EPSG:2229 or 3857).

A note on how I got LANDFIRE. The documented LANDFIRE Product Service job API failed on its end ("Failure
determining region from outline map service"), so I pulled the same LF2023 FBFM40 product from LANDFIRE's own image
service instead. Each clip is the perimeter bounds plus 3 km, snapped to the native 30 m grid in EPSG:5070 with
nearest-neighbor, so no cell is resampled. That service also fails intermittently and labels its error messages as
`image/tiff`, so the downloader checks the TIFF header bytes and retries.

---

## 1. Fire perimeters

| Layer | Rows | Notes |
|---|---|---|
| CAL FIRE FRAP 2025 | 2 | PALISADES (LDF 00000738, alarm 2025-01-07, 23,449 acres) and EATON (LAC 00009087, alarm 2025-01-08, 14,056 acres). 16 and 22 parts. **Both geometries are invalid**, and after `make_valid` their areas match `GIS_ACRES` exactly |
| LA County "Palisades and Eaton Dissolved" | 1 | Despite the name, it only holds the Eaton heat perimeter (14,056 acres) |

I'll use the CAL FIRE FRAP perimeters for both fires.

## 2. CAL FIRE DINS (damage inspections)

The statewide master (`POSTFIRE_MASTER_DATA_SHARE`) has every field the inspectors recorded. Filtered to the two
fires, it has 30,565 points: 12,137 Palisades and 18,428 Eaton. No duplicate IDs or locations.

The public views carry only `DAMAGE` and `STRUCTURETYPE`. They hold the same records as the master but under
different GlobalIDs (zero overlap), and the Palisades view leaves out the 56 Inaccessible points. Their damage labels
are also worded slightly differently ("Affected (1-9%)" against "Affected (>0-10%)"). The master is the one to use.

**Damage class by fire, all structures:**

| DAMAGE | Eaton | Palisades | Total |
|---|---|---|---|
| Destroyed (>50%) | 9,419 | 6,845 | 16,264 |
| Major (25-50%) | 70 | 72 | 142 |
| Minor (10-25%) | 148 | 171 | 319 |
| Affected (>0-10%) | 858 | 732 | 1,590 |
| No Damage | 7,893 | 4,261 | 12,154 |
| Inaccessible | 40 | 56 | 96 |
| **Total** | 18,428 | 12,137 | 30,565 |

**Residential structures** (`STRUCTURECATEGORY` Single Residence, Multiple Residence, or Mixed
Commercial/Residential) are 22,152 of these. The rest are mostly "Other Minor Structure" (7,489, meaning sheds,
garages and other outbuildings), plus commercial and infrastructure.

| Residential | Eaton | Palisades |
|---|---|---|
| Destroyed | 6,116 (50.1%) | 5,566 (56.0%) |
| Major | 39 | 58 |
| Minor | 111 | 143 |
| Affected | 632 | 619 |
| No Damage | 5,290 | 3,497 |
| Inaccessible | 31 | 50 |
| Total | 12,219 | 9,933 |

Major is tiny in both fires (97 residential buildings), so it barely matters whether it counts as destroyed.

**Year built** comes from the assessor through DINS (`YEARBUILT`). It's present for 96.8% of all structures and
**98.3% of residential ones**. 987 are 0 (unknown). Valid years run from 1885 to 2022 with a median of 1949. Only
576 residential buildings were built after 2008, when California's Chapter 7A WUI building code took effect, so that
flag will be a small group.

**APN** is a 10-digit string with no dashes for every point except 12 nulls.

**Other fields.** `CITY` is mostly Altadena (14,821), Pacific Palisades (9,031), Pasadena (2,377) and Malibu
(2,199). `COMMUNITY` is blank for 94% of points, so it's not useful for grouping. `ASSESSEDIMPROVEDVALUE` is the
assessor's value.

### Inside the perimeter vs. just outside

DINS inspects structures inside the perimeter and within about 100 m of it, but plenty of points fall further out.
Each point is measured against its own fire's perimeter:

| | Inside | Outside, within 300 ft | Outside, beyond 300 ft | Farthest |
|---|---|---|---|---|
| Palisades | 9,551 | 2,095 | 491 | 289 m |
| Eaton | 13,081 | 3,626 | 1,721 | 624 m |

Residential destruction rates by band (Inaccessible excluded):

| Residential | Inside | 0-300 ft out | 300 ft-200 m out | >200 m out |
|---|---|---|---|---|
| Eaton | 70.4% of 8,560 | 3.1% of 2,502 | 0.6% of 835 | 2.7% of 291 |
| Palisades | 70.3% of 7,746 | 6.7% of 1,738 | 0.3% of 386 | 0% of 13 |

Two things follow from this. Inside the perimeters, **70% of homes were destroyed in both fires**, so the classes are
imbalanced toward destroyed. A model that says "destroyed" for everyone is 70% accurate, which is why I'll lean on
ROC AUC, PR AUC and Brier score rather than accuracy. And the 300 ft buffer adds almost only survivors, so the buffer
sensitivity run will mostly test whether a model can tell "inside" from "outside".

### Post-fire DINS fields (potential leakage)

Everything below was recorded by inspectors after the fire. None of it can go in the main model.

| Field | What it is | Filled | Recorded "Unknown": destroyed / not destroyed |
|---|---|---|---|
| `DAMAGE` | The outcome | 100% | |
| `ROOFCONSTRUCTION` | Roof material | 100% | 12.5% / 2.3% |
| `EAVES` | Eave type | 100% | **71.1% / 0.7%** |
| `VENTSCREEN` | Vent screen | 100% | **45.1% / 3.9%** |
| `EXTERIORSIDING` | Siding | 100% | 4.4% / 0.5% |
| `WINDOWPANE` | Window glazing | 100% | **45.1% / 1.0%** |
| `DECKPORCHONGRADE` | Deck on grade | 100% | 8.2% / 1.0% |
| `DECKPORCHELEVATED` | Elevated deck | 100% | 20.6% / 1.8% |
| `PATIOCOVERCARPORT` | Patio cover / carport | 100% | 24.8% / 1.5% |
| `FENCEATTACHEDTOSTRUCTURE` | Attached fence | 100% | 10.7% / 0.7% |
| `PROPANETANKDISTANCE` | Propane tank distance | 37% | |
| `UTILITYMISCSTRUCTUREDISTANCE` | Distance to outbuildings | 38% | |
| `NOOUTBUILDINGSDAMAGED`, `NOOUTBUILDINGSNOTDAMAGED` | Outbuildings damaged or not | 100% | an outcome of the same fire |
| `NOOFCARSONPROPERTY` | Cars on site at inspection | 100% | |
| `WHEREFIRESTARTEDONSTRUCTURE`, `WHATDIDFIRESTARTFROM` | Ignition point and mechanism | 5% | only filled for Affected and a few Minor |
| `DEFENSIVEACTIONS` | Firefighting on site | 37% | |

The "Unknown" column shows the problem. An inspector can't tell what kind of eaves a house had once it has burned to
the foundation, so "Unknown" is mostly a code for destroyed. Even the fields that look like honest building traits
would leak through that pattern. If I look at these at all, it'll be in a separate, clearly labeled section.

`YEARBUILT`, `APN` and `ASSESSEDIMPROVEDVALUE` come from the assessor roll, not the inspection, so they describe the
building before the fire and are fine to use.

## 3. LA County 2025 Parcels with DINS data

| | |
|---|---|
| Rows | 24,462 parcels (Palisades 12,387, Eaton 12,064, 11 without a fire name) |
| Geometry | 24,251 Polygon + 210 MultiPolygon, **6 invalid, 1 null** |
| IDs | `AIN_1` is 10 digits, `APN_1` is the same with dashes (`4420-030-015`). They agree on all 24,461 rows. No duplicates |
| DINS | `DAMAGE_1` is the most damaged structure on the parcel, `DINS_Count` how many points it has |

`DAMAGE_1` runs Destroyed 11,965, No Damage 8,374, "No Data/Vacant" 2,238, Affected 1,393, Minor 374 and Major 108.
`UseType` is 96% Residential. `UseCode` is the 4-character assessor code (`0100`, `0101`, `010V`) and `UseCode_2` its
first two digits (`01` single family is 22,728).

Each parcel can describe up to five buildings (`YearBuilt1`-`YearBuilt5`, with `EffectiveYear`, units and square
feet for each). 21,803 parcels have a first building, 690 a second, 106 a third, 48 a fourth and 23 a fifth.
`YearBuilt1` is missing for 2,607 parcels (vacant lots, mostly) and its median is 1953. The roll is 2024, so this is
all pre-fire.

There's no way in this layer to say which of a parcel's buildings is which footprint. That's the multi-building
parcel question (question 2 below).

`COMMUNITY` here is much better filled than in DINS (Altadena, Pacific Palisades, Palisades Highlands, Santa Monica
Mountains, Mandeville Canyon, Kinneloa Mesa), so it can serve as the neighborhood grouping alongside block groups.

## 4. LA County Buildings_2023_with_DINS

| | |
|---|---|
| Rows | 45,433 footprints within 1/4 mile of the perimeters |
| Geometry | 45,431 Polygon + 2 MultiPolygon, **24 invalid** |
| `CODE` | Building 45,068, Courtyard 289, Free Standing Solar Structure 76 |
| `SOURCE` / `DATE_` | LARIAC2 (2008) 27,832, Pasadena 7,655, LARIAC5 (2017), 6 (2020), 7 (2023), 4 (2014) |
| `STATUS` | Unchanged 42,812, Modified 2,000, New 600, Replacement 21 |
| `AREA` | Square feet (median 1,672) |
| `BLD_ID` | 288 duplicates |
| `DAMAGE` | Attached by the county from DINS as of 2025-01-27. 30,440 footprints have one |

The name says 2023, but **78% of footprints carry a 2008 date** and are marked "Unchanged". So most outlines are
older captures that were checked in 2023, not redrawn. A house rebuilt or added after its footprint's date may be
missing or out of date. I'll do my own DINS join rather than rely on the county's `DAMAGE` column.

## 5. Joins and expected match rates

| Join | Result |
|---|---|
| Residential DINS point inside a footprint | 21,222 of 22,152 (95.8%). None inside two |
| ...or within 2 / 5 / 10 / 20 m | 97.9% / 98.6% / 99.1% / 99.5% |
| Footprints holding more than one residential DINS point | 136 (condos and multi-unit buildings) |
| DINS APN found in parcel `AIN_1` | 99.73% of all points, 99.75% of residential |
| Parcels with more than one residential DINS point | 1,643, holding 4,204 points |

The APN formats line up once dashes are stripped: DINS uses 10 digits, parcels have both forms. The misses are the
12 null APNs and a handful of parcels that changed.

## 6. Fire Hazard Severity Zones, and which one was in effect

California has two kinds of zone maps. SRA maps cover land where the state is responsible for fire protection. LRA
maps cover cities and other locally protected land, which is where most of the burned homes were.

| Layer | Date | In effect in January 2025? | Coverage of each perimeter |
|---|---|---|---|
| `fhsz_lacounty`: LA County Fire Department's "Los Angeles County Fire Hazard Severity Zones", CAL FIRE data | Item created 2019-04-02, modified 2023-03-23. Schema is CAL FIRE's 2007 SRA / 2007-2011 LRA product (`FID_c19fhs`, county 19) | **Yes**, as far as I can tell. This is the generation of maps the 2025 LRA update replaced | Palisades 100% Very High. Eaton 87.3% Very High |
| `fhsz_sra_2023`: CAL FIRE FHSZ in SRA | Adopted, effective April 1, 2024 | **Yes**, but SRA only | Palisades 32.9%, Eaton 18.4%, all Very High |
| `fhsz_lra_2025`: CAL FIRE recommended LRA FHSZ | Map dated March 24, 2025 | **No**. Published two months after the fires | Palisades 66.2% Very High. Eaton 13.0% Very High, 1.8% High, 1.7% Moderate, 9.7% NonWildland |
| `vhfhsz_la_city`: City of LA VHFHSZ | Updated 2019-09-03 | Yes, City of LA only | Palisades 59.0%, Eaton 0% |

The LA County layer marks its zones `LRA` (72), `FRA` (50) and `SRA` (43), all classed Very High, High or Moderate.

The timing matters for two reasons. The 2025 LRA map came out after the fires, and I can't rule out that it was
informed by them, so comparing a model to it wouldn't be a fair pre-fire test. And the pre-fire map calls nearly all
of both burn areas Very High, so "in a Very High zone" is close to a constant inside the perimeters. That's an
honest finding in itself: the official map flagged the whole area as hazardous, but it can't rank buildings within
it.

## 7. LANDFIRE LF2023 FBFM40

| | Palisades | Eaton |
|---|---|---|
| CRS / resolution | EPSG:5070, 30 m | EPSG:5070, 30 m |
| Size | 787 × 572 | 634 × 496 |
| dtype / nodata | int16 / -9999 | int16 / -9999 |
| Covers the perimeter | yes | yes |
| Nodata cells | 7,241 (ocean) | 0 |
| Burnable cells (codes 101-204) | 51.6% | 63.5% |

Codes present are the non-burnable 91 (urban), 93 (agriculture), 98 (water) and 99 (barren), plus the burnable
grass (101-103), grass-shrub (121-123), shrub (141-147), timber-understory (161-165) and timber litter (181-189)
models, and one cell of 201.

LF2023 represents landscape conditions as of 2023, before the fires. I deliberately didn't use LF2025, which takes in
2025 disturbances and could already show these burns.

## 8. USGS 3DEP DEM

| | |
|---|---|
| Tile | n35w119 (34-35 N, 118-119 W), version published 2024-02-07 |
| CRS | EPSG:4269 (NAD83 geographic) |
| Resolution | 1/3 arc-second, about 8.6 m E-W by 10.3 m N-S here |
| Size / dtype / nodata | 10,812 × 10,812, float32, -999999 |
| Covers both perimeters | yes, with no nodata cells over the fires |
| Elevation over the fires | -0.3 to 1,750 m |

I picked the last version published before the fires (later versions are dated May 2025 onward).

## 9. Census block groups

2024 cartographic boundary block groups for California: 25,586, of which 6,587 are in LA County. EPSG:4269. These
are for the aggregates.

---

## Problems flagged

| # | Issue | Severity | Proposed handling |
|---|---|---|---|
| 1 | Post-fire DINS construction fields, with "Unknown" acting as a stand-in for destroyed | **High** | Out of the main model. Separate labeled section only |
| 2 | **Distance to the fire perimeter isn't a pre-fire feature.** The perimeter is drawn from where the fire went | **High** | Question 4 below |
| 3 | The pre-fire hazard map is Very High across almost the whole burn area | High | Report it as a finding. Question 3 below |
| 4 | The 2025 LRA map postdates the fires | High | Don't use it as the main baseline |
| 5 | 70% of homes inside the perimeters were destroyed | Medium | AUC, PR AUC and Brier, not accuracy |
| 6 | 2,212 DINS points sit more than 300 ft outside their perimeter | Medium | Inside-only population for the main model. The buffer run adds the 0-300 ft band |
| 7 | 78% of footprints date from 2008 | Medium | Use them, flag the date, check the unmatched DINS points |
| 8 | Multi-building parcels: 1,643 parcels have 2+ residential DINS points | Medium | Question 2 below |
| 9 | Invalid geometries: both perimeters, 24 footprints, 6 parcels, 9 / 3 / 8 zone polygons | Low | `make_valid` |
| 10 | LA County "Palisades and Eaton" perimeter holds Eaton only | Low | Use CAL FIRE FRAP |
| 11 | DINS public views drop the Palisades Inaccessible points and use different IDs | Low | Use the master |
| 12 | `YEARBUILT` = 0 for 987 points | Low | Treat as missing, fall back to the parcel's `YearBuilt1` |
| 13 | DINS `COMMUNITY` is 94% blank | Low | Use parcel `COMMUNITY` and block groups |
| 14 | LANDFIRE's job API failed and the image service is flaky | Low | Image-service export with retries and a TIFF check |
