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
        self.gauge_names = list(rain_data.columns)

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
    def mean_gauge_rain(self):
        return self.gauge_totals.mean()
    
    @property
    def max_gauge_rain(self):
        return self.gauge_totals.max()
    
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
    
    @property
    def pct_data_missing(self):
        # Percentage of all possible readings that are missing
        # Total possible 
        total_cells = self.n_timestamps * self.n_gauges
        missing_cells = self.rain_data.isna().sum().sum()
        return (missing_cells / total_cells) * 100
    
    # Gauge Activity Properties

    @property
    def avg_gauges_raining(self):
        # Average number of gauges recording rain (>0) per timestamp
        raining_per_ts = (self.rain_data > 0).sum(axis = 1)
        return raining_per_ts.mean()
    
    @property
    def max_gauges_raining(self):
        # Max number of gauges recording rain at any single timestamp
        raining_per_ts = (self.rain_data > 0).sum(axis = 1)
        return raining_per_ts.max()
    
    @property
    def min_gauges_raining(self):
        # Min number of gauges recording rain at any single timestamp
        raining_per_ts = (self.rain_data > 0).sum(axis = 1)
        return raining_per_ts.min()
    
    @property
    def mean_intensity(self):
        # Average rainfall rate (inches per hour)
        if self.duration_hours == 0:
            return 0
        return self.mean_gauge_rain / self.duration_hours
    
    # Outputs
    
    def to_dict(self):
        # Convert storm to dictionary (For creating dataframes)

        # storms = [storm1, storm2, storm3]
        # df = pd.DataFrame([s.to_dict() for s in storms])
        return {
            'storm_number': self.number,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'duration_hours': self.duration_hours,
            'n_timestamps': self.n_timestamps,
            'total_rain': round(self.total_rain, 3),
            'max_gauge_rain': round(self.max_gauge_rain, 3),
            'mean_gauge_rain': round(self.mean_gauge_rain, 3),
            'wettest_gauge': self.wettest_gauge,
            'peak_intensity': round(self.peak_intensity, 3),
            'avg_gauges_missing': round(self.avg_gauges_missing, 1),
            'pct_data_missing': round(self.pct_data_missing, 1),
            'avg_gauges_raining': round(self.avg_gauges_raining, 1),
            'max_gauges_raining': self.max_gauges_raining,
            'min_gauges_raining': self.min_gauges_raining,
        }
    
    def summary(self):
        # Print a readable summary of the storm
        print(f"\n{'='*50}")
        print(f"STORM {self.number}")
        print(f"\n{'='*50}")
        print(f"Start: {self.start_time}")
        print(f"End: {self.end_time}")
        print(f"Duration: {self.duration_hours} hours")
        print("\nRainfall")
        print(f"  Total (all gauges): {self.total_rain}")
        print(f"  Wettest Gauge: {self.wettest_gauge}")
        print(f"  Peak Intensity: {self.peak_intensity}")
        print("\nData Quality")
        print(f"  Average Gauges Missing: {self.avg_gauges_missing} of {self.n_gauges}")
        print(f"  % data missing: {self.pct_data_missing:.1f}")

    def __repr__(self):
        return (
            f"Storm({self.number}: "
            f"{self.start_time.strftime('%Y-%m-%d')}, "
            f"{self.duration_hours:.1f}hrs,"
            f"{self.total_rain:.2f} rain)"
        )

