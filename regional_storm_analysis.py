from config import OUTPUT_DIR, START_DATE, END_DATE
from logging_setup import setup_logging, get_logger
from data_loader import find_latest_database, load_rainfall_data, filter_by_date
from storm_catalog import StormCatalog

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

    # Report
    print(f"\n{'='*75}")
    print("REGIONAL STORM ANALYSIS")
    print(f"{'='*75}")
    print(f"Total storms: {catalog.n_storms:,}")

    print(f"\n--- Top 10 Largest Storms ---")
    print(f"{'Storm':<8} {'Date':<12} {'Hours':<8} {'Mean Rain':<10} {'Max Rain':<10}")
    print("-" * 55)
    
    for storm in catalog.get_largest_storms(10, by='mean_gauge_rain'):
        print(f"{storm.number:<8} "
              f"{storm.start_time.strftime('%Y-%m-%d'):<12} "
              f"{storm.duration_hours:<8.1f} "
              f"{storm.mean_gauge_rain:<10.3f} "
              f"{storm.max_gauge_rain:<10.3f}")

    # Export
    catalog.to_csv(OUTPUT_DIR)
    logger.info("Analysis complete!")

if __name__ == "__main__":
    main()

# :, thousand comma separator

# .total_seconds