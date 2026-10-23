"""
DataDownloader — Streamlit skeleton (Step 2).

Run from the data-downloader folder:
    streamlit run gui\\app.py

What this page does today:
    - Lists sources from the registry (no hard-coded names)
    - Lets me pick one; builds it via create_source() into
      session_state (constructor only -- no get_sites / get_data)
    - Renders that source's declared sidebar options
    - Shows an empty main-page placeholder for Step 3

Install once (same conda env as the downloader):
    pip install -r requirements-gui.txt
"""

import sys
from pathlib import Path

# streamlit run gui/app.py puts gui/ on sys.path, not the
# project root -- so bare `import data_sources` would fail.
# Stick the repo root (parent of gui/) on the path first.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from data_sources import create_source, get_descriptor, list_sources
from gui.widgets import render_source_options


def _ensure_source(key: str) -> None:
    """Build (or rebuild) the active source when the pick changes.

    Streamlit reruns this whole script on every widget click, so
    I stash the live source on st.session_state. Rebuilding only
    when the key changes means I don't construct a new USGS /
    SNOTEL client on every checkbox tick.
    """
    if st.session_state.get("source_key") == key:
        return
    st.session_state["source_key"] = key
    st.session_state["source"] = create_source(key)


def main() -> None:
    st.set_page_config(
        page_title="DataDownloader",
        layout="wide",
    )

    sources = list_sources()
    if not sources:
        st.error("No data sources registered.")
        return

    keys = [d.key for d in sources]
    label_for = {d.key: d.display_name for d in sources}

    st.sidebar.title("DataDownloader")
    selected_key = st.sidebar.radio(
        "Data source",
        options=keys,
        format_func=lambda k: label_for[k],
        help="Catalog comes from data_sources.registry — not hard-coded here.",
    )

    _ensure_source(selected_key)
    descriptor = get_descriptor(selected_key)
    source = st.session_state["source"]

    # Source-specific sidebar widgets (values collected for
    # later steps; create_source still uses class defaults).
    option_values = render_source_options(
        descriptor.options, source_key=selected_key
    )
    st.session_state["source_options"] = option_values

    # ---- main page (empty on purpose for Step 2) ----
    st.title(descriptor.display_name)
    st.write(descriptor.description)

    st.info(
        "Discovery (sites + available parameters) comes in Step 3. "
        "This page is just the picker and sidebar wiring."
    )

    # Tiny status so I can see the factory actually ran.
    with st.expander("Session status (debug)", expanded=False):
        st.write(
            {
                "registry_key": selected_key,
                "source_class": type(source).__name__,
                "source_name": source.source_name,
                "option_values": option_values,
            }
        )


if __name__ == "__main__":
    main()
