import numpy as np
import pandas as pd
from logging_setup import setup_logging, get_logger
from storm import Storm
import os
from datetime import datetime

setup_logging()
logger = get_logger(__name__)

class StormCatalog:
    #Finds and manages storms in a rainfall dataset

    """
    Example:
        catalog = StormCatalog(rain_df, min_gauges=3, interevent_hours=6)
        catalog.find_storms()
        print(catalog.n_storms)
    """

    def __init__(self, rain_df, min_gauges=3, interevent_hours=6, rain_threshold=0.0):
        # Store inputs
        self.rain_df = rain_df
        self.min_gauges = min_gauges
        self.interevent_hours = interevent_hours
        self.rain_threshold = rain_threshold

        # To fill in
        self.storms = None
        self.storm_series = None

        # Calculate time step info
        time_diff = rain_df.index[1] - rain_df.index[0]
        self.minutes_per_step = time_diff.total_seconds()/60
        self.steps_per_hour = 60 / self.minutes_per_step
        self.interevent_steps = int(interevent_hours * self.steps_per_hour)

    @property
    def n_storms(self):
        # Number of storms found

        if self.storms is None:
            return 0
        return len(self.storms)
    
    def find_storms(self):
        # Find all storms in the data

        # Identify Wet Periods
        network_is_wet = self._identify_wet_periods()

        # Apply Inter-Event Window
        in_storm = self._apply_interevent_window(network_is_wet)
        
        # Assign Storm Numbers
        self._assign_storm_numbers(in_storm)

        # Create Storm Objects
        self._create_storm_objects()

    def _identify_wet_periods(self):
        # Count gauges with rain at each timestep
        n_gauges_raining = (self.rain_df > self.rain_threshold).sum(axis = 1)

        # Log used variables
        logger.info(f"  Rain Threshold: {self.rain_threshold}")
        logger.info(f"  Min Gauges: {self.min_gauges}")

        # Network is wet when enough gauges have rain
        network_is_wet = n_gauges_raining >= self.min_gauges

        return network_is_wet

    def _apply_interevent_window(self, network_is_wet):
        # Has it rained in the last n hours?
        in_storm = (
            network_is_wet
            .rolling(window=self.interevent_steps, min_periods=1) # Uses the interevent window to calculate if we are still in a storm, min periods allows for it to work at the beginning
            .max() # FOr each window find the max value, for if it is > 0 it rained in the period
            .astype(bool) # Converts back to bool
        )

        n_in_storm = in_storm.sum()
        logger.info(f"  In-storm timestamps: {n_in_storm:,}")

        return in_storm
    
    def _assign_storm_numbers(self, in_storm):
        # Find where storms start (transition from false to true)
        storm_starts = (in_storm.astype(int).diff() == 1)

        # Cumulative count of starts
        cumulative_storms = storm_starts.cumsum()

        # Only assign numbers during storms
        storm_numbers = np.where(in_storm, cumulative_storms, 0)
        
        # Store as series

        self.storm_series = pd.Series(
            storm_numbers,
            index=self.rain_df.index,
            name='storm'
        )

        n_storms = self.storm_series.max()
        logger.info(f"  Storms Identified: {n_storms:,}")

    def _create_storm_objects(self):
        logger.info(f"  Creating Storm Objects...")
        n_storms = self.storm_series.max()

        self.storms = [] # Assigns empty list in case called twice

        for storm_num in range(1, n_storms + 1):
            # Get rainfall data for this storm
            storm_mask = (self.storm_series == storm_num) # Create true/false for each timestep if storm is/isn't that number
            storm_rain_data = self.rain_df[storm_mask] # Extracts only the rows with True (ONly rain data during that storm)

            # Create Storm object
            storm = Storm(number=storm_num, rain_data=storm_rain_data) # Using Storm class
            self.storms.append(storm)

            # Progress Update
            if storm_num % 1000 == 0:
                logger.info(f"    Created {storm_num:,} storms...")
        logger.info(f"    Created {storm_num:,} storms...")

    ### Access Methods

    def get_storm(self, storm_number):
        # Get a specific storm by its number
        index = storm_number - 1

        if 0 <= index < len(self.storms):
            return self.storms[index]
        else:
            print(f"Storm {storm_number} not found")
            return None
        
    def get_largest_storms(self, n=10, by='mean_gauge_rain'):
        # Get the N largest storms
        sorted_storms = sorted(
            self.storms,
            key=lambda storm: getattr(storm, by),
            reverse = True
        )
        return sorted_storms[:n]

    def get_storms_by_year(self, year=None):
        if not year:
            logger.error("You must provide a year.")
            return
        storms_in_year = [storm for storm in self.storms if storm.start_time.year == year]
        return storms_in_year
    
    ### Export Methods

    def to_dataframe(self):
        # Convert all storms to a DataFrame
        # Returns a dataframe with one row per storm

        if not self.storms:
            logger.error("No storms found. Run find_storms() first.")
            return None
        
        # Use each storm's to_dict() method
        data = [storm.to_dict() for storm in self.storms]

        return pd.DataFrame(data)
    
    def to_csv(self, filepath):
        # Save storm data to csv

        df = self.to_dataframe()
        filename = self.generate_filename(filepath, dl_csv=True)
        if df is not None:
            df.to_csv(filename, index=False)
            logger.info(f"Saved {len(df)} storms to {filename}")
    
    def generate_filename(self, output_dir=None, dl_csv=False, dl_sql=False):

        download_date = datetime.now().strftime("%Y-%m-%d")

        if dl_csv:
            filename = f"storm_catalog_downloaded_{download_date}.csv"
        elif dl_sql:
            filename = f"precipitation_15min_downloaded_{download_date}.db"
        else:
            raise ValueError("Must specify either dl_csv=True or dl_sql=True")

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            return os.path.join(output_dir, filename)
        
        return filename

    def summary(self):
        
        if not self.storms:
            print("No storms found. Run find_storms() first.")
            return
        
        print(f"\n{'='*50}")
        print("STORM CATALOG SUMMARY")
        print(f"{'='*50}")
        
        print(f"\nParameters:")
        print(f"  Min gauges: {self.min_gauges}")
        print(f"  Inter-event hours: {self.interevent_hours}")
        
        print(f"\nStorms:")
        print(f"  Total: {self.n_storms:,}")
        print(f"  First: {self.storms[0].start_time.date()}")
        print(f"  Last: {self.storms[-1].start_time.date()}")
        
        # Duration stats
        durations = [s.duration_hours for s in self.storms]
        print(f"\nDuration (hours):")
        print(f"  Min: {min(durations):.1f}")
        print(f"  Max: {max(durations):.1f}")
        print(f"  Mean: {sum(durations)/len(durations):.1f}")
        
        # Rainfall stats
        rainfalls = [s.mean_gauge_rain for s in self.storms]
        print(f"\nMean Rainfall (inches):")
        print(f"  Min: {min(rainfalls):.3f}")
        print(f"  Max: {max(rainfalls):.3f}")
        print(f"  Mean: {sum(rainfalls)/len(rainfalls):.3f}")

        
