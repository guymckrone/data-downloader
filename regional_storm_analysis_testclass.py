from config import OUTPUT_DIR, START_DATE, END_DATE
from logging_setup import setup_logging, get_logger
from data_loader import find_latest_database, load_rainfall_data, filter_by_date
from storm import Storm
from storm_catalog import StormCatalog

setup_logging()
logger = get_logger(__name__)


def main():
    # Load data
    logger.info("Starting...")
    
    db_path = find_latest_database(OUTPUT_DIR)
    if db_path is None:
        return
    
    rain_df = load_rainfall_data(db_path)
    rain_df = filter_by_date(rain_df, START_DATE, END_DATE)
    
    print(f"Loaded {len(rain_df):,} timestamps")
    
    # === Test Step 1: Create catalog ===
    print("\n" + "="*60)
    print("STEP 1: CREATE CATALOG")
    print("="*60)
    
    catalog = StormCatalog(
        rain_df,
        min_gauges=3,
        interevent_hours=6
    )
    
    print(f"\ncatalog.min_gauges: {catalog.min_gauges}")
    print(f"catalog.interevent_hours: {catalog.interevent_hours}")
    print(f"catalog.minutes_per_step: {catalog.minutes_per_step}")
    print(f"catalog.interevent_steps: {catalog.interevent_steps}")
    print(f"catalog.storms: {catalog.storms}")

        # === Test Step 2: Find storms ===
    print("\n" + "="*60)
    print("STEP 2: FIND STORMS")
    print("="*60)
    
    catalog.find_storms()
    
    print(f"\nStorm series created: {len(catalog.storm_series):,} timestamps")
    print(f"Max storm number: {catalog.storm_series.max()}")

        # === Test Step 3: Examine Storm objects ===
    print("\n" + "="*60)
    print("STEP 3: EXAMINE STORM OBJECTS")
    print("="*60)
    
    print(f"\ncatalog.storms has {len(catalog.storms)} storms")
    
    # Look at first storm
    print(f"\n--- First Storm ---")
    storm1 = catalog.storms[0]
    print(f"  storm1.number: {storm1.number}")
    print(f"  storm1.start_time: {storm1.start_time}")
    print(f"  storm1.end_time: {storm1.end_time}")
    print(f"  storm1.duration_hours: {storm1.duration_hours:.1f}")
    print(f"  storm1.total_rain: {storm1.total_rain:.3f}")
    print(f"  storm1.wettest_gauge: {storm1.wettest_gauge}")
    
    # Look at first 5 storms
    print(f"\n--- First 5 Storms ---")
    for storm in catalog.storms[:5]:
        print(f"  Storm {storm.number}: "
              f"{storm.start_time.date()}, "
              f"{storm.duration_hours:.1f} hrs, "
              f"mean={storm.mean_gauge_rain:.3f}, "
              f"max={storm.max_gauge_rain:.3f}")
        
    # Sanity check Storm 4
    print(f"\n--- Sanity Check: Storm 4 ---")
    storm4 = catalog.get_storm(4)
    print(f"  total_rain (network sum): {storm4.total_rain:.3f}")
    print(f"  n_gauges: {storm4.n_gauges}")
    print(f"  mean_gauge_rain: {storm4.mean_gauge_rain:.3f}")
    print(f"  max_gauge_rain: {storm4.max_gauge_rain:.3f}")
    print(f"  wettest_gauge: {storm4.wettest_gauge}")
    print(f"\n  Per-gauge totals:")
    print(storm4.gauge_totals)

     # === PM Requirements Test ===
    print("\n" + "="*60)
    print("PM REQUIREMENTS: REGIONAL STORM SUMMARY")
    print("="*60)
    
    print(f"\nTotal storms found: {catalog.n_storms}")
    print(f"Period: {catalog.storms[0].start_time.date()} to "
          f"{catalog.storms[-1].start_time.date()}")
    
    # Biggest storms
    print(f"\n--- Top 10 Largest Storms (by mean rainfall) ---")
    print(f"{'Storm':<8} {'Date':<12} {'Hours':<8} {'Mean Rain':<10} "
          f"{'Max Rain':<10} {'Missing':<8} {'Wettest gauge':<12}")
    print("-" * 75)
    
    for storm in catalog.get_largest_storms(10, by='mean_gauge_rain'):
        print(f"{storm.number:<8} "
              f"{storm.start_time.strftime('%Y-%m-%d'):<12} "
              f"{storm.duration_hours:<8.1f} "
              f"{storm.mean_gauge_rain:<10.3f} "
              f"{storm.max_gauge_rain:<10.3f} "
              f"{storm.avg_gauges_missing:<8.1f} "
              f"{storm.wettest_gauge:<12}")
    
    # Export to CSV
    print(f"\n--- Exporting to CSV ---")
    catalog.to_csv(OUTPUT_DIR)
    
    # Preview the DataFrame
    print(f"\nDataFrame preview:")
    df = catalog.to_dataframe()
    print(df.head())


if __name__ == "__main__":
    main()