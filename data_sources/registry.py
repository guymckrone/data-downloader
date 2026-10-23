"""
Source registry for the GUI (and anything else that wants a
catalog of available data sources).

Why this exists:
    The GUI should never hard-code "USGS" / "SNOTEL" /
    "Aquarius". It asks the registry what's available, then
    builds a source by key when the user picks one. Adding
    NOAA later should be one new entry here, not edits
    scattered through Streamlit code.

Lazy factories on purpose:
    Storing USGSDataSource() (with parentheses) would build
    every source the moment this module imports -- USGS
    resolves an API key, SNOTEL opens a requests Session.
    Storing a factory (a callable I invoke later) means
    import is free; construction only happens when someone
    calls create_source().

    Options are Streamlit-agnostic:
    Plain data describing sidebar widgets the GUI will build.
    No streamlit imports here -- this package stays testable
    without the GUI installed. Construction-related options
    (e.g. verify_ssl) can be passed into create_source();
    download-only options (e.g. duration) stay for the GUI
    to use later and are ignored by the factory.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple

from .aquarius import AquariusDataSource
from .base import BaseDataSource
from .snotel import SNOTELDataSource
from .usgs import USGSDataSource


# ---------------------------------------------------------
# DESCRIPTORS
# ---------------------------------------------------------

@dataclass(frozen=True)
class SourceOption:
    """One sidebar control the GUI can render later.

    kind is a plain string the Streamlit layer will interpret
    ("text", "select", "checkbox", "number") -- not a widget
    object. choices only matters for kind="select".
    """
    key: str
    label: str
    kind: str
    default: Any = None
    help: str = ""
    choices: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceDescriptor:
    """One row in the source catalog.

    key: machine id used in code ("usgs"). Stable, lowercase.
    display_name / description: what a human sees in the picker.
    factory: zero-arg callable that returns a fresh source.
    options: sidebar hints for Step 2+; empty is fine for now.
    """
    key: str
    display_name: str
    description: str
    factory: Callable[[], BaseDataSource]
    options: Tuple[SourceOption, ...] = ()


# ---------------------------------------------------------
# CATALOG
# ---------------------------------------------------------
# Import sibling modules above (not `from data_sources import
# ...`) so this file and __init__.py don't circular-import
# each other. Order here is picker order.

_SOURCES: Tuple[SourceDescriptor, ...] = (
    SourceDescriptor(
        key="usgs",
        display_name="USGS Water Data",
        description=(
            "USGS OGC API — streamflow, stage, and other "
            "continuous/daily series at monitoring locations."
        ),
        # **kwargs so create_source can pass options later;
        # USGS doesn't take verify_ssl, so ignore extras.
        factory=lambda **kwargs: USGSDataSource(),
        # Sidebar filters (state, bbox, shapefile) are shared
        # discovery UI in the GUI, not construction options.
        options=(),
    ),
    SourceDescriptor(
        key="aquarius",
        display_name="Portland BES Aquarius",
        description=(
            "Portland Bureau of Environmental Services "
            "Aquarius portal — local precip and related datasets."
        ),
        factory=lambda **kwargs: AquariusDataSource(
            verify_ssl=kwargs.get("verify_ssl", False),
        ),
        options=(
            SourceOption(
                key="verify_ssl",
                label="Verify SSL certificates",
                kind="checkbox",
                default=False,
                help=(
                    "Leave off on the work network (SSL "
                    "interception). On elsewhere."
                ),
            ),
        ),
    ),
    SourceDescriptor(
        key="snotel",
        display_name="NRCS SNOTEL",
        description=(
            "NRCS AWDB REST — SNOTEL (and SCAN) snow, soil, "
            "and weather elements by station triplet."
        ),
        factory=lambda **kwargs: SNOTELDataSource(
            verify_ssl=kwargs.get("verify_ssl", True),
        ),
        options=(
            SourceOption(
                key="verify_ssl",
                label="Verify SSL certificates",
                kind="checkbox",
                default=True,
                help=(
                    "Turn off on the work network (same SSL "
                    "interception issue as Aquarius). Default "
                    "matches SNOTELDataSource."
                ),
            ),
            SourceOption(
                key="duration",
                label="Default duration",
                kind="select",
                default="DAILY",
                choices=("DAILY", "HOURLY"),
                help="Passed to get_data as duration= later.",
            ),
        ),
    ),
)

# O(1) lookup by key; built once at import from the tuple above.
_BY_KEY: Dict[str, SourceDescriptor] = {
    d.key: d for d in _SOURCES
}


# ---------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------

def list_sources() -> List[SourceDescriptor]:
    """Return every registered source, in picker order."""
    return list(_SOURCES)


def get_descriptor(key: str) -> SourceDescriptor:
    """Look up one source by key.

    Raises ValueError with the valid keys listed if the key
    isn't registered -- refuse to guess, same spirit as the
    series-disambiguation rule in the sources themselves.
    """
    try:
        return _BY_KEY[key]
    except KeyError:
        known = ", ".join(d.key for d in _SOURCES) or "(none)"
        raise ValueError(
            f"Unknown data source {key!r}. Known sources: {known}"
        ) from None


def create_source(key: str, **kwargs) -> BaseDataSource:
    """Build a fresh source instance for the given key.

    Fresh every call on purpose -- the GUI (or caller) owns
    caching, not the registry. Optional kwargs are forwarded
    to the factory (verify_ssl for Aquarius/SNOTEL); each
    factory only picks what its constructor understands.
    """
    return get_descriptor(key).factory(**kwargs)
