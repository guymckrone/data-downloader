"""StreamStats tool page — stub until the API client is wired."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

# Prove the package import path works; no API calls yet.
from streamstats import StreamStatsClient  # noqa: F401


def main() -> None:
    st.set_page_config(
        page_title="StreamStats — Tributary Toolkit",
        layout="wide",
    )

    st.title("StreamStats")
    st.write(
        "Batch watershed delineation and basin attributes from "
        "points, via the USGS StreamStats services."
    )

    st.info(
        "Not implemented yet — this page is a placeholder so the "
        "toolkit shell has a home for the next build step."
    )

    st.subheader("Planned workflow")
    st.markdown(
        """
1. **Load points** — CSV upload and/or map clicks (lat/lon).
2. **Snap** — move each point to the nearest StreamStats /
   stream location.
3. **Delineate** — request watersheds for the snapped points
   (batch).
4. **Attributes** — pull StreamStats basin characteristics.
5. **Review + export** — map of basins, table of attributes,
   CSV / Geo-friendly download.
        """
    )

    st.caption(
        "Backend package: `streamstats/` (sibling to "
        "`data_sources/`). Not a BaseDataSource — outputs are "
        "basins and attributes, not time-series DataPoints."
    )


main()
