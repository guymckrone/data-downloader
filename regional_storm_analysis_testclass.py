from config import OUTPUT_DIR, START_DATE, END_DATE
from logging_setup import setup_logging, get_logger
from data_loader import find_latest_database, load_rainfall_data, filter_by_date
from storm import Storm  # Import our new class!

setup_logging()
logger = get_logger(__name__)


def main():
    # === Load Data ===
    logger.info("Starting regional storm analysis...")
    
    db_path = find_latest_database(OUTPUT_DIR)
    if db_path is None:
        return
    
    rain_df = load_rainfall_data(db_path)
    rain_df = filter_by_date(rain_df, START_DATE, END_DATE)
    
    print(f"Loaded {len(rain_df):,} timestamps, {len(rain_df.columns)} gauges")
    
    # === Test the Storm class ===
    print("\n" + "="*60)
    print("TESTING THE STORM CLASS")
    print("="*60)
    
    # Let's manually create a storm from the first day of data
    # Just to test that our class works
    
    # Get first 24 hours of data (96 timestamps at 15-min intervals)
    test_rain_data = rain_df.iloc[:96]
    
    print(f"\nCreating a test storm from first 24 hours...")
    print(f"  Timestamps: {len(test_rain_data)}")
    print(f"  Start: {test_rain_data.index[0]}")
    print(f"  End: {test_rain_data.index[-1]}")
    
    # Create a Storm object
    test_storm = Storm(number=1, rain_data=test_rain_data)
    
    # Test the string representation
    print(f"\n--- String representation ---")
    print(f"repr: {test_storm}")
    
    # Test individual properties
    print(f"\n--- Properties ---")
    print(f"storm.number: {test_storm.number}")
    print(f"storm.start_time: {test_storm.start_time}")
    print(f"storm.end_time: {test_storm.end_time}")
    print(f"storm.duration_hours: {test_storm.duration_hours}")
    print(f"storm.n_timestamps: {test_storm.n_timestamps}")
    print(f"storm.n_gauges: {test_storm.n_gauges}")
    
    print(f"\n--- Rainfall properties ---")
    print(f"storm.total_rain: {test_storm.total_rain}")
    print(f"storm.wettest_gauge: {test_storm.wettest_gauge}")
    print(f"storm.max_gauge_rain: {test_storm.max_gauge_rain}")
    print(f"storm.peak_intensity: {test_storm.peak_intensity}")
    
    print(f"\n--- Per-gauge totals ---")
    print(test_storm.gauge_totals)
    
    print(f"\n--- Missing data ---")
    print(f"storm.avg_gauges_missing: {test_storm.avg_gauges_missing}")
    print(f"storm.pct_data_missing: {test_storm.pct_data_missing}%")
    
    # Test the summary method
    test_storm.summary()
    
    # Test to_dict
    print(f"\n--- to_dict() ---")
    storm_dict = test_storm.to_dict()
    for key, value in storm_dict.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()