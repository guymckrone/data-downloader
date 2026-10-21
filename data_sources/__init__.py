"""
Data Sources Package

This package provides a unified interface for downloading
environmental data from multiple sources.

Usage:
    from data_sources import USGSDataSource

    usgs = USGSDataSource()
    sites = usgs.get_sites(state='OR')
"""

from .base import BaseDataSource, DataPoint, SiteInfo
from .usgs import USGSDataSource

__all__ = [
    "BaseDataSource",
    "DataPoint",
    "SiteInfo",
    "USGSDataSource",
]
