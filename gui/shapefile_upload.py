"""Shapefile ZIP upload for site discovery (Step 5d).

A watershed shapefile is usually a zip of .shp/.shx/.dbf/.prj.
I unpack it, find the .shp, and read its bounding box with the
same USGS header reader the backend already uses (lon/lat only,
projected CRS rejected). The caller then passes that bbox into
get_sites() -- this is a rectangle around the polygon, not
point-in-polygon.
"""

import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Tuple

from data_sources import USGSDataSource

BBox = Tuple[float, float, float, float]


def bbox_from_shapefile_zip(data: bytes) -> Tuple[BBox, str]:
    """Unpack a zip and return (bbox, shp filename).

    bbox is (min_lon, min_lat, max_lon, max_lat).
    Raises ValueError / FileNotFoundError with a message the
    GUI can show if the zip isn't a usable lon/lat shapefile.
    """
    if not data:
        raise ValueError("Uploaded file is empty.")

    tmp = Path(tempfile.mkdtemp(prefix="dd_shp_"))
    try:
        extract_to = tmp / "out"
        extract_to.mkdir()
        zpath = tmp / "upload.zip"
        zpath.write_bytes(data)

        with zipfile.ZipFile(zpath) as zf:
            _safe_extract(zf, extract_to)

        shps = [
            p for p in extract_to.rglob("*.shp")
            if "__MACOSX" not in p.parts and not p.name.startswith("._")
        ]
        if not shps:
            raise ValueError(
                "No .shp file in that zip. Include the shapefile "
                "and its sidecars (.shx, .dbf, .prj)."
            )
        shps.sort(key=lambda p: p.name.lower())
        shp = shps[0]

        # shapefile_bbox lives on USGS because that's where the
        # header/CRS checks were written. It only reads the file
        # -- it does not call the USGS API.
        bbox = USGSDataSource().shapefile_bbox(str(shp))
        note = shp.name
        if len(shps) > 1:
            note = (
                f"{shp.name} (zip had {len(shps)} .shp files; "
                "used the first)"
            )
        return bbox, note
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract zip members, refusing paths that escape dest."""
    root = dest.resolve()
    for info in zf.infolist():
        name = info.filename
        if not name or name.endswith("/"):
            continue
        # Zip-slip: "../" or absolute names must not leave dest.
        target = (dest / name).resolve()
        if target != root and root not in target.parents:
            raise ValueError(f"Unsafe path in zip: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            out.write(src.read())
