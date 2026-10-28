# LA Wildfire Survival: What Predicted Which Homes Burned?

In January 2025 the Palisades and Eaton fires destroyed more than 11,000 homes in Los Angeles. Every building inside
those perimeters was inspected afterward, so for once there's a clean answer key: we know which homes burned and
which ones didn't. I wanted to use that to ask an honest question. Of the things you could have measured *before*
the fires, which ones actually predicted destruction, and does a simple model built on them do better than CAL
FIRE's official Fire Hazard Severity Zones?

This is a validation project more than a mapping one. The point is to build the model without letting any
after-the-fact information leak in, and then test it against what really happened.

Work in progress. The data inventory is in `docs/data_inventory.md`.

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
```
