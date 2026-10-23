"""Map view for discovered sites (Steps 5a / 5b).

5a: Folium pins in a MarkerCluster (zoom/click cluster to expand).
5b: Click a pin -> that site_id is added to the discovery
    multiselect (via session_state).

Sites missing coordinates are skipped (Aquarius can have
locations with no map pin -- expected).
"""

from typing import Dict, List, Optional, Sequence, Set, Tuple

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

# How close a click must be to a pin (degrees) to count as
# that site. Streamlit-folium usually returns the marker's
# exact lat/lon, so this is just float-noise insurance.
_CLICK_TOL_DEG = 1e-5


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

    Tooltip is the bare site_id so click handling can read it
    without parsing (SNOTEL ids contain colons).
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
            # Bare id -- used by click-to-select. Don't put a
            # colon here; SNOTEL triplets already have them.
            tooltip=str(site.site_id),
        ).add_to(cluster)

    fmap.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])
    return fmap, stats


def site_id_from_map_click(
    map_data: dict,
    sites: Sequence[SiteInfo],
    known_ids: Set[str],
) -> Optional[str]:
    """Resolve a st_folium click payload to a site_id.

    Prefer the tooltip (we set it to site_id). Fall back to
    nearest pin by lat/lon when tooltip isn't returned (can
    happen with some cluster interactions).
    """
    if not map_data:
        return None

    tooltip = map_data.get("last_object_clicked_tooltip")
    if isinstance(tooltip, str):
        tip = tooltip.strip()
        if tip in known_ids:
            return tip

    clicked = map_data.get("last_object_clicked")
    if not isinstance(clicked, dict):
        return None
    lat = clicked.get("lat")
    lon = clicked.get("lng")
    if lat is None or lon is None:
        return None
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return None

    best_id: Optional[str] = None
    best_dist = _CLICK_TOL_DEG ** 2
    for site in sites:
        if site.latitude is None or site.longitude is None:
            continue
        if site.site_id not in known_ids:
            continue
        dlat = float(site.latitude) - lat_f
        dlon = float(site.longitude) - lon_f
        dist = dlat * dlat + dlon * dlon
        if dist <= best_dist:
            best_dist = dist
            best_id = site.site_id
    return best_id


def render_sites_map(
    sites: Sequence[SiteInfo],
    source_key: str,
    known_ids: Optional[Set[str]] = None,
    map_key: Optional[str] = None,
) -> Optional[str]:
    """Show the map; return a newly clicked site_id, or None.

    "Newly" means this click token differs from the last one we
    applied -- so a stale last_object_clicked won't keep
    re-adding a site the user removed from the multiselect.

    map_key: optional streamlit-folium widget key. Discovery
    passes a hash of the filtered id list so include/exclude
    changes rebuild the map instead of showing stale pins.
    """
    st.subheader("Map")
    st.caption(
        "Click a pin to add that site to **Sites to inspect** "
        "below. Nearby pins group into clusters — zoom in or "
        "click a cluster to expand. Colors: "
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
        return None

    ids = known_ids if known_ids is not None else {s.site_id for s in sites}
    widget_key = map_key or f"sites_map_{source_key}"

    # Ask streamlit-folium for click payloads (tooltip + lat/lng).
    map_data = st_folium(
        fmap,
        key=widget_key,
        height=480,
        use_container_width=True,
        returned_objects=[
            "last_object_clicked",
            "last_object_clicked_tooltip",
        ],
    )

    st.caption(
        f"{stats['plotted']:,} site(s) on the map (clustered). "
        "Click a pin to select it."
    )

    site_id = site_id_from_map_click(map_data or {}, sites, ids)
    if not site_id:
        return None

    clicked = (map_data or {}).get("last_object_clicked") or {}
    token = (
        site_id,
        clicked.get("lat"),
        clicked.get("lng"),
        (map_data or {}).get("last_object_clicked_tooltip"),
    )
    token_key = f"map_click_token_{source_key}"
    if st.session_state.get(token_key) == token:
        return None
    st.session_state[token_key] = token
    return site_id
