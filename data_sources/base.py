"""
Base classes for data sources.

This module defines the format  all data sources must follow
"""

from abc import ABC, abstractmethod             # Allows us to templace classes that cant be used directly
from dataclasses import dataclass, field        # Automatically creates boilerplate code
from datetime import datetime
from typing import List, Optional, Dict, Any
import pandas as pd
import logging

# =========================================================
# DATA CLASSES - Standardized Data Structure
# =========================================================

@dataclass
class DataPoint:
    """
    Dataclass automatically creates __init__, __repr__, and __eq__ methods
    A single data measurement
    All sources must convert their data to this structure
    """
    timestamp: datetime
    value: float
    location_id: str
    parameter: str
    unit: str
    source: str # Which API this came from (for tracking)
    quality_flag: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        # Convert to dictionary, useful for creating dataframes
        return {
            'timestamp': self.timestamp,
            'value': self.value,
            'location': self.location_id,
            'parameter': self.parameter,
            'unit': self.unit,
            'source': self.source,
            'quality_flag': self.quality_flag
        }
    
@dataclass
class SiteInfo:
    """
    Information about a monitoring site/location
    
    Different APIs call these different things, we standardize to site
    """
    # Required fields
    site_id: str        # Unique id
    name: str           # Human readable name

    # Location (not all apis provide it)
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Source tracking
    source: str = "" # Which api this came from

    # Optional fields that may not be provided
    state: Optional[str] = None
    county: Optional[str] = None
    elevation_ft: Optional[float] = None

    # Catch all for extras
    # (Use default_factory= for all mutable defaults (list, dict, set)
    metadata: Dict[str, Any] = field(default_factory=dict) # Creates a unique object each call. 
    

    def __repr__(self):
        """
        A nice string representation. 
        Default dataclass __repr__ includes all fields, this is shorter
        """
        return f"SiteInfo({self.site_id}: {self.name})"
    
# =========================================================
# ABSTRACT BASE CLASS
# =========================================================

class BaseDataSource(ABC):
    """
    Abstract base class for all data sources.

    ABC is:
    - A template/blueprint for other classes
    - Methods marked @abstractmethod MUST be implemented by child classes
    - You cannot create an instance of BaseDataSource directly

    All this for:
    - Consistency: All data sources have the same methods
    - Reliability: Python enforces this like a contract
    - Documentation: Shows what methods are required
    - Flexibility: Easy to add new sources

    Example of what happens:
    
        class MySource(BaseDataSource):
            pass  # Forgot to implement required methods!
        
        source = MySource()  # TypeError: Can't instantiate abstract class!
    """
    def __init__(self):
        """Initialize the data source"""
        # Each source gets its own logger
        self.logger = logging.getLogger(self.__class__.__name__)

        # Simple cache to avoid repeated API calls
        self._cache: Dict[str, Any] = {}
        self._cache_enabled = True

    # ---------------------------------------------------------
    # ABSTRACT PROPERTIES - must be defined by each source
    # ---------------------------------------------------------

    @property
    @abstractmethod
    def source_name(self) -> str:
        """
        Return the name of this data source.
        Used to identify where data originated
        """
        pass
    
    @property
    @abstractmethod
    def base_url(self) -> str:
        """
        Return the base URL for this API
        """
        pass

    # ---------------------------------------------------------
    # ABSTRACT METHODS - must be implemented by each source
    # ---------------------------------------------------------

    @abstractmethod
    def get_sites(
        self,
        state: Optional[str] = None,
        bbox: Optional[tuple] = None,
        site_ids: Optional[List[str]] = None,
        **kwargs
    ) -> List[SiteInfo]:
        """
        get available monitoring sites

        state: two letter state code
        bbox: bounding box (minlon, minlat, maxlon, maxlat)
        site_ids: list of specific site ids to retrieve (if known)
        **kwargs: source specific parameters - allows flexibility

        returns a list of SiteInfo objects
        """
        pass
    
    @abstractmethod
    def get_data(
        self,
        site_ids: List[str],
        parameter: str,
        start_date: datetime,
        end_date: datetime,
        **kwargs
    ) -> List[DataPoint]:
        """
        Get time series data
        
        This is the main data retrieval method, each source must convert its native format
        to standard DataPoint format.
        
        site_ids: list of site identifiers
        parameter: what to measure (eg. "precipitation", "Discharge")
        start_date: Start of data period
        end_date: End of data period
        **kwargs: Source specific parameters
        
        returns a list of DataPoint objects"""
        pass

    @abstractmethod
    def get_available_parameters(self, site_id: str) -> List[Dict[str, str]]:
        """
        Get list of available parameters at a site.
        
        site_id: Site identifier
        
        returns a list of dicts with 'code', 'name', 'unit' keys
        """
        pass

    # ---------------------------------------------------------
    # CONCRETE METHODS - Shared by all sources (not abstract)
    # ---------------------------------------------------------

    def to_dataframe(self, data_points: List[DataPoint]) -> pd.DataFrame:
        """
        Convert list of DataPoints to a pandas Dataframe
        
        This works for ALL source bcause they all produce DataPoints
        
        data_points: List of DataPoint objects
        
        returns a dataframe with standardized columns
        """
        if not data_points:
            self.logger.warning("No data points to convert")
            return pd.DataFrame()
        
        # Use each DataPoint's to_dict method
        data = [dp.to_dict() for dp in data_points]
        df = pd.DataFrame(data)

        # Ensure timestamp is datetime
        df['timestamp'] = pd.to_datetime(df['timestamp'])

        # Sort by timestamp
        df = df.sort_values('timestamp').reset_index(drop=True)

        self.logger.info(f"Created DataFrame with {len(df):,} rows")

        return df
    
    def clear_cache(self):
        """Clear the API response cache"""
        self._cache.clear()
        self.logger.debug("Cache cleared")

    def _get_cached(self, key: str) -> Optional[Any]:
        """Get a value from cache if it exists"""
        if self._cache_enabled and key in self._cache:
            self.logger.debug(f"Cache hit: {key[:50]}...")
            return self._cache[key]
        return None
    
    def _set_cached(self, key: str, value: Any) -> None:
        """Store a value in cache"""
        if self._cache_enabled:
            self._cache[key] = value