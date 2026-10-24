"""USGS StreamStats helpers for the Tributary Toolkit.

Basins / snap / attributes — not time-series DataPoints.
Keep this package separate from data_sources/ on purpose.
"""

from .client import StreamStatsClient

__all__ = ["StreamStatsClient"]
