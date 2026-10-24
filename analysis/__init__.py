"""
Rainfall / storm analysis pipeline.

Consumes precipitation SQLite DBs produced by the Aquarius (or other)
downloaders. Separate from Data Download and StreamStats toolkit tools.

Run entry points from the repo root, for example:

    python -m analysis.regional_storm_analysis
    python -m analysis.gauge_analysis
"""
