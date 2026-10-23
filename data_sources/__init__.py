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

    # Or go through the registry (what the GUI will use):
    from data_sources import list_sources, create_source
    for desc in list_sources():
        print(desc.display_name)
    source = create_source("usgs")
"""

from .aquarius import AquariusDataSource
from .base import BaseDataSource, DataPoint, SiteInfo
from .registry import (
    SourceDescriptor,
    SourceOption,
    create_source,
    get_descriptor,
    list_sources,
)
from .snotel import SNOTELDataSource
from .usgs import USGSDataSource

__all__ = [
    "AquariusDataSource",
    "BaseDataSource",
    "DataPoint",
    "SiteInfo",
    "SourceDescriptor",
    "SourceOption",
    "SNOTELDataSource",
    "USGSDataSource",
    "create_source",
    "get_descriptor",
    "list_sources",
]
