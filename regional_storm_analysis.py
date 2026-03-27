from config import OUTPUT_DIR, START_DATE, END_DATE
from logging_setup import setup_logging, get_logger
from data_loader import find_latest_database, load_rainfall_data, filter_by_date
import numpy as np
import pandas as pd

setup_logging()
logger = get_logger(__name__)

def main():
    ### Load Data
    logger.info("Starting gauge analysis...")
    # Find the database
    db_path = find_latest_database(OUTPUT_DIR)
    logger.info(f"Using database: {db_path}")

    if db_path is None:
        logger.error("Cannot continue without a database file")
        return
    
    # Load into DataFrame
    rain_df = load_rainfall_data(db_path)

    # Limit dates
    rain_df = filter_by_date(rain_df, START_DATE, END_DATE)

    logger.info(f"Loaded {len(rain_df):,} timestamps, {len(rain_df.columns)} gauges")

    ### Find Storms
    catalog = StormCatalog(
        rain_df,
        min_gauges=3,
        interevent_hours=6
    )
    catalog.find_storms()

    ### Summary Report
    print(f"\n{'='*75}")
    print("REGIONAL STORM ANALYSIS SUMMARY")
    print(f"{'='*75}")

if __name__ == "__main__":
    main()

# :, thousand comma separator

# .total_seconds