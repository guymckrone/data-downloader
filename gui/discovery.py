"""Discovery UI: find sites, then list available parameters.

Read-only for Step 3 -- no downloads. I only hit the APIs
when the user clicks a button, so Streamlit reruns (every
checkbox tick) don't burn USGS quota or re-pull SNOTEL.
"""

from typing import List, Optional

import pandas as pd
import streamlit as st

from data_sources import BaseDataSource, SiteInfo


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


def clear_discovery_state() -> None:
    """Drop cached discovery results (call when source changes).

    Also clears download results -- they were built from the
    old parameters catalogue.
    """
    for key in (
        "discovery_sites",
        "discovery_sites_df",
        "discovery_params_df",
        "discovery_error",
    ):
        st.session_state.pop(key, None)
    # Local import avoids a circular import at module load
    # (download.py doesn't import discovery today, but I don't
    # want a future one to bite me).
    from gui.download import clear_download_state
    clear_download_state()


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
            "Portal is Portland-only; state other than OR "
            "returns nothing. Some datasets have no map pin."
        )

    find = st.button("Find sites", type="primary", key=f"find_{source_key}")

    if find:
        state_arg = state.strip() or None
        ids_arg = parse_site_ids(site_ids_raw)

        if source_key in ("usgs", "snotel") and not state_arg and not ids_arg:
            clear_discovery_state()
            st.session_state["discovery_error"] = (
                "Give a state and/or site IDs first — "
                "an unfiltered pull is huge/slow for this source."
            )
        else:
            st.session_state.pop("discovery_error", None)
            site_kwargs = {}
            if source_key == "usgs":
                if agency_code.strip():
                    site_kwargs["agency_code"] = agency_code.strip()
                if site_type_code.strip():
                    site_kwargs["site_type_code"] = site_type_code.strip()
            try:
                with st.spinner("Calling get_sites()..."):
                    sites = source.get_sites(
                        state=state_arg,
                        site_ids=ids_arg,
                        **site_kwargs,
                    )
                st.session_state["discovery_sites"] = sites
                st.session_state["discovery_sites_df"] = sites_to_dataframe(
                    sites
                )
                # New site list invalidates params + any download
                st.session_state.pop("discovery_params_df", None)
                from gui.download import clear_download_state
                clear_download_state()
            except Exception as exc:
                clear_discovery_state()
                st.session_state["discovery_error"] = f"{type(exc).__name__}: {exc}"

    err = st.session_state.get("discovery_error")
    if err:
        st.error(err)

    sites_df = st.session_state.get("discovery_sites_df")
    sites: List[SiteInfo] = st.session_state.get("discovery_sites") or []

    if sites_df is None:
        st.info("Click **Find sites** to load a table.")
        return

    st.subheader(f"Sites ({len(sites_df):,})")
    st.dataframe(sites_df, use_container_width=True, hide_index=True)

    if sites_df.empty:
        st.warning("No sites matched those filters.")
        return

    # ---- map (Step 5a: pins only) ----
    from gui.map_view import render_sites_map
    render_sites_map(sites, source_key)

    # ---- parameters for selected site(s) ----
    st.subheader("Available parameters")
    id_list = [s.site_id for s in sites]
    # Default to first site so one click shows something useful
    selected = st.multiselect(
        "Sites to inspect",
        options=id_list,
        default=id_list[:1],
        key=f"discovery_select_{source_key}",
        help="One row per real series/element/dataset at each site.",
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
