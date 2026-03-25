from config import OUTPUT_DIR, START_DATE, END_DATE
from logging_setup import setup_logging, get_logger
from data_loader import find_latest_database, load_rainfall_data, filter_by_date

setup_logging()
logger = get_logger(__name__)

MIN_GAUGES = 3
INTEREVENT_HOURS = 6

def examine_single_timestamp(rain_df):
    first_row = rain_df.iloc[0]
    timestamp = rain_df.index[0]

    print(timestamp)
    print(first_row)

    n_with_rain = (first_row > 0).sum()
    print(f"{n_with_rain} out of {len(first_row)}")

def count_raining_gages(rain_df):
    return (rain_df > 0).sum(axis = 1)

def summarize_rain_frequency(n_gauges_raining):
    print(f"Min gauges raining at once: {n_gauges_raining.min()}")
    print(f"Max gauges raining at once: {n_gauges_raining.max()}")
    print(f"Mean: {n_gauges_raining.mean():.2f}")

    pct_any_rain = (n_gauges_raining > 0).mean() * 100
    pct_three_plus = (n_gauges_raining > 3).mean() * 100

    print(f"% of time with at least 1 gauge raining: {pct_any_rain}")
    print(f"% of time with at least 3 gauge raining: {pct_three_plus}")


def define_network_wet(n_gauges_raining, min_gauges):
    return n_gauges_raining >= min_gauges

def summarize_wet_periods(network_is_wet):
    n_wet = network_is_wet.sum()
    n_total = len(network_is_wet)

    logger.info(f"Wet timestamps: {n_wet:,} or {(n_wet/n_total) * 100:.1f}%")
    logger.info(f"Dry timestamps: {n_total-n_wet:,} or {((n_total-n_wet)/n_total) * 100:.1f}%")

def count_transitions(network_is_wet):

    changes = network_is_wet.astype(int).diff() # Converts bools to int and calculates difference between each row
    n_starts = (changes == 1).sum()
    n_stops = (changes == -1).sum

    logger.info(f"{n_starts} starts")
    logger.info(f"{n_stops} stops")

    return changes

def calculate_interevent_periods(rain_df, interevent_hours=6):

    # Figre out time between rows
    time_diff = rain_df.index[1] - rain_df.index[0]
    minutes_per_step = time_diff.total_seconds() / 60
    steps_per_hour = 60 / minutes_per_step
    interevent_steps = int(interevent_hours * steps_per_hour)

    logger.info(f"Time between observations: {minutes_per_step:.0f} minutes")
    logger.info(f"Inter-event period: {interevent_hours} hours = {interevent_steps} timesteps")

    return interevent_steps

def apply_interevent_window(network_is_wet, interevent_steps):

    in_storm = (
        network_is_wet
        .rolling(window=interevent_steps, min_periods=1)
        .max()
        .astype(bool)   
    )

    return in_storm

def main():

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

    # Single Timestep
    examine_single_timestamp(rain_df)

    # Entire Dataset
    n_gauges_raining = count_raining_gages(rain_df)
    summarize_rain_frequency(n_gauges_raining)
    
    logger.info(f"Using threshold: at least {MIN_GAUGES} gauges")
    network_is_wet = define_network_wet(n_gauges_raining, MIN_GAUGES)

    print(network_is_wet.head)
    summarize_wet_periods(network_is_wet)
    changes = count_transitions(network_is_wet)

    interevent_steps = calculate_interevent_periods(rain_df, INTEREVENT_HOURS)

    in_storm = apply_interevent_window(network_is_wet, interevent_steps)

    print(f"Before Wet Timestamps: {network_is_wet.sum():,}")
    print(f"After: {in_storm.sum():,}")

    storm_changes = in_storm.astype(int).diff()
    n_storms = (storm_changes == 1).sum()

    print(f"Before: {(changes == 1).sum():,} After: {n_storms:,}")

if __name__ == "__main__":
    main()