"""
Data Sources Package

This package provides a unified interface for downloading
environmental data from multiple sources.

Usage:
    from data_sources import USGSDataSource, AquariusDataSource

    usgs = USGSDataSource()
    sites = usgs.get_sites(state='OR')

    aquarius = AquariusDataSource()
    catalogue = aquarius.available_datasets_dataframe()
"""

from .aquarius import AquariusDataSource
from .base import BaseDataSource, DataPoint, SiteInfo
from .snotel import SNOTELDataSource
from .usgs import USGSDataSource

__all__ = [
    "AquariusDataSource",
    "BaseDataSource",
    "DataPoint",
    "SiteInfo",
    "SNOTELDataSource",
    "USGSDataSource",
]
