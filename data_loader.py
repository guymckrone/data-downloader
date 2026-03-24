import os
import sqlite3
import pandas as pd
from logging_setup import setup_logging, get_logger

# Setup logging
setup_logging()
logger = get_logger(__name__)

def find_latest_database(output_dir):
    logger.info(f"Looking for database files in {output_dir}...")

    # Get all files in the directory
    all_files = os.listdir(output_dir)
    
    # Filter to only .db files
    db_files = [f for f in all_files if f.endswith('.db')]

    if not db_files:
        logger.error(f"No .db files found in {output_dir}")
        return None
    
    logger.info(f"Found {len(db_files)} database file(s)")

    #If multiple databases, picks most recent
    if len(db_files) > 1:
        # Sort by modification time, with most recent first
        db_files.sort(
            key=lambda f: os.path.getmtime(os.path.join(output_dir, f)),
            reverse=True
        )
    
    # Builds the full path
    db_path = os.path.join(output_dir, db_files[0])
    logger.info(f"Using database: {db_path}")

    return db_path

def load_database_to_dataframe(db_path):
    logger.info("Loading data from database")
    
    df = _load_from_database(db_path)
    df['timestamp_aligned'] = df['timestamp'].dt.round('15min')

    logger.info(f"  Example: {df['timestamp'].iloc[0]} -> {df['timestamp_aligned'].iloc[0]}")

    logger.info("Pivoting to wide format")

    wide = df.pivot_table(
        index='timestamp_aligned',  # Rows = timestamps that are aligned to the 00:00 mark
        columns='location',         # Columns will be gauge names
        values='value',             # Cell values will be rainfall amounts
        aggfunc='first'             # If duplicate entries, take the first
    )

    logger.info(f"Result: {len(wide):,} timestamps x {len(wide.columns)} gauges")
    logger.info(f"gauges: {', '.join(wide.columns[:5])}{'...' if len(wide.columns) > 5 else ''}")

    return wide

def _load_from_database(db_path):
    # Connect to database
    with sqlite3.connect(db_path) as conn:
        # Read data into dataframe
        df = pd.read_sql("""
            SELECT timestamp, value, location
            FROM precipitation_data
            ORDER BY timestamp
        """, conn)
    
    logger.info(f"Loaded {len(df):,} rows from database")

    # Convert timestamp column to datetime objects
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    return df
