"""Small Streamlit helpers for rendering registry options.

I keep these out of app.py so the main page stays readable.
Everything here is UI-only -- no API calls.
"""

from typing import Any, Dict, Iterable

import streamlit as st

from data_sources import SourceOption


def render_source_options(
    options: Iterable[SourceOption],
    source_key: str,
) -> Dict[str, Any]:
    """Turn SourceOption rows into sidebar widgets.

    Returns a dict of {option.key: current widget value}.
    Unknown kinds fall back to a text box so a typo in the
    registry doesn't crash the app -- I still see the value.

    source_key goes into each widget's Streamlit key so
    Aquarius and SNOTEL don't share a "verify_ssl" checkbox
    when I flip between them.
    """
    values: Dict[str, Any] = {}
    options = list(options)
    if not options:
        st.caption("No source-specific options for this one yet.")
        return values

    st.subheader("Source options")
    for opt in options:
        widget_key = f"opt_{source_key}_{opt.key}"
        help_text = opt.help or None

        if opt.kind == "checkbox":
            values[opt.key] = st.checkbox(
                opt.label,
                value=bool(opt.default),
                help=help_text,
                key=widget_key,
            )
        elif opt.kind == "select":
            choices = list(opt.choices) or [str(opt.default)]
            default = opt.default if opt.default in choices else choices[0]
            values[opt.key] = st.selectbox(
                opt.label,
                options=choices,
                index=choices.index(default),
                help=help_text,
                key=widget_key,
            )
        elif opt.kind == "number":
            values[opt.key] = st.number_input(
                opt.label,
                value=0 if opt.default is None else opt.default,
                help=help_text,
                key=widget_key,
            )
        else:
            # text, or anything I haven't wired yet
            values[opt.key] = st.text_input(
                opt.label,
                value="" if opt.default is None else str(opt.default),
                help=help_text,
                key=widget_key,
            )
    return values
