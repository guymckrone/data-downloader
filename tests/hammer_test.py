"""
Hammer test: exercise every feature of all three data sources.

This is a live-API test script (not a unit test suite) -- it hits
USGS, the Aquarius portal, and SNOTEL for real and checks that
what comes back is sane, that chunked == unchunked, and that
bad inputs fail the way they're supposed to.

Run from the data-downloader folder:
    python tests/hammer_test.py

Credentials come from .env (USGS key optional, Aquarius needed).
Expect a few minutes and a bunch of log noise; the PASS/FAIL
summary at the end is the part that matters.
"""

import struct
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_sources import AquariusDataSource, SNOTELDataSource, USGSDataSource

RESULTS = []


def check(name, fn):
    """Run one check, record PASS/FAIL, keep going on failure."""
    try:
        fn()
    except Exception:
        RESULTS.append((name, "FAIL"))
        print(f"\nFAIL: {name}")
        traceback.print_exc()
    else:
        RESULTS.append((name, "PASS"))
        print(f"PASS: {name}")


def expect_raises(exc_type, fn, name=""):
    try:
        fn()
    except exc_type:
        return
    raise AssertionError(f"{name} should have raised {exc_type.__name__}")


def read_env():
    env = {}
    for line in open(".env", encoding="utf-8-sig"):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


ENV = read_env()

# =========================================================
# USGS
# =========================================================
usgs = USGSDataSource(api_key=ENV.get("USGS_API_KEY") or None)
JOHNSON = "14211400"          # Johnson Creek at Milwaukie, OR
RAIN_ONLY = "14211105"        # site with no time series
PORTLAND_BBOX = (-122.70, 45.50, -122.60, 45.55)


def usgs_sites_state():
    sites = usgs.get_sites(state="OR", site_type_code="ST", limit=50)
    assert len(sites) > 100, len(sites)
    assert all(s.latitude and s.longitude for s in sites[:20])


def usgs_sites_bbox_and_ids():
    bbox_sites = usgs.get_sites(bbox=PORTLAND_BBOX, site_type_code="ST")
    assert len(bbox_sites) > 10
    one = usgs.get_site(JOHNSON.replace("1421", "1421"))  # full path below
    by_bare = usgs.get_sites(site_ids=["14211105"])
    by_full = usgs.get_sites(site_ids=["USGS-14211105"])
    assert by_bare[0].site_id == by_full[0].site_id == "USGS-14211105"
    assert one.site_id.startswith("USGS-")


def usgs_sites_errors():
    expect_raises(ValueError, lambda: usgs.get_sites(state="XX"), "state")
    expect_raises(ValueError, lambda: usgs.get_sites(bbox=(1, 2, 3)), "bbox")
    expect_raises(ValueError, lambda: usgs.get_sites(bogus_filter=1), "kwarg")


def usgs_shapefile():
    tmp = Path(tempfile.mkdtemp())
    shp = tmp / "watershed.shp"
    header = bytearray(100)
    struct.pack_into(">i", header, 0, 9994)
    struct.pack_into("<4d", header, 36, PORTLAND_BBOX[0], PORTLAND_BBOX[1], PORTLAND_BBOX[2], PORTLAND_BBOX[3])
    shp.write_bytes(bytes(header))
    assert usgs.shapefile_bbox(str(shp)) == PORTLAND_BBOX
    sites = usgs.get_sites_from_shapefile(str(shp), site_type_code="ST")
    assert len(sites) > 10
    struct.pack_into("<4d", header, 36, 7_600_000.0, 600_000.0, 7_700_000.0, 700_000.0)
    shp.write_bytes(bytes(header))
    expect_raises(ValueError, lambda: usgs.shapefile_bbox(str(shp)), "projected")
    expect_raises(FileNotFoundError, lambda: usgs.shapefile_bbox(str(tmp / "nope.shp")), "missing")


def usgs_parameters():
    params = usgs.get_available_parameters(JOHNSON)
    assert len(params) > 10
    codes = {p["code"] for p in params}
    assert {"00060", "00065"} <= codes
    assert all(isinstance(p["code"], str) for p in params)
    df = usgs.available_parameters_dataframe([JOHNSON, "14197900"])
    assert len(df) > len(params)
    assert "computation_period" in df.columns
    assert usgs.get_available_parameters(RAIN_ONLY) == []


def usgs_get_data():
    pts = usgs.get_data([JOHNSON], "discharge", datetime(2026, 10, 19), datetime(2026, 10, 20))
    assert len(pts) == 97, len(pts)  # 96 + inclusive endpoint
    assert pts[0].parameter == "Discharge" and pts[0].unit == "ft^3/s"
    df = usgs.to_dataframe(pts)
    assert list(df.columns) == ["timestamp", "value", "location", "parameter", "unit", "source", "quality_flag"]


def usgs_get_data_daily_and_selection():
    daily = usgs.get_data([JOHNSON], "00060", datetime(2026, 10, 1), datetime(2026, 10, 7), computation="Mean")
    assert len(daily) == 7 and daily[0].parameter == "Discharge (Mean)"
    by_stat = usgs.get_data([JOHNSON], "discharge", datetime(2026, 10, 1), datetime(2026, 10, 7), statistic_id="3")
    assert [p.value for p in by_stat] == [p.value for p in daily]
    by_id = usgs.get_data([JOHNSON], "00060", datetime(2026, 10, 19), datetime(2026, 10, 20),
                          time_series_id="1fd86fd765fa42e780d04f20f32a2027")
    assert len(by_id) == 97
    expect_raises(ValueError, lambda: usgs.get_data(
        [JOHNSON], "water_temperature", datetime(2026, 10, 19), datetime(2026, 10, 20)), "ambiguity")
    expect_raises(ValueError, lambda: usgs.get_data(
        [JOHNSON], "nope", datetime(2026, 1, 1), datetime(2026, 1, 2)), "bad param")
    expect_raises(ValueError, lambda: usgs.get_data(
        [JOHNSON], "discharge", datetime(2026, 2, 1), datetime(2026, 1, 1)), "reversed")
    expect_raises(ValueError, lambda: usgs.get_data(
        [JOHNSON], "discharge", datetime(2026, 1, 1), datetime(2026, 1, 2), chunk_years=0), "chunk")


def usgs_chunk_equivalence():
    chunked = usgs.get_data([JOHNSON], "discharge", datetime(2020, 1, 1), datetime(2023, 1, 1),
                            computation="Mean", chunk_years=1)
    single = usgs.get_data([JOHNSON], "discharge", datetime(2020, 1, 1), datetime(2023, 1, 1),
                           computation="Mean", chunk_years=100)
    assert len(chunked) == len(single)
    assert abs(sum(p.value for p in chunked) - sum(p.value for p in single)) < 1e-6


def usgs_all_series():
    preview = usgs.preview_all_series([JOHNSON])
    assert len(preview) >= 20
    pts = usgs.get_all_series_data([JOHNSON], datetime(2026, 10, 19), datetime(2026, 10, 20))
    assert len(pts) > 300
    discharge_only = usgs.get_all_series_data([JOHNSON], datetime(2026, 10, 19), datetime(2026, 10, 20),
                                              parameters=["discharge"], include_daily=False)
    assert {p.parameter for p in discharge_only} == {"Discharge"}


# =========================================================
# AQUARIUS
# =========================================================
aquarius = AquariusDataSource(
    base_url=ENV.get("AQUARIUS_BASE_URL"),
    username=ENV.get("AQUARIUS_USERNAME"),
    password=ENV.get("AQUARIUS_PASSWORD"),
)


def aquarius_sites():
    sites = aquarius.get_sites()
    assert len(sites) > 500
    assert aquarius.get_sites(state="WA") == []
    bbox = aquarius.get_sites(bbox=PORTLAND_BBOX)
    assert 10 < len(bbox) < len(sites)
    one = aquarius.get_site("HYDRA-1")
    assert one.site_id == "HYDRA-1" and one.latitude
    expect_raises(ValueError, lambda: aquarius.get_site("NOPE-9999"), "bad site")


def aquarius_catalogue():
    cat = aquarius.available_datasets_dataframe()
    assert len(cat) > 2000
    assert "Precipitation Incremental" in set(cat["name"])
    df = aquarius.available_parameters_dataframe(["HYDRA-1"])
    assert len(df) == 4


def aquarius_get_data():
    pts = aquarius.get_data(["HYDRA-1"], "precip", datetime(2026, 10, 19), datetime(2026, 10, 20), label="15Minute")
    assert len(pts) == 96, len(pts)
    assert pts[0].unit == "in" and pts[0].source == "Aquarius"
    expect_raises(ValueError, lambda: aquarius.get_data(
        ["HYDRA-1"], "Precipitation Incremental", datetime(2026, 10, 19), datetime(2026, 10, 20)), "ambiguity")
    by_id = aquarius.get_dataset_data(["Precip Increm.1Hour@HYDRA-1"], datetime(2026, 10, 19), datetime(2026, 10, 20))
    assert len(by_id) == 25
    multi = aquarius.get_data(["HYDRA-1", "HYDRA-2"], "precip", datetime(2026, 10, 19), datetime(2026, 10, 20), label="15Minute")
    assert len(multi) == 192
    expect_raises(ValueError, lambda: aquarius.get_dataset_data(
        ["Bogus@HYDRA-1"], datetime(2026, 1, 1), datetime(2026, 1, 2)), "bad id")


def aquarius_chunk_equivalence():
    chunked = aquarius.get_dataset_data(["Precip Increm.15Minute@HYDRA-1"],
                                        datetime(2025, 1, 1), datetime(2026, 1, 1), chunk_years=1)
    single = aquarius.get_dataset_data(["Precip Increm.15Minute@HYDRA-1"],
                                       datetime(2025, 1, 1), datetime(2026, 1, 1), chunk_years=5)
    assert len(chunked) == len(single) == 365 * 96
    assert abs(sum(p.value for p in chunked) - sum(p.value for p in single)) < 1e-9


def aquarius_all_datasets():
    preview = aquarius.preview_all_datasets(site_ids=["HYDRA-1"])
    assert len(preview) == 4
    pts = aquarius.get_all_datasets_data(["HYDRA-1"], datetime(2026, 10, 19), datetime(2026, 10, 20))
    assert len(pts) > 300
    expect_raises(ValueError, lambda: aquarius.get_all_datasets_data(["HYDRA-1"]), "no dates")
    expect_raises(ValueError, lambda: aquarius.get_all_datasets_data(
        ["NOPE-1"], datetime(2026, 1, 1), datetime(2026, 1, 2)), "no match")


# =========================================================
# SNOTEL
# =========================================================
snotel = SNOTELDataSource(verify_ssl=False)
ANEROID = "302:OR:SNTL"


def snotel_sites():
    sites = snotel.get_sites(state="OR")
    assert len(sites) > 50
    one = snotel.get_site("302", state="OR")
    assert one.site_id == ANEROID
    bbox = snotel.get_sites(state="OR", bbox=(-122.2, 45.2, -121.4, 45.5))
    assert 0 < len(bbox) < len(sites)
    expect_raises(ValueError, lambda: snotel.get_sites(state="OR", bbox=(1, 2)), "bbox")
    expect_raises(ValueError, lambda: snotel.get_site("99999", state="OR"), "bad site")


def snotel_parameters():
    params = snotel.get_available_parameters(ANEROID)
    assert len(params) > 50
    codes = {p["code"] for p in params}
    assert {"WTEQ", "SNWD"} <= codes
    df = snotel.available_parameters_dataframe([ANEROID])
    assert len(df) == len(params)


def snotel_get_data():
    pts = snotel.get_data([ANEROID], "WTEQ", datetime(2026, 1, 1), datetime(2026, 4, 30))
    assert len(pts) == 120
    assert pts[0].unit == "in" and pts[0].source == "SNOTEL"
    by_name = snotel.get_data([ANEROID], "Snow Water Equivalent", datetime(2026, 1, 1), datetime(2026, 1, 10))
    assert len(by_name) == 10
    hourly = snotel.get_data(["651:OR:SNTL"], "TOBS", datetime(2026, 1, 5), datetime(2026, 1, 6), duration="HOURLY")
    assert len(hourly) == 25
    expect_raises(ValueError, lambda: snotel.get_data(
        [ANEROID], "junk element", datetime(2026, 1, 1), datetime(2026, 1, 2)), "bad element")


def snotel_chunk_equivalence():
    chunked = snotel.get_data([ANEROID], "WTEQ", datetime(2000, 1, 1), datetime(2020, 1, 1), chunk_years=5)
    single = snotel.get_data([ANEROID], "WTEQ", datetime(2000, 1, 1), datetime(2020, 1, 1), chunk_years=100)
    assert len(chunked) == len(single)
    assert abs(sum(p.value for p in chunked) - sum(p.value for p in single)) < 1e-6


def snotel_all_elements():
    preview = snotel.preview_all_elements([ANEROID])
    assert len(preview) >= 10
    pts = snotel.get_all_elements_data([ANEROID], datetime(2026, 1, 1), datetime(2026, 1, 31))
    assert len(pts) > 300
    filtered = snotel.get_all_elements_data([ANEROID], datetime(2026, 1, 1), datetime(2026, 1, 31),
                                            elements=["WTEQ", "SNWD"])
    assert {p.parameter for p in filtered} == {"Snow Water Equivalent", "Snow Depth"}
    expect_raises(ValueError, lambda: snotel.get_all_elements_data(
        [ANEROID], datetime(2026, 1, 1), datetime(2026, 1, 2), elements=["SMS"]), "no match")


def usgs_extra_edges():
    small_pages = usgs.get_sites(state="OR", site_type_code="ST", limit=37)
    big_pages = usgs.get_sites(state="OR", site_type_code="ST", limit=1000)
    assert len(small_pages) == len(big_pages), (len(small_pages), len(big_pages))
    assert {s.site_id for s in small_pages} == {s.site_id for s in big_pages}
    string_dates = usgs.get_data([JOHNSON], "discharge", "2026-10-19", "2026-10-20")
    assert len(string_dates) == 97
    from datetime import date as date_only
    date_objects = usgs.get_data([JOHNSON], "discharge", date_only(2026, 10, 19), date_only(2026, 10, 20))
    assert len(date_objects) == 97
    expect_raises(ValueError, lambda: usgs.get_data(
        ["99999999"], "discharge", datetime(2026, 1, 1), datetime(2026, 1, 2)), "fake site")
    repeated = usgs.get_sites(bbox=PORTLAND_BBOX, site_type_code="ST")
    assert repeated == usgs.get_sites(bbox=PORTLAND_BBOX, site_type_code="ST")  # cache path


def aquarius_extra_edges():
    active = aquarius.get_sites(active_only=True)
    assert 0 < len(active) <= len(aquarius.get_sites())
    typed = aquarius.get_sites(site_type="Surface Water")
    assert len(typed) > 50  # 72 on the live portal when written
    assert aquarius.get_available_parameters("NOPE-9999") == []
    upper = aquarius.get_data(["HYDRA-1"], "PRECIP", datetime(2026, 10, 19), datetime(2026, 10, 20), label="15minute")
    assert len(upper) == 96
    expect_raises(ValueError, lambda: aquarius.get_data(
        ["HYDRA-1"], "precip", datetime(2026, 10, 20), datetime(2026, 10, 19), label="15Minute"), "reversed")


def snotel_extra_edges():
    bare = snotel.get_data(["302"], "WTEQ", datetime(2026, 1, 1), datetime(2026, 1, 5), state="OR")
    assert len(bare) == 5 and bare[0].location_id == ANEROID
    scan = snotel.get_sites(state="OR", network_code="SCAN")
    assert len(scan) > 0 and all(s.metadata["network_code"] == "SCAN" for s in scan)
    expect_raises(ValueError, lambda: snotel.get_data(
        [ANEROID], "WTEQ", datetime(2026, 2, 1), datetime(2026, 1, 1)), "reversed")
    expect_raises(ValueError, lambda: snotel.get_data(
        [ANEROID], "WTEQ", datetime(2026, 1, 1), datetime(2026, 1, 2), chunk_years=0), "chunk")
    assert snotel.get_data([ANEROID], "SMS", datetime(2026, 1, 1), datetime(2026, 1, 3)) == []


# =========================================================
# CROSS-SOURCE
# =========================================================
def cross_source_dataframe_shape():
    empty = usgs.to_dataframe([])
    assert empty.empty
    frames = [
        usgs.to_dataframe(usgs.get_data([JOHNSON], "discharge", datetime(2026, 10, 19), datetime(2026, 10, 20))),
        aquarius.to_dataframe(aquarius.get_data(["HYDRA-1"], "precip", datetime(2026, 10, 19),
                                                datetime(2026, 10, 20), label="15Minute")),
        snotel.to_dataframe(snotel.get_data([ANEROID], "WTEQ", datetime(2026, 1, 1), datetime(2026, 1, 10))),
    ]
    column_sets = {tuple(f.columns) for f in frames}
    assert len(column_sets) == 1, column_sets
    assert {f["source"].iloc[0] for f in frames} == {"USGS", "Aquarius", "SNOTEL"}


ALL_CHECKS = [
    ("USGS sites state", usgs_sites_state),
    ("USGS sites bbox/ids", usgs_sites_bbox_and_ids),
    ("USGS sites errors", usgs_sites_errors),
    ("USGS shapefile", usgs_shapefile),
    ("USGS parameters", usgs_parameters),
    ("USGS get_data", usgs_get_data),
    ("USGS daily/selection", usgs_get_data_daily_and_selection),
    ("USGS chunk equivalence", usgs_chunk_equivalence),
    ("USGS all series", usgs_all_series),
    ("Aquarius sites", aquarius_sites),
    ("Aquarius catalogue", aquarius_catalogue),
    ("Aquarius get_data", aquarius_get_data),
    ("Aquarius chunk equivalence", aquarius_chunk_equivalence),
    ("Aquarius all datasets", aquarius_all_datasets),
    ("SNOTEL sites", snotel_sites),
    ("SNOTEL parameters", snotel_parameters),
    ("SNOTEL get_data", snotel_get_data),
    ("SNOTEL chunk equivalence", snotel_chunk_equivalence),
    ("SNOTEL all elements", snotel_all_elements),
    ("USGS extra edges", usgs_extra_edges),
    ("Aquarius extra edges", aquarius_extra_edges),
    ("SNOTEL extra edges", snotel_extra_edges),
    ("Cross-source DataFrame shape", cross_source_dataframe_shape),
]


def main():
    only = sys.argv[1].lower() if len(sys.argv) > 1 else None
    for name, fn in ALL_CHECKS:
        if only and only not in name.lower():
            continue
        check(name, fn)

    print("\n" + "=" * 50)
    failed = [name for name, result in RESULTS if result == "FAIL"]
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    if failed:
        print("FAILED:", ", ".join(failed))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
