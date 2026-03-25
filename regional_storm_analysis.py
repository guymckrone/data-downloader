from config import OUTPUT_DIR, START_DATE, END_DATE
from logging_setup import setup_logging, get_logger
from data_loader import find_latest_database, load_rainfall_data, filter_by_date
import numpy as np
import pandas as pd

setup_logging()
logger = get_logger(__name__)

MIN_GAUGES = 3
INTEREVENT_HOURS = 6

class Storm:
    """
    Represents a single storm event

    Storm knows:
        When it started and ended
        Which timestamps belong to it
        The rainfall data during the storm

    A Storm can:
        Calculate its duration
        Calculate rainfall stats
        Report on missing gages
    
    """
    def __init__(self, number, rain_data):
        
        self.number = number
        self.timestamps = rain_data.index
        self.rain_data = rain_data

        # Calulcate basic properties right off the bat
        self.start_time = self.timestamps.min()
        self.end_time = self.timestamps.max()
        self.n_timestamps = len(self.timestamps)
        self.n_gauges = len(rain_data.columns)

    @property
    def duration_hours(self):
        # Storm duration in hours
        delta = self.end_time - self.start_time
        return delta.total_seconds() / 3600
    
    @property
    def duration_days(self):
        # Storm duration in days
        return self.duration.hours / 24
    
    ## Rainfall Properties 


    @property
    def total_rain(self):
        # Total rainfall across all gauges
        return self.rain_data.sum().sum() # First sum gets per gauge totals, second sum adds them all
    
    @property
    def gauge_totals(self):
        # Rainfall total per gauge
        return self.rain_data.sum().sort_values(ascending=False)
    
    @property
    def wettest_gauge(self):
        # Name of gauge with most rainfall
        return self.gauge_totals.idxmax() # Returns index of max value, which is the gauge name
    
    @property
    def peak_intensity(self):
        # Highest rainfall at any single gauge
        return self.rain_data.max().max()
    

    ## Missing Data Properties

    @property
    def avg_gauges_missing(self):
        # Average number of gauges with missing data per timestamp
        missing_per_ts = (self.rain_data > 0).isna().sum(axis=1) # Counts missing (True) per row
        return missing_per_ts.mean() # Averages across all timestamps
    
    @property
    def max_gauges_missing(self):
        # Max gauges missing at any timestamp
        missing_per_ts = (self.rain_data > 0).isna().sum(axis=1)
        return missing_per_ts.max()
    
    def pct_data_missing(self):
        # Percentage of all possible readings that are missing
        # Total possible 
        total_cells = self.n_timestamps * self.n_gauges

    
    def to_dict(self):
        # Convert storm to dictionary (For creating dataframes)
        return {
            'storm_number': self.number

        }

    
    

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
    minutes_per_step = time_diff.total_seconds() / 60 # Get seconds as plain number from date time object
    steps_per_hour = 60 / minutes_per_step
    interevent_steps = int(interevent_hours * steps_per_hour)

    logger.info(f"Time between observations: {minutes_per_step:.0f} minutes")
    logger.info(f"Inter-event period: {interevent_hours} hours = {interevent_steps} timesteps")

    return interevent_steps

def apply_interevent_window(network_is_wet, interevent_steps):

    in_storm = (
        network_is_wet
        .rolling(window=interevent_steps, min_periods=1) # Uses the interevent window to calculate if we are still in a storm, min periods allows for it to work at the beginning
        .max() # FOr each window find the max value, for if it is > 0 it rained in the period
        .astype(bool) # Converts back to bool
    )

    return in_storm

def find_storm_starts(in_storm):
    as_integer = in_storm.astype(int) # Converts to int

    differences = as_integer.diff() # Calcs difference from previous row

    storm_starts = (differences == 1) # Finds where diff == 1 which is where a storm starts

    return storm_starts

def assign_storm_numbers(in_storm, storm_starts):
    cumulative_storms = storm_starts.cumsum() # Cumulative sum of storm starts

    storm_numbers = np.where(
        in_storm, # Condition: In storm
        cumulative_storms, # If true, use the storm number
        0 # If false use 0
    )

    storm_series = pd.Series(
        storm_numbers,          # The data, storm numbers
        index = in_storm.index, # The index, the timestamps
        name = 'storm'          # Column name
    )

    return storm_series

def summarize_storms(storm_series):
    n_storms = storm_series.max() # Tells how many storms (last storm number)
    
    # How many timestamps are in storms vs not
    n_in_storm = (storm_series > 0).sum()
    n_not_in_storm = (storm_series == 0).sum()
    n_total = len(storm_series)

    # Print summary
    print(f"Total storms {n_storms:,}")
    print(f"  Timstamps in a storm {n_in_storm}")
    print(f"  Timstamps not in a storm {n_not_in_storm}")
    
def show_first_storms(storm_series, n_storms_to_show=5):

    for storm_num in range(1, n_storms_to_show + 1):
        # Get all timestamps for this storm
        storm_mask = (storm_series == storm_num) # Gives true/false for storm series and gives this storms timestamps
        storm_timestamps = storm_series[storm_mask].index

        # First and last timestamp
        start = storm_timestamps.min()
        end = storm_timestamps.max()

        # Finding duration

        duration_dt = end - start
        duration_hours = duration_dt.total_seconds() / 3600 # Gets duration in hours

        print(f"{storm_num:<8} {str(start):<25} {str(end):<25} {duration_hours:<.1f} hours")

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

    print(network_is_wet.head())
    summarize_wet_periods(network_is_wet)
    changes = count_transitions(network_is_wet)

    interevent_steps = calculate_interevent_periods(rain_df, INTEREVENT_HOURS)

    in_storm = apply_interevent_window(network_is_wet, interevent_steps)

    print(f"Before Wet Timestamps: {network_is_wet.sum():,}")
    print(f"After: {in_storm.sum():,}")

    storm_changes = in_storm.astype(int).diff()
    n_storms = (storm_changes == 1).sum()

    print(f"Before: {(changes == 1).sum():,} After: {n_storms:,}")

    storm_starts = find_storm_starts(in_storm)
    n_starts = storm_starts.sum()
    print(f"Found {n_starts:,} storm starts")

    storm_series = assign_storm_numbers(in_storm, storm_starts)

    summarize_storms(storm_series)

    show_first_storms(storm_series, n_storms_to_show=10)

if __name__ == "__main__":
    main()

# :, thousand comma separator

# .total_seconds