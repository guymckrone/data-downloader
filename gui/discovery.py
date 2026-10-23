"""Discovery UI: find sites, then list available parameters.

I only hit the APIs when the user clicks a button, so
Streamlit reruns don't burn USGS quota or re-pull SNOTEL.

After Find sites, include / exclude / search filters narrow
the loaded list in-memory (table + map + site picker) -- no
extra API calls. Same filters work for every source.
"""

import hashlib
from typing import List, Optional, Sequence, Tuple

import pandas as pd
import streamlit as st

from data_sources import BaseDataSource, SiteInfo

BBox = Tuple[float, float, float, float]


def sites_to_dataframe(sites: List[SiteInfo]) -> pd.DataFrame:
    """Flatten SiteInfo rows into a table for st.dataframe.

    Pull agency_code / site_type out of metadata when present
    -- for USGS, OR004-* sites are real locations but often
    have zero downloadable series, and that column makes it
    obvious why parameters came back empty.
    """
    columns = [
        "site_id", "name", "agency_code", "site_type",
        "latitude", "longitude", "state", "county",
        "elevation_ft", "source",
    ]
    if not sites:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(
        [
            {
                "site_id": s.site_id,
                "name": s.name,
                "agency_code": (s.metadata or {}).get("agency_code"),
                "site_type": (s.metadata or {}).get("site_type")
                or (s.metadata or {}).get("site_type_code"),
                "latitude": s.latitude,
                "longitude": s.longitude,
                "state": s.state,
                "county": s.county,
                "elevation_ft": s.elevation_ft,
                "source": s.source,
            }
            for s in sites
        ],
        columns=columns,
    )


def parse_site_ids(raw: str) -> Optional[List[str]]:
    """Split a text box into site id strings.

    Commas, whitespace, or newlines all work. Empty -> None
    so get_sites can treat "no filter" vs "empty list".
    IDs stay strings (leading zeros are real).
    """
    if not raw or not raw.strip():
        return None
    parts: List[str] = []
    for chunk in raw.replace(",", " ").split():
        token = chunk.strip()
        if token:
            parts.append(token)
    return parts or None


def parse_patterns(raw: str) -> List[str]:
    """Split include/exclude text into substrings.

    Comma or newline separated so a pattern can contain spaces
    ("Johnson Creek"). Empty / whitespace-only -> [].
    """
    if not raw or not raw.strip():
        return []
    parts: List[str] = []
    for chunk in raw.replace("\n", ",").split(","):
        token = chunk.strip()
        if token:
            parts.append(token)
    return parts


def _site_haystack(site: SiteInfo, match_on: str) -> str:
    """Text we match include/exclude/search against."""
    sid = (site.site_id or "").lower()
    name = (site.name or "").lower()
    if match_on == "id":
        return sid
    if match_on == "name":
        return name
    return f"{sid} {name}"


def filter_sites(
    sites: Sequence[SiteInfo],
    include: Sequence[str],
    exclude: Sequence[str],
    search: str = "",
    match_on: str = "id_or_name",
) -> List[SiteInfo]:
    """Narrow a loaded site list in memory (no API calls).

    include: if non-empty, keep sites matching ANY pattern
    exclude: drop sites matching ANY pattern (after include)
    search: extra live "contains" filter (AND)
    match_on: "id" | "name" | "id_or_name"
    Patterns are case-insensitive substrings.
    """
    include_l = [p.lower() for p in include]
    exclude_l = [p.lower() for p in exclude]
    search_l = (search or "").strip().lower()

    out: List[SiteInfo] = []
    for site in sites:
        text = _site_haystack(site, match_on)
        if include_l and not any(p in text for p in include_l):
            continue
        if exclude_l and any(p in text for p in exclude_l):
            continue
        if search_l and search_l not in text:
            continue
        out.append(site)
    return out


def clear_discovery_state() -> None:
    """Drop cached discovery results (call when source changes).

    Also clears download results -- they were built from the
    old parameters catalogue -- and map/multiselect session
    keys so a stale pin-click doesn't re-select old ids.
    """
    for key in (
        "discovery_sites",
        "discovery_sites_df",
        "discovery_params_df",
        "discovery_error",
    ):
        st.session_state.pop(key, None)
    # Widget / map keys are per source_key -- wipe any of them.
    for key in list(st.session_state.keys()):
        if (
            key.startswith("discovery_select_")
            or key.startswith("discovery_ids_sig_")
            or key.startswith("discovery_full_sig_")
            or key.startswith("map_click_token_")
            or key.startswith("sites_map_")
            or key.startswith("bbox_draw_map_")
            or key.startswith("drawn_bbox_")
        ):
            st.session_state.pop(key, None)
    # Local import avoids a circular import at module load
    # (download.py doesn't import discovery today, but I don't
    # want a future one to bite me).
    from gui.download import clear_download_state
    clear_download_state()


def _usgs_site_kwargs(agency_code: str, site_type_code: str) -> dict:
    """Optional kwargs for USGS get_sites()."""
    kwargs = {}
    if agency_code.strip():
        kwargs["agency_code"] = agency_code.strip()
    if site_type_code.strip():
        kwargs["site_type_code"] = site_type_code.strip()
    return kwargs


def _store_discovered_sites(sites: List[SiteInfo]) -> None:
    """Write a fresh get_sites() result into session_state."""
    st.session_state["discovery_sites"] = sites
    st.session_state["discovery_sites_df"] = sites_to_dataframe(sites)
    st.session_state.pop("discovery_params_df", None)
    st.session_state.pop("discovery_error", None)
    from gui.download import clear_download_state
    clear_download_state()


def _run_get_sites(
    source: BaseDataSource,
    source_key: str,
    *,
    state: Optional[str],
    site_ids: Optional[List[str]],
    agency_code: str,
    site_type_code: str,
    bbox: Optional[BBox] = None,
) -> None:
    """Call get_sites and store results, or set discovery_error."""
    site_kwargs = {}
    if source_key == "usgs":
        site_kwargs.update(_usgs_site_kwargs(agency_code, site_type_code))
    try:
        label = "get_sites(bbox=...)" if bbox is not None else "get_sites()"
        with st.spinner(f"Calling {label}..."):
            sites = source.get_sites(
                state=state,
                site_ids=site_ids,
                bbox=bbox,
                **site_kwargs,
            )
        _store_discovered_sites(sites)
    except Exception as exc:
        clear_discovery_state()
        st.session_state["discovery_error"] = f"{type(exc).__name__}: {exc}"


def render_discovery(source: BaseDataSource, source_key: str) -> None:
    """Sites table + parameters table for the active source."""
    st.header("Discovery")
    st.caption(
        "Find sites, then inspect what each one measures. "
        "Use the parameters table below to pick downloads."
    )

    # ---- filters ----
    col_state, col_ids = st.columns(2)
    with col_state:
        # Default OR: Oregon is where most of my test sites live.
        # Aquarius ignores non-OR; USGS/SNOTEL need a state or
        # IDs or they'll try to pull a huge catalogue.
        state = st.text_input(
            "State",
            value="OR",
            key=f"discovery_state_{source_key}",
            help=(
                "Two-letter code (OR). Leave blank only if you "
                "pass site IDs below. USGS Oregon has thousands "
                "of sites -- prefer a state + optional IDs."
            ),
        )
    with col_ids:
        site_ids_raw = st.text_input(
            "Site IDs (optional)",
            value="",
            key=f"discovery_ids_{source_key}",
            help=(
                "Comma or space separated. Examples: "
                "14211400 | HYDRA-1 | 302:OR:SNTL"
            ),
        )

    # USGS-only discovery kwargs (passed straight into get_sites)
    agency_code = ""
    site_type_code = ""
    if source_key == "usgs":
        col_agency, col_type = st.columns(2)
        with col_agency:
            # Default USGS: a bare OR pull mixes in OR004/etc.
            # agency locations that often have zero series in the
            # continuous/daily API -- looks like a bug in the GUI.
            agency_code = st.text_input(
                "Agency code",
                value="USGS",
                key=f"discovery_agency_{source_key}",
                help=(
                    "USGS = federal gages with downloadable series. "
                    "Clear this to include other agencies (OR004, …). "
                    "Many non-USGS locations have no time series here."
                ),
            )
        with col_type:
            site_type_code = st.text_input(
                "Site type code",
                value="ST",
                key=f"discovery_site_type_{source_key}",
                help=(
                    "ST = stream. Clear for all types. "
                    "See USGS site-type codes for others."
                ),
            )
        st.caption(
            "Tip: Johnson Creek is 14211400. "
            "OR004-* ids are other agencies — often no parameters."
        )
    elif source_key == "snotel":
        st.caption(
            "Tip: Aneroid Lake #2 is 302:OR:SNTL. "
            "State helps a lot -- nationwide SNOTEL is slow."
        )
    elif source_key == "aquarius":
        st.caption(
            "Tip: HYDRA-1 is a good precip test location. "
            "After Find sites, use Include=`HYDRA` to keep only "
            "Hydra gauges. Portal is Portland-only; some "
            "datasets have no map pin."
        )

    state_arg = state.strip() or None
    ids_arg = parse_site_ids(site_ids_raw)

    find = st.button("Find sites", type="primary", key=f"find_{source_key}")

    if find:
        if source_key in ("usgs", "snotel") and not state_arg and not ids_arg:
            clear_discovery_state()
            st.session_state["discovery_error"] = (
                "Give a state and/or site IDs first — "
                "an unfiltered pull is huge/slow for this source. "
                "Or draw a box below and use Find sites in box."
            )
        else:
            _run_get_sites(
                source,
                source_key,
                state=state_arg,
                site_ids=ids_arg,
                agency_code=agency_code,
                site_type_code=site_type_code,
                bbox=None,
            )

    # ---- 5c: draw bbox -> get_sites(bbox=...) ----
    with st.expander("Find by map area (draw a box)", expanded=False):
        from gui.map_view import render_bbox_draw_map
        drawn_bbox = render_bbox_draw_map(source_key)
        find_box = st.button(
            "Find sites in box",
            key=f"find_bbox_{source_key}",
        )
        if find_box:
            bbox = drawn_bbox or st.session_state.get(
                f"drawn_bbox_{source_key}"
            )
            if not bbox:
                st.session_state["discovery_error"] = (
                    "Draw a rectangle on the map first, then click "
                    "Find sites in box."
                )
            elif source_key == "snotel" and not state_arg:
                st.session_state["discovery_error"] = (
                    "SNOTEL bbox search still needs a State above "
                    "(e.g. OR) so it doesn't pull every station "
                    "nationwide before filtering."
                )
            else:
                # Site IDs don't apply to a box search -- bbox is
                # the spatial filter. State still helps SNOTEL /
                # Aquarius; USGS can query on bbox alone.
                _run_get_sites(
                    source,
                    source_key,
                    state=state_arg,
                    site_ids=None,
                    agency_code=agency_code,
                    site_type_code=site_type_code,
                    bbox=bbox,
                )

    err = st.session_state.get("discovery_error")
    if err:
        st.error(err)

    all_sites: List[SiteInfo] = st.session_state.get("discovery_sites") or []
    sites_df = st.session_state.get("discovery_sites_df")

    if sites_df is None:
        st.info(
            "Click **Find sites** (filters above) or "
            "**Find sites in box** (draw a rectangle) to load a table."
        )
        return

    # ---- post-filters (in-memory; no extra API calls) ----
    st.subheader(f"Sites ({len(all_sites):,} loaded)")
    if all_sites:
        st.caption(
            "Narrow the loaded list without re-fetching. "
            "Include / exclude are comma-separated substrings "
            "(e.g. `HYDRA` or `14211`). Search filters as you type. "
            "Table, map, and site picker all use the same result."
        )
        col_inc, col_exc = st.columns(2)
        with col_inc:
            include_raw = st.text_input(
                "Include (contains any)",
                value="",
                key=f"discovery_include_{source_key}",
                help=(
                    "Keep sites whose id/name contains any of these. "
                    "Empty = keep all. Example: HYDRA"
                ),
            )
        with col_exc:
            exclude_raw = st.text_input(
                "Exclude (contains any)",
                value="",
                key=f"discovery_exclude_{source_key}",
                help=(
                    "Drop sites matching any of these, after include. "
                    "Example: HYDRA  or  Forecast"
                ),
            )
        col_search, col_match = st.columns([2, 1])
        with col_search:
            search_raw = st.text_input(
                "Search",
                value="",
                key=f"discovery_search_{source_key}",
                help="Live contains-filter on top of include/exclude.",
            )
        with col_match:
            match_on = st.selectbox(
                "Match on",
                options=["id_or_name", "id", "name"],
                format_func=lambda v: {
                    "id_or_name": "ID or name",
                    "id": "Site ID",
                    "name": "Name",
                }[v],
                key=f"discovery_match_{source_key}",
            )

        sites = filter_sites(
            all_sites,
            include=parse_patterns(include_raw),
            exclude=parse_patterns(exclude_raw),
            search=search_raw,
            match_on=match_on,
        )
        filtered_df = sites_to_dataframe(sites)
        st.caption(
            f"Showing {len(sites):,} of {len(all_sites):,} "
            "after include / exclude / search."
        )
        st.dataframe(filtered_df, use_container_width=True, hide_index=True)
    else:
        sites = []
        st.dataframe(sites_df, use_container_width=True, hide_index=True)

    if not all_sites:
        st.warning("No sites matched those Find-sites filters.")
        return
    if not sites:
        st.warning(
            "No sites left after include / exclude / search. "
            "Clear or loosen those filters."
        )
        return

    # ---- map + site selection (5a pins, 5b click-to-select) ----
    id_list = [s.site_id for s in sites]
    select_key = f"discovery_select_{source_key}"
    sig_key = f"discovery_ids_sig_{source_key}"
    # Signature is the *filtered* id list: include/exclude changes
    # sanitize the multiselect; a brand-new Find sites list resets
    # to the first visible site.
    sites_sig = tuple(id_list)
    full_sig_key = f"discovery_full_sig_{source_key}"
    full_sig = tuple(s.site_id for s in all_sites)
    if st.session_state.get(full_sig_key) != full_sig:
        st.session_state[full_sig_key] = full_sig
        st.session_state[sig_key] = sites_sig
        st.session_state[select_key] = id_list[:1] if id_list else []
    elif st.session_state.get(sig_key) != sites_sig:
        st.session_state[sig_key] = sites_sig
        # Keep selections that are still visible; if none left,
        # fall back to the first filtered site.
        kept = [
            i for i in st.session_state.get(select_key, [])
            if i in id_list
        ]
        st.session_state[select_key] = (
            kept if kept else (id_list[:1] if id_list else [])
        )
    else:
        current = [
            i for i in st.session_state.get(select_key, [])
            if i in id_list
        ]
        st.session_state[select_key] = current

    # New map component key when the filtered set changes so
    # streamlit-folium doesn't keep showing a stale pin set.
    map_sig = hashlib.md5(
        ",".join(id_list).encode("utf-8")
    ).hexdigest()[:12]

    from gui.map_view import render_sites_map
    clicked_id = render_sites_map(
        sites,
        source_key,
        known_ids=set(id_list),
        map_key=f"sites_map_{source_key}_{map_sig}",
    )
    if clicked_id and clicked_id in id_list:
        chosen = list(st.session_state.get(select_key, []))
        if clicked_id not in chosen:
            st.session_state[select_key] = chosen + [clicked_id]
            st.toast(f"Added {clicked_id} from map")

    st.subheader("Available parameters")
    selected = st.multiselect(
        "Sites to inspect",
        options=id_list,
        key=select_key,
        help=(
            "Pick from the filtered list or click pins on the map. "
            "One catalogue row per real series/element/dataset."
        ),
    )
    load_params = st.button(
        "Show available parameters",
        key=f"params_{source_key}",
    )

    if load_params:
        if not selected:
            st.warning("Pick at least one site.")
        else:
            try:
                with st.spinner("Calling available_parameters_dataframe()..."):
                    params_df = source.available_parameters_dataframe(selected)
                st.session_state["discovery_params_df"] = params_df
                from gui.download import clear_download_state
                clear_download_state()
            except Exception as exc:
                st.session_state.pop("discovery_params_df", None)
                st.error(f"{type(exc).__name__}: {exc}")

    params_df = st.session_state.get("discovery_params_df")
    if params_df is not None:
        st.caption(f"{len(params_df):,} series/element/dataset row(s)")
        st.dataframe(params_df, use_container_width=True, hide_index=True)
        if params_df.empty:
            if source_key == "usgs":
                st.warning(
                    "No time series in the USGS continuous/daily API "
                    "for the selected site(s). That is a real empty "
                    "answer (not a GUI bug) — common for non-USGS "
                    "agency ids like OR004-… or discontinued sites. "
                    "Re-find with Agency code **USGS**, or try site "
                    "id **14211400** (Johnson Creek)."
                )
            else:
                st.warning("No parameters returned for the selected site(s).")
