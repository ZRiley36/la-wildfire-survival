# LA Wildfire Survival: What Predicted Which Homes Burned?

In January 2025 the Palisades and Eaton fires destroyed more than 11,000 homes in Los Angeles. Every building inside
those perimeters was inspected afterward, so for once there's a clean answer key: we know which homes burned and
which ones didn't. I wanted to use that to ask an honest question. Of the things you could have measured *before*
the fires, which ones actually predicted destruction, and does a simple model built on them do better than CAL
FIRE's official Fire Hazard Severity Zones?

This is a validation project more than a mapping one. The point is to build the model without letting any
after-the-fact information leak in, and then test it against what really happened.

Work in progress. The data inventory is in `docs/data_inventory.md` and the full method and results are in
`docs/methodology.md`.

## What I've found so far

Inside the two perimeters, 70% of homes were destroyed in both fires, so "everything burned" is already 70%
accurate and accuracy is the wrong yardstick. On ranking which homes burned, the official map that was in effect in
January 2025 barely beats a coin flip (ROC AUC 0.54). In Palisades every home was in a Very High zone, and in Eaton
homes in the Very High zone were destroyed *less* often than homes outside any zone. A gradient-boosted model on
pre-fire features gets to 0.76 under spatial cross-validation and is well calibrated.

The honest caveat is transfer. Trained on one fire and tested on the other, the model drops to 0.70 and 0.60. What
holds up across both fires is how old the house is, how close it is to wildland, and how tightly packed the
neighborhood is. Homes with a neighbor within 2 m were destroyed about 80% of the time, against about 40% for homes
with nothing within 20 m. That matches IBHS's description of these fires as structure-to-structure conflagrations
([Monroy et al. 2025](https://doi.org/10.82346/KYXN-NS13)).

I also checked what happens if you let in the details the inspectors recorded after the fire, like roof, eaves and
vents. The model jumps to AUC 0.94, and it's meaningless. Inspectors mark eaves "Unknown" on 71% of destroyed homes
and 0.7% of survivors, because there's nothing left to look at, so those fields mostly encode the outcome.

## Method

One row per residential building that CAL FIRE inspected, joined to its 2023 footprint and its assessor parcel.
Features are things you could have known before the fire: terrain from the USGS DEM, fuels and distance to wildland
from LANDFIRE 2023, distance to and count of neighboring buildings, footprint size, and year built. Distance to the
fire perimeter is deliberately left out because the perimeter is drawn from the outcome. Models are logistic
regression and a small gradient-boosting model. Validation is spatial only: train on one fire and test on the other,
and 5-fold cross-validation over 500 m grid blocks. Random splits would let a model learn a house's outcome from its
next-door neighbor.

## Data

| Dataset | Source |
|---|---|
| Damage inspections (DINS) | [CAL FIRE Damage Inspection (DINS) Data](https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/POSTFIRE_MASTER_DATA_SHARE/FeatureServer/0), plus the [Palisades](https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/DINS_2025_Palisades_Public_View/FeatureServer/0) and [Eaton](https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/DINS_2025_Eaton_Public_View/FeatureServer/0) public views |
| Parcels with DINS | [LA County 2025 Parcels with DINS data](https://services.arcgis.com/RmCCgQtiZLDCtblq/ArcGIS/rest/services/2025_Parcels_with_DINS_data/FeatureServer) |
| Building footprints | [LA County Buildings_2023_with_DINS](https://services.arcgis.com/RmCCgQtiZLDCtblq/ArcGIS/rest/services/Buildings_2023_with_DINS/FeatureServer) (LARIAC) |
| Fire perimeters | [CAL FIRE FRAP 2025 fire perimeters](https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/2025_California_Fire_Perimeters_View/FeatureServer/0) |
| Fuels | [LANDFIRE 2023 FBFM40](https://landfire.gov/fuel/fbfm40) (40 Scott and Burgan fuel models, 30 m) |
| Elevation | [USGS 3DEP 1/3 arc-second DEM](https://www.usgs.gov/3d-elevation-program), tile n35w119 (2024-02-07) |
| Fire Hazard Severity Zones | [LA County FHSZ](https://services.arcgis.com/RmCCgQtiZLDCtblq/arcgis/rest/services/FHSZ_for_LACo/FeatureServer/0), [CAL FIRE SRA 2023](https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/FHSZSRA_23_3/FeatureServer/0), [CAL FIRE LRA 2025](https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/FHSALRA25_v1_All/FeatureServer/0), [City of LA VHFHSZ](https://services5.arcgis.com/7nsPwEMP38bSkCjy/arcgis/rest/services/Very_High_Fire_Hazard_Severity_Zones/FeatureServer/0) |
| Block groups | [Census 2024 cartographic boundary files](https://www.census.gov/geographies/mapping-files/time-series/geo/cartographic-boundary.html) |

## Setup
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/pip install -e .
source .venv/bin/activate
python -m wildfire.download                          # ~670 MB into data/raw/
python -m wildfire.inventory > docs/data_inventory.json
python -m wildfire                                   # the whole pipeline, about 1.5 minutes
python -m pytest
```

Or `make setup download pipeline test`. All tunable choices (CRS, buffers, feature list, model settings, fold size)
are in `config/config.yaml`.

## Limitations

These are two fires under extreme Santa Ana winds. What predicted destruction here may not carry over to a fire
under ordinary weather, and the cross-fire scores already show how much it varies between just these two.

The study only includes homes inside the perimeters, and the perimeter is drawn around what burned. That selection
inflates some effects, distance to wildland especially.

DINS records the damage CAL FIRE inspectors saw, not why a house survived. Footprints are mostly 2008 captures,
parcels can hold several buildings, and the official hazard map in effect was largely the 2007-2011 generation.

## Citation

Monroy et al. (2025). *The 2025 LA Conflagrations.* Insurance Institute for Business & Home Safety.
https://doi.org/10.82346/KYXN-NS13
