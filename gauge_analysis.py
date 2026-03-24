
from datetime import datetime
import os
import sqlite3
import pandas as pd
import numpy as np


# Import shared configuration
from config import OUTPUT_DIR, START_DATE, END_DATE
from data_loader import find_latest_database, load_database_to_dataframe, _load_from_database
from logging_setup import setup_logging, get_logger

# Set up logging
setup_logging()
logger = get_logger(__name__)

def analyze_single_gauge(rain_df, gauge_name):
    total_timesteps = len(rain_df)

    # Returns true for every NaN value
    missing_mask = rain_df[gauge_name].isna()

    # Counts number of True values and then calculates missing
    n_missing = missing_mask.sum()
    pct_missing = (n_missing / total_timesteps) * 100

    logger.info(f"  {gauge_name}: missing {n_missing:,} of {total_timesteps:,} timesteps ({pct_missing:.1f}%)")

    return {
        'gauge': gauge_name,
        'n_missing': n_missing,
        'pct_missing': round(pct_missing, 2)
    }

def analyze_gauge_coobservation(rain_df, gauge_name):

    total_timesteps = len(rain_df)

    # Where is this gauge missing
    missing_mask = rain_df[gauge_name].isna()
    n_missing = missing_mask.sum()

    # When this gauge is missing, are other gauges missing
    when_missing = rain_df.loc[missing_mask] # Rows where this gauge is missing
    others = when_missing.drop(columns=gauge_name) # All other gauges

    # Do any other gauges have data?
    others_have_data = others.notna().any(axis=1) # True if at least one other gauge has data
    all_others_missing = others.isna().all(axis=1) # True if all others are missing data

    n_missing_but_others_observe = others_have_data.sum()
    n_missing_and_all_others_missing = all_others_missing.sum()

    check_values = n_missing_but_others_observe + n_missing_and_all_others_missing
    if check_values != n_missing:
        logger.warning(f"   {gauge_name}: Value Check Failed")
        logger.warning(f"    n_missing: {n_missing}")
        logger.warning(f"    others_observe + all_missing = {check_values}")

    # Calculate percentages
    pct_missing = (n_missing / total_timesteps) * 100

    # These are % of the missing time (not total time)
    if n_missing > 0:
        pct_others_observe = (n_missing_but_others_observe / n_missing) * 100
        pct_all_missing = (n_missing_and_all_others_missing / n_missing) * 100
    else:
        pct_others_observe = 0
        pct_all_missing = 0

    # What rainfall when this gauge is missing but other observe?
    # Getting all values from other gauges at this time
    when_missing_but_others_observe = when_missing.loc[others_have_data]
    other_values = when_missing_but_others_observe.drop(columns=gauge_name)

    # Into one series (all rainfall data from other gauges)
    all_other_rainfall = other_values.stack()

    # Calc percentiles
    if len(all_other_rainfall) > 0:
        percentiles = all_other_rainfall.quantile([0.05, 0.25, 0.50, 0.75, 0.95, 0.99, 1])
    else:
        percentiles = pd.Series([np.nan] * 5, index = [0.05, 0.25, 0.50, 0.75, 0.95, 0.99, 1])

    return {
        'gauge': gauge_name,
        'pct_missing': round(pct_missing, 2),
        'pct_others_observe_when_missing': round(pct_others_observe, 2),
        'pct_all_missing_when_missing': round(pct_all_missing, 2),
        'other_rain_05th': round(percentiles[0.05], 4),
        'other_rain_25th': round(percentiles[0.25], 4),
        'other_rain_50th': round(percentiles[0.50], 4),
        'other_rain_75th': round(percentiles[0.75], 4),
        'other_rain_95th': round(percentiles[0.95], 4),
        'other_rain_99th': round(percentiles[0.99], 4),
        'other_rain_max': round(percentiles[1], 4),
        'n_coobservations': len(all_other_rainfall)
    }

def analyze_all_gauges(rain_df):
    
    results = []
    n_gauges = len(rain_df.columns)

    for i, gauge in enumerate(rain_df.columns):
        logger.info(f"[{i+1}/{n_gauges}] Analyzing {gauge}...")
        result = analyze_gauge_coobservation(rain_df, gauge)
        results.append(result)

    # Convert list of dicts to DataFrame
    summary = pd.DataFrame(results)

    return summary
        
def investigate_data_quality(rain_df):

    logger.info("\n" + "="*60)
    logger.info("DATA QUALITY INVESTIGATION")
    logger.info("="*60)

    # Time range info
    print("\nTime Range:")
    print(f"  Start: {rain_df.index.min()}")
    print(f"  End:   {rain_df.index.max()}")
    print(f"  Total Timesteps: {len(rain_df):,}")

    # Calc expected years
    time_span = rain_df.index.max() - rain_df.index.min()
    print(f"  Time span: {time_span.days / 365:.1f} years")

    # Check when each gauge FIRST has data
    print("\nFirst valid data point per gauge:")
    for gauge in rain_df.columns:
        first_valid = rain_df[gauge].first_valid_index()
        print(f"  {gauge}: {first_valid}")

    for gauge in rain_df.columns:
        total = len(rain_df)
        n_nan = rain_df[gauge].isna().sum()
        n_zero = (rain_df[gauge] == 0).sum()
        n_positive = (rain_df[gauge] > 0).sum()

        pct_nan = (n_nan / total) * 100
        pct_zero = (n_zero / total) * 100
        pct_positive = (n_positive / total) * 100

        print(f"\n{gauge}:")
        print(f"  NaN (missing): {n_nan:>8,} ({pct_nan:>5.1f}%)")
        print(f"  Zero values: {n_zero:>8,} ({pct_zero:>5.1f}%)")
        print(f"  Positive values: {n_positive:>8,} ({pct_positive:>5.1f}%)")
        print(f"  Total: {total:>8,}")

def investigate_true_missingness(rain_df):
    print(f"\n{'gauge':<12} {'Started':<22} {'Total After':<12} {'Missing':<12} {'% Missing':<10}")
    print("-" * 70)

    for gauge in rain_df.columns:
        # FInd when gauge first has data
        first_valid = rain_df[gauge].first_valid_index()

        if first_valid is None:
            print(f"{gauge:<12} {'NO DATA':<22}")
            continue
        
        # Slice from first data onwards
        gauge_data = rain_df.loc[first_valid:, gauge]

        total_after_start = len(gauge_data)
        n_missing = gauge_data.isna().sum()
        pct_missing = (n_missing / total_after_start) * 100

        print(f"{gauge:<12} {str(first_valid)[:19]:<22} {total_after_start:<12,} {n_missing:<12,} {pct_missing:<10.1f}%")

def investigate_yearly_pattern(rain_df, gauge_name):
    """
    Show missingness by year for a single gauge.
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"YEARLY PATTERN FOR {gauge_name}")
    logger.info(f"{'='*60}")
    
    # Get just this gauge's data
    gauge_data = rain_df[gauge_name]
    
    # Group by year
    gauge_data_with_year = gauge_data.to_frame()
    gauge_data_with_year['year'] = gauge_data_with_year.index.year
    
    print(f"\n{'Year':<8} {'Total':<10} {'Has Data':<10} {'Missing':<10} {'% Missing':<10}")
    print("-" * 50)
    
    for year in sorted(gauge_data_with_year['year'].unique()):
        year_data = gauge_data_with_year[gauge_data_with_year['year'] == year][gauge_name]
        
        total = len(year_data)
        n_missing = year_data.isna().sum()
        n_has_data = total - n_missing
        pct_missing = (n_missing / total) * 100
        
        # Visual bar
        bar_length = int((100 - pct_missing) / 5)  # 20 chars max
        bar = "█" * bar_length + "░" * (20 - bar_length)
        
        print(f"{year:<8} {total:<10,} {n_has_data:<10,} {n_missing:<10,} {pct_missing:>5.1f}%  {bar}")

def investigate_hourly_pattern(rain_df, gauge_name):
    """
    Show data availability by hour of day.
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"HOURLY PATTERN FOR {gauge_name}")
    logger.info(f"{'='*60}")
    
    # Get just this gauge's data
    gauge_data = rain_df[gauge_name]
    
    # Add hour column
    gauge_data_with_hour = gauge_data.to_frame()
    gauge_data_with_hour['hour'] = gauge_data_with_hour.index.hour
    
    print(f"\n{'Hour':<6} {'Total':<12} {'Has Data':<12} {'% Has Data':<12}")
    print("-" * 45)
    
    for hour in range(24):
        hour_data = gauge_data_with_hour[gauge_data_with_hour['hour'] == hour][gauge_name]
        
        total = len(hour_data)
        n_has_data = hour_data.notna().sum()
        pct_has_data = (n_has_data / total) * 100 if total > 0 else 0
        
        # Visual bar
        bar_length = int(pct_has_data / 5)
        bar = "█" * bar_length + "░" * (20 - bar_length)
        
        print(f"{hour:02d}:00  {total:<12,} {n_has_data:<12,} {pct_has_data:>5.1f}%  {bar}")

def investigate_minute_pattern(rain_df, gauge_name):
    """
    Show data availability by minute of hour.
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"MINUTE PATTERN FOR {gauge_name}")
    logger.info(f"{'='*60}")
    
    # Get just this gauge's data
    gauge_data = rain_df[gauge_name]
    
    # Add minute column
    gauge_data_with_minute = gauge_data.to_frame()
    gauge_data_with_minute['minute'] = gauge_data_with_minute.index.minute
    
    print(f"\n{'Minute':<8} {'Total':<12} {'Has Data':<12} {'% Has Data':<12}")
    print("-" * 50)
    
    for minute in sorted(gauge_data_with_minute['minute'].unique()):
        minute_data = gauge_data_with_minute[gauge_data_with_minute['minute'] == minute][gauge_name]
        
        total = len(minute_data)
        n_has_data = minute_data.notna().sum()
        pct_has_data = (n_has_data / total) * 100 if total > 0 else 0
        
        # Visual bar
        bar_length = int(pct_has_data / 5)
        bar = "█" * bar_length + "░" * (20 - bar_length)
        
        print(f":{minute:02d}     {total:<12,} {n_has_data:<12,} {pct_has_data:>5.1f}%  {bar}")

def investigate_gauge_timing(rain_df):
    for gauge in rain_df.columns:
        has_data = rain_df[gauge].dropna()

        minutes = has_data.index.minute.unique()
        minutes_sorted = sorted(minutes)

        print(f"{gauge:<12} records at minutesL {minutes_sorted}")

def save_results(summary_df, output_dir):
    filename = f"coobservation_analysis_{datetime.now().strftime('%Y-%m-%d_%H%M')}.csv"
    filepath = os.path.join(output_dir, filename)

    summary_df.to_csv(filepath, index=False)
    logger.info(f"Results saved to: {filepath}")

    return filepath

def main():
    logger.info("Starting gauge analysis...")

    # Find the database
    db_path = find_latest_database(OUTPUT_DIR)
    
    if db_path is None:
        logger.error("Cannot continue without a database file")
        return
    
    # Load into DataFrame
    rain_df = load_database_to_dataframe(db_path)

    # Limit dates
    if START_DATE and END_DATE:
        rain_df = rain_df.loc[START_DATE:END_DATE]
        logger.info(f"Filtered to {START_DATE} to {END_DATE}: {len(rain_df):,} timestamps")

    # Check true missingness
    # investigate_true_missingness(rain_df)
    logger.info("Analysis complete!")

    # Quick summary
    print("\nData Summary:")
    print(f"  Timestamps: {len(rain_df):,}")
    print(f"  gauges: {len(rain_df.columns)}")
    print(f"  Date range: {rain_df.index.min()} to {rain_df.index.max()}")

    # Analyze all gauges
    summary = analyze_all_gauges(rain_df)
    print(summary.to_string(index = False))

    save_results(summary, OUTPUT_DIR)
    logger.info("Analysis complete!")

    # Below calls are useful to analyzing data gaps
    """investigate_data_quality(rain_df)
    investigate_yearly_pattern(rain_df, "HYDRA-4")
    investigate_hourly_pattern(rain_df, "HYDRA-4")
    investigate_minute_pattern(rain_df, "HYDRA-4")
    investigate_gauge_timing(rain_df)
"""
if __name__ == "__main__":
    main()