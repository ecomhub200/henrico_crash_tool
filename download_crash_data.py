#!/usr/bin/env python3
"""
Download crash data from Virginia Roads ArcGIS API.
Filters for Henrico County and excludes state routes.
"""

import logging
import os
import sys
import time
from datetime import datetime

import pandas as pd
import requests
import schedule

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# API Configuration
PRIMARY_API_URL = "https://services.arcgis.com/p5v98VHDX9Atv3l7/arcgis/rest/services/CrashData_test/FeatureServer/0/query"
FALLBACK_CSV_URL = "https://www.virginiaroads.org/api/download/v1/items/101101cecac34f28b38c0846e847bd0b/csv?layers=1"

# Henrico County FIPS code is 087, but in the data it appears as "43" for Juris Code
# and "043. Henrico County" for Physical Juris Name
HENRICO_FIPS = "087"
HENRICO_JURIS_CODE = "43"
HENRICO_NAME_PATTERNS = ["HENRICO", "043. Henrico County"]

# State route types to exclude (B=Business, S=State, IS=Interstate, US=US Route)
STATE_ROUTE_TYPES = ['B', 'S', 'IS', 'US']

# Pagination settings
RECORDS_PER_REQUEST = 2000

# Output configuration
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "crashes.csv")


def get_arcgis_record_count(where_clause: str) -> int:
    """Get total record count from ArcGIS API."""
    params = {
        'where': where_clause,
        'returnCountOnly': 'true',
        'f': 'json'
    }

    response = requests.get(PRIMARY_API_URL, params=params, timeout=60)
    response.raise_for_status()
    data = response.json()

    if 'error' in data:
        raise Exception(f"ArcGIS API error: {data['error']}")

    return data.get('count', 0)


def download_arcgis_page(where_clause: str, offset: int) -> list:
    """Download a page of records from ArcGIS API."""
    params = {
        'where': where_clause,
        'outFields': '*',
        'returnGeometry': 'true',
        'outSR': '4326',
        'resultOffset': offset,
        'resultRecordCount': RECORDS_PER_REQUEST,
        'f': 'json'
    }

    response = requests.get(PRIMARY_API_URL, params=params, timeout=120)
    response.raise_for_status()
    data = response.json()

    if 'error' in data:
        raise Exception(f"ArcGIS API error: {data['error']}")

    features = data.get('features', [])
    records = []
    for feature in features:
        record = feature.get('attributes', {})
        # Extract geometry coordinates
        if 'geometry' in feature and feature['geometry']:
            record['x'] = feature['geometry'].get('x')
            record['y'] = feature['geometry'].get('y')
        records.append(record)
    return records


def download_from_arcgis() -> pd.DataFrame:
    """
    Download crash data from ArcGIS REST API with pagination.
    Filters for Henrico County.
    """
    logger.info("Attempting download from ArcGIS REST API...")

    # Build WHERE clause for Henrico County
    # Try multiple filter approaches for robustness
    where_clauses = [
        "Juris_Code = '43' OR Juris_Code = 43",
        "Physical_Juris_Name LIKE '%HENRICO%' OR Physical_Juris_Name LIKE '%Henrico%'",
        "COUNTYFP = '087' OR FIPS = '087'"
    ]

    # Try each where clause until one works
    all_records = []

    for where_clause in where_clauses:
        try:
            count = get_arcgis_record_count(where_clause)
            if count > 0:
                logger.info(f"Found {count} records with filter: {where_clause}")
                break
        except Exception as e:
            logger.debug(f"Filter '{where_clause}' failed: {e}")
            continue
    else:
        # Fallback: get all records and filter locally
        logger.info("Specific filters failed, downloading all records for local filtering...")
        where_clause = "1=1"
        count = get_arcgis_record_count(where_clause)
        logger.info(f"Total records in dataset: {count}")

    # Download with pagination
    offset = 0
    while offset < count:
        logger.info(f"Downloading records {offset} to {min(offset + RECORDS_PER_REQUEST, count)}...")
        records = download_arcgis_page(where_clause, offset)

        if not records:
            break

        all_records.extend(records)
        offset += RECORDS_PER_REQUEST

    logger.info(f"Downloaded {len(all_records)} total records from ArcGIS API")

    if not all_records:
        raise Exception("No records returned from ArcGIS API")

    return pd.DataFrame(all_records)


def download_from_fallback() -> pd.DataFrame:
    """Download crash data from fallback CSV URL."""
    logger.info("Attempting download from fallback CSV URL...")

    response = requests.get(FALLBACK_CSV_URL, timeout=300)
    response.raise_for_status()

    # Save temporarily and read as CSV
    import io
    df = pd.read_csv(io.StringIO(response.text))

    logger.info(f"Downloaded {len(df)} records from fallback URL")
    return df


def filter_henrico_county(df: pd.DataFrame) -> pd.DataFrame:
    """Filter dataframe to only include Henrico County records."""
    original_count = len(df)

    # Try multiple filter approaches
    mask = pd.Series([False] * len(df))

    # Check various possible column names for jurisdiction
    juris_columns = ['Juris_Code', 'JURIS_CODE', 'juris_code', 'Juris Code']
    for col in juris_columns:
        if col in df.columns:
            mask |= df[col].astype(str).str.strip() == HENRICO_JURIS_CODE
            break

    # Check Physical Juris Name
    name_columns = ['Physical_Juris_Name', 'PHYSICAL_JURIS_NAME', 'Physical Juris Name', 'PHYSICAL_JURIS']
    for col in name_columns:
        if col in df.columns:
            for pattern in HENRICO_NAME_PATTERNS:
                mask |= df[col].astype(str).str.upper().str.contains(pattern.upper(), na=False)
            break

    # Check FIPS code
    fips_columns = ['COUNTYFP', 'FIPS', 'County_FIPS', 'countyfp']
    for col in fips_columns:
        if col in df.columns:
            mask |= df[col].astype(str).str.strip() == HENRICO_FIPS
            break

    df_filtered = df[mask].copy()

    logger.info(f"Filtered from {original_count} to {len(df_filtered)} Henrico County records")

    return df_filtered


def filter_exclude_state_routes(df: pd.DataFrame) -> pd.DataFrame:
    """
    Exclude state routes (Interstate, US, State, Business routes).
    Only keep local/county roads.
    """
    original_count = len(df)

    # Find the route name column
    route_columns = ['RTE_NM', 'RTE_NAME', 'RTE NAME', 'Rte_Name', 'Route_Name', 'ROUTE_NAME', 'RTE_Name', 'RTE Name']
    route_col = None
    for col in route_columns:
        if col in df.columns:
            route_col = col
            break

    if route_col is None:
        logger.warning("Could not find route name column, skipping state route filter")
        return df

    # Filter out state routes
    # Route patterns: R-VA (state primary), I- (Interstate), US (US route)
    # Keep: S-VA043 (secondary county roads)
    mask = pd.Series([True] * len(df))

    route_values = df[route_col].astype(str)

    # Exclude Interstate routes (I-64, I-95, etc.)
    mask &= ~route_values.str.contains(r'^I-|^R-VA\s*IS', case=False, na=False, regex=True)

    # Exclude US routes
    mask &= ~route_values.str.contains(r'^R-VA\s*US|US\d+', case=False, na=False, regex=True)

    # Exclude state routes (but keep secondary/county roads starting with S-)
    mask &= ~route_values.str.contains(r'^R-VA\s*SR|^R-VA\s*\d', case=False, na=False, regex=True)

    # Exclude business routes
    mask &= ~route_values.str.contains(r'^R-VA\s*B|BUSINESS', case=False, na=False, regex=True)

    df_filtered = df[mask].copy()

    logger.info(f"Filtered from {original_count} to {len(df_filtered)} records after excluding state routes")

    return df_filtered


def filter_nonvdot_system(df: pd.DataFrame) -> pd.DataFrame:
    """
    Filter dataframe to only include NonVDOT records in the SYSTEM column.
    """
    original_count = len(df)

    # Find the SYSTEM column
    system_columns = ['SYSTEM', 'System', 'system']
    system_col = None
    for col in system_columns:
        if col in df.columns:
            system_col = col
            break

    if system_col is None:
        logger.warning("Could not find SYSTEM column, skipping NonVDOT filter")
        return df

    # Filter to only keep NonVDOT records
    mask = df[system_col].astype(str).str.upper().str.contains('NONVDOT', na=False)
    df_filtered = df[mask].copy()

    logger.info(f"Filtered from {original_count} to {len(df_filtered)} NonVDOT records")

    return df_filtered


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize column names to match expected format for index.html."""
    # Comprehensive mapping from API column names to expected column names
    column_mapping = {
        # Core identifiers
        'OBJECTID': 'OBJECTID',
        'DOCUMENT_NBR': 'Document Nbr',
        'Document_Nbr': 'Document Nbr',

        # Crash timing
        'CRASH_YEAR': 'Crash Year',
        'Crash_Year': 'Crash Year',
        'CRASH_DT': 'Crash Date',
        'Crash_Date': 'Crash Date',
        'CRASH_MILITARY_TM': 'Crash Military Time',
        'Crash_Military_Time': 'Crash Military Time',

        # Severity
        'CRASH_SEVERITY': 'Crash Severity',
        'Crash_Severity': 'Crash Severity',
        'K_PEOPLE': 'K_People',
        'A_PEOPLE': 'A_People',
        'B_PEOPLE': 'B_People',
        'C_PEOPLE': 'C_People',

        # Injury counts
        'PERSONS_INJURED': 'Persons Injured',
        'Persons_Injured': 'Persons Injured',
        'PEDESTRIANS_KILLED': 'Pedestrians Killed',
        'Pedestrians_Killed': 'Pedestrians Killed',
        'PEDESTRIANS_INJURED': 'Pedestrians Injured',
        'Pedestrians_Injured': 'Pedestrians Injured',
        'VEH_COUNT': 'Vehicle Count',
        'Vehicle_Count': 'Vehicle Count',

        # Crash characteristics
        'COLLISION_TYPE': 'Collision Type',
        'Collision_Type': 'Collision Type',
        'WEATHER_CONDITION': 'Weather Condition',
        'Weather_Condition': 'Weather Condition',
        'LIGHT_CONDITION': 'Light Condition',
        'Light_Condition': 'Light Condition',
        'ROADWAY_SURFACE_COND': 'Roadway Surface Condition',
        'Roadway_Surface_Condition': 'Roadway Surface Condition',
        'RELATION_TO_ROADWAY': 'Relation To Roadway',
        'Relation_To_Roadway': 'Relation To Roadway',
        'ROADWAY_ALIGNMENT': 'Roadway Alignment',
        'Roadway_Alignment': 'Roadway Alignment',
        'ROADWAY_SURFACE_TYPE': 'Roadway Surface Type',
        'Roadway_Surface_Type': 'Roadway Surface Type',
        'ROADWAY_DEFECT': 'Roadway Defect',
        'Roadway_Defect': 'Roadway Defect',
        'ROADWAY_DESCRIPTION': 'Roadway Description',
        'Roadway_Description': 'Roadway Description',

        # Intersection/control
        'INTERSECTION_TYPE': 'Intersection Type',
        'Intersection_Type': 'Intersection Type',
        'TRAFFIC_CONTROL_TYPE': 'Traffic Control Type',
        'Traffic_Control_Type': 'Traffic Control Type',
        'TRFC_CTRL_STATUS_TYPE': 'Traffic Control Status',
        'Traffic_Control_Status': 'Traffic Control Status',

        # Work zone / school
        'WORK_ZONE_RELATED': 'Work Zone Related',
        'Work_Zone_Related': 'Work Zone Related',
        'WORK_ZONE_LOCATION': 'Work Zone Location',
        'Work_Zone_Location': 'Work Zone Location',
        'WORK_ZONE_TYPE': 'Work Zone Type',
        'Work_Zone_Type': 'Work Zone Type',
        'SCHOOL_ZONE': 'School Zone',
        'School_Zone': 'School Zone',

        # First harmful event
        'FIRST_HARMFUL_EVENT': 'First Harmful Event',
        'First_Harmful_Event': 'First Harmful Event',
        'FIRST_HARMFUL_EVENT_LOC': 'First Harmful Event Loc',
        'First_Harmful_Event_Loc': 'First Harmful Event Loc',

        # Jurisdiction
        'JURIS_CODE': 'Juris Code',
        'Juris_Code': 'Juris Code',
        'PHYSICAL_JURIS': 'Physical Juris Name',
        'Physical_Juris_Name': 'Physical Juris Name',

        # Road classification
        'FUN': 'Functional Class',
        'Functional_Class': 'Functional Class',
        'FAC': 'Facility Type',
        'Facility_Type': 'Facility Type',
        'AREA_TYPE': 'Area Type',
        'Area_Type': 'Area Type',
        'SYSTEM': 'SYSTEM',
        'VSP': 'VSP',
        'OWNERSHIP': 'Ownership',

        # Planning/admin
        'PLAN_DISTRICT': 'Planning District',
        'Planning_District': 'Planning District',
        'MPO_NAME': 'MPO Name',
        'MPO_Name': 'MPO Name',
        'VDOT_DISTRICT': 'VDOT District',
        'VDOT_District': 'VDOT District',

        # Route/location
        'RTE_NM': 'RTE Name',
        'RTE_NAME': 'RTE Name',
        'RTE_Name': 'RTE Name',
        'RNS_MP': 'RNS MP',
        'NODE': 'Node',
        'OFFSET': 'Node Offset (ft)',
        'Node_Offset': 'Node Offset (ft)',

        # Coordinates (keep lowercase)
        'x': 'x',
        'y': 'y',

        # Boolean flags
        'ALCOHOL_NOTALCOHOL': 'Alcohol?',
        'BIKE_NONBIKE': 'Bike?',
        'PED_NONPED': 'Pedestrian?',
        'SPEED_NOTSPEED': 'Speed?',
        'DISTRACTED_NOTDISTRACTED': 'Distracted?',
        'DROWSY_NOTDROWSY': 'Drowsy?',
        'HITRUN_NOT_HITRUN': 'Hitrun?',
        'SENIOR_NOTSENIOR': 'Senior?',
        'YOUNG_NOTYOUNG': 'Young?',
        'NIGHT': 'Night?',
        'BELTED_UNBELTED': 'Unrestrained?',
        'MOTOR_NONMOTOR': 'Motorcycle?',

        # Additional boolean flags
        'DRUG_NODRUG': 'Drug Related?',
        'GR_NOGR': 'Guardrail Related?',
        'LGTRUCK_NONLGTRUCK': 'Lgtruck?',
        'MAINLINE_YN': 'Mainline?',

        # Speed and road attributes
        'SPEED_DIFF_MAX': 'Max Speed Diff',
        'RD_TYPE': 'RoadDeparture Type',
    }

    # Rename columns that exist
    rename_dict = {k: v for k, v in column_mapping.items() if k in df.columns}
    df = df.rename(columns=rename_dict)

    return df


def main():
    """Main function to download and process crash data."""
    logger.info("=" * 60)
    logger.info(f"Starting crash data download at {datetime.now()}")
    logger.info("=" * 60)

    # Ensure output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    df = None

    # Try primary API first
    try:
        df = download_from_arcgis()
    except Exception as e:
        logger.error(f"Primary API failed: {e}")
        logger.info("Falling back to CSV download...")

    # Try fallback if primary failed
    if df is None or df.empty:
        try:
            df = download_from_fallback()
        except Exception as e:
            logger.error(f"Fallback download also failed: {e}")
            sys.exit(1)

    # Filter data
    logger.info("Applying filters...")
    df = filter_henrico_county(df)

    if df.empty:
        logger.error("No Henrico County records found after filtering!")
        sys.exit(1)

    df = filter_exclude_state_routes(df)

    if df.empty:
        logger.error("No records remaining after excluding state routes!")
        sys.exit(1)

    # Filter to only include NonVDOT system records
    df = filter_nonvdot_system(df)

    if df.empty:
        logger.error("No NonVDOT records found after filtering!")
        sys.exit(1)

    # Standardize column names
    df = standardize_columns(df)

    # Save to CSV
    logger.info(f"Saving {len(df)} records to {OUTPUT_FILE}")
    df.to_csv(OUTPUT_FILE, index=False)

    logger.info("=" * 60)
    logger.info(f"Successfully downloaded {len(df)} crash records")
    logger.info(f"Output saved to: {OUTPUT_FILE}")
    logger.info("=" * 60)

    return 0


if __name__ == "__main__":
    # Run once immediately on startup
    main()

    # Schedule to run every Monday at 6:00 AM
    schedule.every().monday.at("06:00").do(main)

    logger.info("Scheduler started. Will download crash data every Monday at 6:00 AM.")

    # Keep the script running
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute
