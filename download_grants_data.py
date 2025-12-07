#!/usr/bin/env python3
"""
Download traffic safety grants from Grants.gov.
Filters for transportation category and safety-related keywords.
"""

import io
import logging
import os
import re
import sys
import zipfile
from datetime import datetime, timedelta

import pandas as pd
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Grants.gov extract URL template
GRANTS_URL_TEMPLATE = "https://prod-grants-gov-chatbot.s3.amazonaws.com/extracts/GrantsDBExtract{date}v2.zip"

# Traffic safety related keywords (case-insensitive)
SAFETY_KEYWORDS = [
    'traffic safety',
    'highway safety',
    'pedestrian safety',
    'nhtsa',
    'fhwa',
    'hsip',
    'crash reduction',
    'vision zero',
    'safe routes to school',
    'drunk driving',
    'intersection safety',
    'traffic calming',
    'complete streets',
    'road safety',
    'vehicle safety',
    'bicycle safety',
    'distracted driving',
    'impaired driving',
    'speed management',
    'roadway safety',
    'traffic fatality',
    'traffic incident',
]

# Transportation category code
TRANSPORTATION_CATEGORY = 'T'

# Output configuration
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "grants.csv")

# Number of days to look back for extracts if today's isn't available
MAX_LOOKBACK_DAYS = 7


def get_grants_url(target_date: datetime) -> str:
    """Generate the Grants.gov extract URL for a specific date."""
    date_str = target_date.strftime('%Y%m%d')
    return GRANTS_URL_TEMPLATE.format(date=date_str)


def download_grants_extract(max_attempts: int = MAX_LOOKBACK_DAYS) -> pd.DataFrame:
    """
    Download and extract Grants.gov data.
    Tries today's extract first, then looks back up to max_attempts days.
    """
    target_date = datetime.now()

    for attempt in range(max_attempts):
        url = get_grants_url(target_date)
        logger.info(f"Attempting to download: {url}")

        try:
            response = requests.get(url, timeout=300)

            if response.status_code == 200:
                logger.info(f"Successfully downloaded extract for {target_date.strftime('%Y-%m-%d')}")

                # Extract ZIP file
                with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
                    # Find the opportunities XML or CSV file
                    file_list = zf.namelist()
                    logger.info(f"Files in archive: {file_list}")

                    # Look for opportunities data file
                    opportunities_file = None
                    for filename in file_list:
                        if 'opportunit' in filename.lower():
                            opportunities_file = filename
                            break

                    if opportunities_file is None:
                        # Try to find any CSV or XML file
                        for filename in file_list:
                            if filename.endswith('.csv') or filename.endswith('.xml'):
                                opportunities_file = filename
                                break

                    if opportunities_file is None and file_list:
                        opportunities_file = file_list[0]

                    if opportunities_file:
                        logger.info(f"Reading file: {opportunities_file}")

                        with zf.open(opportunities_file) as f:
                            content = f.read()

                            # Try to parse as CSV first
                            try:
                                df = pd.read_csv(io.BytesIO(content), low_memory=False)
                                logger.info(f"Parsed {len(df)} records from CSV")
                                return df
                            except Exception:
                                pass

                            # Try to parse as XML
                            try:
                                df = pd.read_xml(io.BytesIO(content))
                                logger.info(f"Parsed {len(df)} records from XML")
                                return df
                            except Exception:
                                pass

                            # Try pipe-delimited
                            try:
                                df = pd.read_csv(io.BytesIO(content), delimiter='|', low_memory=False)
                                logger.info(f"Parsed {len(df)} records from pipe-delimited file")
                                return df
                            except Exception as e:
                                logger.error(f"Failed to parse {opportunities_file}: {e}")

            elif response.status_code == 404:
                logger.info(f"Extract not found for {target_date.strftime('%Y-%m-%d')}, trying previous day...")
            else:
                logger.warning(f"HTTP {response.status_code} for {url}")

        except requests.exceptions.Timeout:
            logger.warning(f"Timeout downloading {url}")
        except Exception as e:
            logger.error(f"Error downloading {url}: {e}")

        # Try previous day
        target_date -= timedelta(days=1)

    raise Exception(f"Could not download grants extract after {max_attempts} attempts")


def filter_transportation_category(df: pd.DataFrame) -> pd.DataFrame:
    """Filter for Transportation category grants."""
    # Find category column
    category_columns = [
        'CategoryOfFunding', 'Category', 'category_of_funding',
        'CategoryFunding', 'FundingCategory', 'OpportunityCategory',
        'CATEGORY_OF_FUNDING', 'CFDA_Category'
    ]

    category_col = None
    for col in category_columns:
        if col in df.columns:
            category_col = col
            break

    if category_col:
        mask = df[category_col].astype(str).str.upper().str.contains('T|TRANSPORTATION', na=False, regex=True)
        logger.info(f"Found {mask.sum()} grants in Transportation category")
        return mask
    else:
        logger.warning("Could not find category column, category filter will not be applied")
        return pd.Series([False] * len(df))


def filter_safety_keywords(df: pd.DataFrame) -> pd.DataFrame:
    """Filter for traffic safety related keywords in title and description."""
    # Build regex pattern for keywords
    keyword_pattern = '|'.join([re.escape(kw) for kw in SAFETY_KEYWORDS])

    mask = pd.Series([False] * len(df))

    # Check title columns
    title_columns = [
        'OpportunityTitle', 'Title', 'opportunity_title',
        'OPPORTUNITY_TITLE', 'Grant_Title', 'ProjectTitle'
    ]

    for col in title_columns:
        if col in df.columns:
            col_mask = df[col].astype(str).str.lower().str.contains(keyword_pattern, na=False, regex=True)
            mask |= col_mask
            logger.info(f"Found {col_mask.sum()} keyword matches in {col}")
            break

    # Check description columns
    desc_columns = [
        'Description', 'OpportunityDescription', 'description',
        'DESCRIPTION', 'Synopsis', 'Abstract', 'Summary'
    ]

    for col in desc_columns:
        if col in df.columns:
            col_mask = df[col].astype(str).str.lower().str.contains(keyword_pattern, na=False, regex=True)
            mask |= col_mask
            logger.info(f"Found {col_mask.sum()} keyword matches in {col}")
            break

    # Check agency columns for NHTSA, FHWA, DOT
    agency_columns = [
        'AgencyName', 'Agency', 'agency_name', 'AGENCY_NAME',
        'GrantorContactName', 'FundingAgency'
    ]

    agency_keywords = ['NHTSA', 'FHWA', 'Department of Transportation', 'DOT', 'Highway Administration']
    agency_pattern = '|'.join([re.escape(kw) for kw in agency_keywords])

    for col in agency_columns:
        if col in df.columns:
            col_mask = df[col].astype(str).str.contains(agency_pattern, na=False, case=False, regex=True)
            mask |= col_mask
            logger.info(f"Found {col_mask.sum()} agency matches in {col}")
            break

    logger.info(f"Total records matching safety keywords: {mask.sum()}")
    return mask


def filter_grants(df: pd.DataFrame) -> pd.DataFrame:
    """Apply all filters to grants data."""
    original_count = len(df)

    # Combine category and keyword filters with OR logic
    category_mask = filter_transportation_category(df)
    keyword_mask = filter_safety_keywords(df)

    combined_mask = category_mask | keyword_mask

    df_filtered = df[combined_mask].copy()

    logger.info(f"Filtered from {original_count} to {len(df_filtered)} relevant grants")

    return df_filtered


def filter_active_grants(df: pd.DataFrame) -> pd.DataFrame:
    """Filter to only include grants that are still open or recently closed."""
    # Find close date column
    date_columns = [
        'CloseDate', 'close_date', 'CLOSE_DATE', 'ApplicationDueDate',
        'DueDate', 'Deadline', 'ResponseDate'
    ]

    date_col = None
    for col in date_columns:
        if col in df.columns:
            date_col = col
            break

    if date_col:
        try:
            # Parse dates and filter for grants closing in future or recent past (30 days)
            df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
            cutoff_date = datetime.now() - timedelta(days=30)
            mask = (df[date_col].isna()) | (df[date_col] >= cutoff_date)
            df_filtered = df[mask].copy()
            logger.info(f"Filtered to {len(df_filtered)} active/recent grants")
            return df_filtered
        except Exception as e:
            logger.warning(f"Could not filter by date: {e}")

    return df


def select_output_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Select and rename columns for output."""
    # Define preferred columns and their output names
    column_mappings = {
        'OpportunityID': 'opportunity_id',
        'OpportunityNumber': 'opportunity_number',
        'OpportunityTitle': 'title',
        'AgencyName': 'agency',
        'Description': 'description',
        'Synopsis': 'description',
        'CloseDate': 'close_date',
        'PostDate': 'post_date',
        'AwardCeiling': 'award_ceiling',
        'AwardFloor': 'award_floor',
        'EstimatedTotalProgramFunding': 'total_funding',
        'CategoryOfFunding': 'category',
        'EligibleApplicants': 'eligible_applicants',
        'AdditionalInformationURL': 'url',
        'GrantorContactEmail': 'contact_email',
        'LastUpdatedDate': 'last_updated',
    }

    # Find columns that exist in our data
    output_cols = {}
    for orig_col, new_col in column_mappings.items():
        # Try exact match
        if orig_col in df.columns:
            output_cols[orig_col] = new_col
        else:
            # Try case-insensitive match
            for col in df.columns:
                if col.lower() == orig_col.lower():
                    output_cols[col] = new_col
                    break

    if not output_cols:
        logger.warning("Could not map columns, returning all columns")
        return df

    # Select and rename columns
    df_output = df[list(output_cols.keys())].copy()
    df_output = df_output.rename(columns=output_cols)

    return df_output


def main():
    """Main function to download and process grants data."""
    logger.info("=" * 60)
    logger.info(f"Starting grants data download at {datetime.now()}")
    logger.info("=" * 60)

    # Ensure output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    try:
        # Download grants extract
        df = download_grants_extract()

        if df.empty:
            logger.error("No grants data downloaded!")
            sys.exit(1)

        logger.info(f"Downloaded {len(df)} total grants")
        logger.info(f"Available columns: {list(df.columns)}")

        # Filter for traffic safety related grants
        df = filter_grants(df)

        if df.empty:
            logger.warning("No traffic safety grants found after filtering")
            # Create empty CSV with headers
            df = pd.DataFrame(columns=[
                'opportunity_id', 'opportunity_number', 'title', 'agency',
                'description', 'close_date', 'post_date', 'award_ceiling',
                'award_floor', 'total_funding', 'category', 'eligible_applicants',
                'url', 'contact_email', 'last_updated'
            ])
        else:
            # Filter to active grants
            df = filter_active_grants(df)

            # Select output columns
            df = select_output_columns(df)

        # Save to CSV
        logger.info(f"Saving {len(df)} grants to {OUTPUT_FILE}")
        df.to_csv(OUTPUT_FILE, index=False)

        logger.info("=" * 60)
        logger.info(f"Successfully processed grants data")
        logger.info(f"Output saved to: {OUTPUT_FILE}")
        logger.info("=" * 60)

        return 0

    except Exception as e:
        logger.error(f"Failed to download grants data: {e}")
        # Don't fail completely - create empty file with error note
        try:
            error_df = pd.DataFrame({
                'error': [f'Download failed: {str(e)}'],
                'timestamp': [datetime.now().isoformat()]
            })
            error_df.to_csv(OUTPUT_FILE, index=False)
            logger.info(f"Created error placeholder at {OUTPUT_FILE}")
        except Exception:
            pass

        return 1


if __name__ == "__main__":
    sys.exit(main())
