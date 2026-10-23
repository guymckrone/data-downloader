"""
DataDownloader — Streamlit GUI.

Run from the data-downloader folder:
    streamlit run gui\\app.py

Steps so far:
    1. Registry-backed source picker
    2. Source-specific sidebar options
    3. Discovery: sites table + available-parameters table
       (button-driven; no downloads yet)

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
from gui.discovery import clear_discovery_state, render_discovery
from gui.widgets import render_source_options


def _constructor_kwargs(source_key: str, option_values: dict) -> dict:
    """Pick option values that create_source actually understands.

    duration stays GUI-only until downloads (Step 4).
    """
    kwargs = {}
    if source_key in ("aquarius", "snotel") and "verify_ssl" in option_values:
        kwargs["verify_ssl"] = bool(option_values["verify_ssl"])
    return kwargs


def _ensure_source(key: str, option_values: dict) -> None:
    """Build (or rebuild) the active source when pick/options change.

    Streamlit reruns this whole script on every widget click, so
    I stash the live source on st.session_state. Fingerprint
    includes constructor kwargs (verify_ssl) so flipping SSL
    rebuilds the client. Discovery results clear on rebuild --
    they belong to the previous source.
    """
    kwargs = _constructor_kwargs(key, option_values)
    fingerprint = (key, tuple(sorted(kwargs.items())))
    if st.session_state.get("source_fingerprint") == fingerprint:
        return

    st.session_state["source_fingerprint"] = fingerprint
    st.session_state["source_key"] = key
    st.session_state["source"] = create_source(key, **kwargs)
    clear_discovery_state()


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

    descriptor = get_descriptor(selected_key)

    # Options first so verify_ssl can feed create_source.
    option_values = render_source_options(
        descriptor.options, source_key=selected_key
    )
    st.session_state["source_options"] = option_values

    _ensure_source(selected_key, option_values)
    source = st.session_state["source"]

    st.title(descriptor.display_name)
    st.write(descriptor.description)

    render_discovery(source, selected_key)

    with st.expander("Session status (debug)", expanded=False):
        st.write(
            {
                "registry_key": selected_key,
                "source_class": type(source).__name__,
                "source_name": source.source_name,
                "option_values": option_values,
                "sites_loaded": len(
                    st.session_state.get("discovery_sites") or []
                ),
            }
        )


if __name__ == "__main__":
    main()
