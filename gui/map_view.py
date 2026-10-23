"""Map view for discovered sites (Step 5a).

Pins + clustering -- click-to-select / draw-bbox / shapefile
come later. I build a Folium map from SiteInfo lat/lon and
hand it to streamlit-folium. Sites missing coordinates are
skipped (Aquarius has locations with no map pin -- expected).

MarkerCluster groups nearby pins into a count bubble; zoom
in (or click the bubble) and they split apart. That lets me
plot a full Oregon USGS pull without capping the list.
"""

from typing import Dict, List, Optional, Sequence, Tuple

import folium
import streamlit as st
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

from data_sources import SiteInfo

# Distinct colors per source_name (what SiteInfo.source carries).
SOURCE_COLORS: Dict[str, str] = {
    "USGS": "#1f77b4",      # blue
    "Aquarius": "#2ca02c",  # green
    "SNOTEL": "#d62728",    # red
}
_DEFAULT_COLOR = "#7f7f7f"
_DEFAULT_ZOOM = 6


def _mappable_sites(
    sites: Sequence[SiteInfo],
) -> Tuple[List[SiteInfo], int]:
    """Return (sites with lat/lon, count skipped for missing coords)."""
    mappable: List[SiteInfo] = []
    skipped = 0
    for site in sites:
        if site.latitude is None or site.longitude is None:
            skipped += 1
            continue
        try:
            lat = float(site.latitude)
            lon = float(site.longitude)
        except (TypeError, ValueError):
            skipped += 1
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            skipped += 1
            continue
        mappable.append(site)
    return mappable, skipped


def build_sites_map(
    sites: Sequence[SiteInfo],
) -> Tuple[Optional[folium.Map], dict]:
    """Build a Folium map of site pins inside a MarkerCluster.

    Returns (map_or_None, stats) with plotted / skipped_no_coords.
    """
    mappable, skipped = _mappable_sites(sites)
    stats = {
        "plotted": len(mappable),
        "skipped_no_coords": skipped,
    }
    if not mappable:
        return None, stats

    lats = [float(s.latitude) for s in mappable]
    lons = [float(s.longitude) for s in mappable]
    center = (sum(lats) / len(lats), sum(lons) / len(lons))

    fmap = folium.Map(location=center, zoom_start=_DEFAULT_ZOOM)
    # disableClusteringAtZoom=None keeps clustering until you
    # zoom far enough that points separate; click a cluster to
    # spiderfy overlapping pins at the same spot.
    cluster = MarkerCluster(
        name="Sites",
        options={
            "showCoverageOnHover": False,
            "maxClusterRadius": 50,
        },
    ).add_to(fmap)

    for site in mappable:
        color = SOURCE_COLORS.get(site.source or "", _DEFAULT_COLOR)
        folium.CircleMarker(
            location=(float(site.latitude), float(site.longitude)),
            radius=5,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.85,
            weight=1,
            popup=folium.Popup(
                f"<b>{site.site_id}</b><br>{site.name}<br>"
                f"source: {site.source or '?'}",
                max_width=280,
            ),
            tooltip=f"{site.site_id}: {site.name}",
        ).add_to(cluster)

    fmap.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])
    return fmap, stats


def render_sites_map(sites: Sequence[SiteInfo], source_key: str) -> None:
    """Show the clustered sites map inside Streamlit."""
    st.subheader("Map")
    st.caption(
        "All sites with lat/lon. Nearby pins group into numbered "
        "clusters — zoom in or click a cluster to expand. "
        "Selecting a site from the map comes in 5b. Colors: "
        "USGS blue · Aquarius green · SNOTEL red."
    )

    fmap, stats = build_sites_map(sites)

    if stats["skipped_no_coords"]:
        st.caption(
            f"Skipped {stats['skipped_no_coords']:,} site(s) "
            "with no / invalid coordinates."
        )

    if fmap is None:
        st.info("No sites with coordinates to plot.")
        return

    # returned_objects=[] -- no click/draw events yet; collecting
    # them would force heavier reruns on every pan.
    st_folium(
        fmap,
        key=f"sites_map_{source_key}",
        height=480,
        use_container_width=True,
        returned_objects=[],
    )
    st.caption(
        f"{stats['plotted']:,} site(s) on the map (clustered)."
    )
