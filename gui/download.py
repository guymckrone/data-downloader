"""Download UI: pick series from the discovery catalogue, pull data, export.

I only call get_data when the user clicks Download -- same
button-driven idea as discovery, so Streamlit reruns don't
re-hit the APIs. Each selected catalogue row becomes one
get_data() call with exact disambiguation kwargs (time_series_id
/ dataset_identifier / duration+ordinal) so I never guess
when a site has several series for the same parameter.

Exports (from the shared to_dataframe() columns):
    CSV  -- plain text, one row per point
    .db  -- SQLite file with an `observations` table (same
            columns). Readable later with sqlite3 / pandas
            read_sql, same idea as the Aquarius precip DBs.

Layout:
    One file     -- all selected series stacked (current default)
    One per series -- a ZIP with one csv/.db per timeseries
"""

import io
import os
import re
import sqlite3
import tempfile
import zipfile
from datetime import date, datetime, timedelta
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from data_sources import BaseDataSource


def dataframe_to_sqlite_bytes(
    df: pd.DataFrame,
    table_name: str = "observations",
) -> bytes:
    """Pack a DataFrame into a SQLite .db file (as bytes).

    Streamlit's download_button wants bytes in memory, so I
    write a temp file, read it back, and delete it. Timestamps
    go in as text (ISO) -- SQLite has no real datetime type,
    and that's what the Aquarius precip DBs do too.
    """
    out = df.copy()
    if "timestamp" in out.columns:
        out["timestamp"] = out["timestamp"].astype(str)

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        # Explicit close before reading bytes -- Windows can
        # keep a lock if I only rely on the context manager.
        conn = sqlite3.connect(path)
        try:
            out.to_sql(table_name, conn, index=False, if_exists="replace")
            conn.commit()
        finally:
            conn.close()
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def clear_download_state() -> None:
    """Drop cached download results."""
    for key in (
        "download_df",
        "download_parts",
        "download_error",
        "download_meta",
    ):
        st.session_state.pop(key, None)


def _safe_stem(text: str, max_len: int = 80) -> str:
    """Turn a label into a filesystem-safe filename piece."""
    cleaned = re.sub(r"[^\w.\-]+", "_", str(text).strip())
    cleaned = cleaned.strip("._") or "series"
    return cleaned[:max_len]


def _part_stem(row: pd.Series, source_key: str) -> str:
    """Filename stem for one timeseries (no extension)."""
    site = str(row.get("site_id") or "site")
    code = str(row.get("code") or "param")
    if source_key == "usgs":
        tid = str(row.get("time_series_id") or "")[:8]
        comp = str(row.get("computation") or "")
        return _safe_stem(f"{site}_{code}_{comp}_{tid}")
    if source_key == "aquarius":
        ident = str(
            row.get("dataset_identifier") or row.get("code") or "dataset"
        )
        return _safe_stem(ident.replace("@", "_at_"))
    dur = str(row.get("duration") or "")
    ord_ = str(row.get("ordinal") or "")
    depth = str(row.get("height_depth") or "")
    return _safe_stem(f"{site}_{code}_{dur}_ord{ord_}_{depth}")


def _unique_stems(stems: List[str]) -> List[str]:
    """If two series collide on a name, append _2, _3, ..."""
    seen: Dict[str, int] = {}
    unique: List[str] = []
    for stem in stems:
        count = seen.get(stem, 0) + 1
        seen[stem] = count
        unique.append(stem if count == 1 else f"{stem}_{count}")
    return unique


def parts_to_zip(
    parts: List[Dict[str, Any]],
    fmt: str,
) -> bytes:
    """ZIP of one csv or .db per part. fmt is 'csv' or 'db'."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for part in parts:
            stem = part["stem"]
            part_df: pd.DataFrame = part["df"]
            if fmt == "csv":
                zf.writestr(
                    f"{stem}.csv",
                    part_df.to_csv(index=False).encode("utf-8"),
                )
            elif fmt == "db":
                zf.writestr(f"{stem}.db", dataframe_to_sqlite_bytes(part_df))
            else:
                raise ValueError(f"Unknown zip format: {fmt!r}")
    return buf.getvalue()


def _series_key(row: pd.Series, source_key: str) -> str:
    """Stable id for one catalogue row (used in the multiselect)."""
    if source_key == "usgs":
        return str(row.get("time_series_id") or "")
    if source_key == "aquarius":
        return str(row.get("dataset_identifier") or row.get("code") or "")
    # snotel -- code alone isn't unique (same element, several
    # ordinals / depths), so I pack the disambiguators in.
    parts = [
        str(row.get("site_id") or ""),
        str(row.get("code") or ""),
        str(row.get("duration") or ""),
        str(row.get("ordinal") or ""),
        str(row.get("height_depth") or ""),
    ]
    return "|".join(parts)


def _series_label(row: pd.Series, source_key: str) -> str:
    """Human-readable line for the multiselect."""
    site = row.get("site_id", "")
    code = row.get("code", "")
    name = row.get("name", "")
    if source_key == "usgs":
        comp = row.get("computation", "")
        sub = row.get("sublocation", "")
        extra = comp + (f" / {sub}" if sub else "")
        return f"{site} | {code} {name} | {extra}".strip(" |")
    if source_key == "aquarius":
        label = row.get("label", "")
        return f"{site} | {code} | {label}".strip(" |")
    # snotel
    dur = row.get("duration", "")
    ord_ = row.get("ordinal", "")
    depth = row.get("height_depth", "")
    tail = f"{dur}, ord {ord_}" + (f", {depth}" if depth else "")
    return f"{site} | {code} {name} | {tail}".strip(" |")


def _rows_by_key(
    params_df: pd.DataFrame, source_key: str
) -> Dict[str, pd.Series]:
    """Map series key -> catalogue row."""
    mapping: Dict[str, pd.Series] = {}
    for _, row in params_df.iterrows():
        key = _series_key(row, source_key)
        if key:
            mapping[key] = row
    return mapping


def _get_data_for_row(
    source: BaseDataSource,
    source_key: str,
    row: pd.Series,
    start: date,
    end: date,
) -> List[Any]:
    """One catalogue row -> get_data() with no-guessing kwargs."""
    site_id = str(row["site_id"])
    start_dt = datetime(start.year, start.month, start.day)
    # end-of-day-ish: pass the date; each source coerces it.
    end_dt = datetime(end.year, end.month, end.day)

    if source_key == "usgs":
        return source.get_data(
            site_ids=[site_id],
            parameter=str(row["code"]),
            start_date=start_dt,
            end_date=end_dt,
            time_series_id=str(row["time_series_id"]),
        )

    if source_key == "aquarius":
        identifier = str(
            row.get("dataset_identifier") or row.get("code") or ""
        )
        return source.get_data(
            site_ids=[site_id],
            parameter=identifier,
            start_date=start_dt,
            end_date=end_dt,
            dataset_identifiers=[identifier],
        )

    # snotel
    duration = str(row.get("duration") or "DAILY").upper()
    try:
        ordinal = int(float(row.get("ordinal") or 1))
    except (TypeError, ValueError):
        ordinal = 1
    return source.get_data(
        site_ids=[site_id],
        parameter=str(row["code"]),
        start_date=start_dt,
        end_date=end_dt,
        duration=duration,
        ordinal=ordinal,
    )


def render_download(
    source: BaseDataSource,
    source_key: str,
) -> None:
    """Date range + series pick + download + CSV button."""
    st.header("Download")
    st.caption(
        "Pick series from the parameters table above, set dates, "
        "then download. Output is the shared to_dataframe() shape."
    )

    params_df = st.session_state.get("discovery_params_df")
    if params_df is None:
        st.info(
            "Load **Show available parameters** in Discovery first — "
            "that catalogue is what you pick downloads from."
        )
        return
    if params_df.empty:
        st.warning("Parameters table is empty — nothing to download.")
        return

    by_key = _rows_by_key(params_df, source_key)
    if not by_key:
        st.error(
            "Couldn't build series keys from this catalogue. "
            "Expected time_series_id / dataset_identifier / "
            "code+duration columns."
        )
        return

    labels = {
        key: _series_label(row, source_key) for key, row in by_key.items()
    }
    # Stable order matching the parameters table
    ordered_keys = [k for k in by_key if k]

    selected_keys = st.multiselect(
        "Series to download",
        options=ordered_keys,
        format_func=lambda k: labels.get(k, k),
        key=f"download_select_{source_key}",
        help=(
            "Each row is one real series/element/dataset. "
            "I pass its exact id into get_data so nothing is guessed."
        ),
    )

    today = date.today()
    col_a, col_b = st.columns(2)
    with col_a:
        start = st.date_input(
            "Start date",
            value=today - timedelta(days=365),
            key=f"download_start_{source_key}",
        )
    with col_b:
        end = st.date_input(
            "End date",
            value=today,
            key=f"download_end_{source_key}",
        )

    if isinstance(start, tuple):  # streamlit oddity with ranges
        start = start[0] if start else today
    if isinstance(end, tuple):
        end = end[0] if end else today

    go = st.button(
        "Download data",
        type="primary",
        key=f"download_go_{source_key}",
    )

    if go:
        if not selected_keys:
            st.warning("Pick at least one series.")
        elif end < start:
            st.error("End date is before start date.")
        else:
            st.session_state.pop("download_error", None)
            all_points: List[Any] = []
            parts: List[Dict[str, Any]] = []
            raw_stems: List[str] = []
            errors: List[str] = []
            n = len(selected_keys)
            bar = st.progress(0)
            status = st.empty()

            for i, key in enumerate(selected_keys):
                row = by_key[key]
                status.caption(
                    f"Downloading {i + 1}/{n}: {labels.get(key, key)}"
                )
                try:
                    points = _get_data_for_row(
                        source, source_key, row, start, end
                    )
                    part_df = source.to_dataframe(points)
                    parts.append(
                        {
                            "stem": _part_stem(row, source_key),
                            "label": labels.get(key, key),
                            "df": part_df,
                        }
                    )
                    raw_stems.append(parts[-1]["stem"])
                    all_points.extend(points)
                except Exception as exc:
                    errors.append(
                        f"{labels.get(key, key)}: "
                        f"{type(exc).__name__}: {exc}"
                    )
                bar.progress((i + 1) / n)

            status.empty()
            bar.empty()

            if errors and not parts:
                st.session_state["download_df"] = None
                st.session_state["download_parts"] = None
                st.session_state["download_error"] = "\n".join(errors)
                st.session_state["download_meta"] = None
            else:
                # Dedupe stems so two similar series don't clobber
                # each other inside a per-series ZIP.
                for part, stem in zip(parts, _unique_stems(raw_stems)):
                    part["stem"] = stem
                df = source.to_dataframe(all_points)
                st.session_state["download_df"] = df
                st.session_state["download_parts"] = parts
                st.session_state["download_meta"] = {
                    "series_count": len(parts),
                    "point_count": len(all_points),
                    "start": str(start),
                    "end": str(end),
                    "partial_errors": errors,
                }
                if errors:
                    st.session_state["download_error"] = (
                        "Some series failed; others succeeded:\n"
                        + "\n".join(errors)
                    )
                else:
                    st.session_state.pop("download_error", None)

    err = st.session_state.get("download_error")
    if err:
        st.error(err)

    df = st.session_state.get("download_df")
    parts = st.session_state.get("download_parts") or []
    meta = st.session_state.get("download_meta")
    if df is None:
        return

    if meta:
        st.caption(
            f"{meta['point_count']:,} points from "
            f"{meta['series_count']} series "
            f"({meta['start']} → {meta['end']})"
        )

    st.dataframe(df, use_container_width=True, hide_index=True)

    if df.empty and not parts:
        st.warning("Download returned no points for that range.")
        return

    base_name = (
        f"{source_key}_{meta['start']}_{meta['end']}"
        if meta else f"{source_key}_data"
    )

    st.subheader("Save")
    layout = st.radio(
        "File layout",
        options=["combined", "per_series"],
        format_func=lambda v: (
            "One file (all series together)"
            if v == "combined"
            else "One file per timeseries (ZIP)"
        ),
        horizontal=True,
        key=f"download_layout_{source_key}",
        help=(
            "Combined stacks every series into one csv/.db. "
            "Per timeseries puts each series in its own file "
            "inside a ZIP (browsers only let me hand you one "
            "download at a time)."
        ),
    )

    if layout == "combined":
        st.caption(
            "SQLite table name is `observations` "
            "(columns match the preview table)."
        )
        col_csv, col_db = st.columns(2)
        with col_csv:
            st.download_button(
                label="Save CSV",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name=f"{base_name}.csv",
                mime="text/csv",
                key=f"download_csv_{source_key}",
                use_container_width=True,
            )
        with col_db:
            st.download_button(
                label="Save SQLite (.db)",
                data=dataframe_to_sqlite_bytes(df),
                file_name=f"{base_name}.db",
                mime="application/x-sqlite3",
                key=f"download_db_{source_key}",
                use_container_width=True,
            )
    else:
        if not parts:
            st.warning("No per-series parts to pack into a ZIP.")
            return
        st.caption(
            f"ZIP will contain {len(parts)} file(s). "
            "Each SQLite file has an `observations` table."
        )
        col_csv, col_db = st.columns(2)
        with col_csv:
            st.download_button(
                label="Save CSV (ZIP)",
                data=parts_to_zip(parts, "csv"),
                file_name=f"{base_name}_csv.zip",
                mime="application/zip",
                key=f"download_csv_zip_{source_key}",
                use_container_width=True,
            )
        with col_db:
            st.download_button(
                label="Save SQLite (ZIP)",
                data=parts_to_zip(parts, "db"),
                file_name=f"{base_name}_db.zip",
                mime="application/zip",
                key=f"download_db_zip_{source_key}",
                use_container_width=True,
            )
