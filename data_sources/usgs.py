"""
USGS Water Data source (the modernized NWIS APIs).

Uses the OGC API v1 at https://api.waterdata.usgs.gov/ogcapi/v1
instead of the legacy waterservices.usgs.gov endpoints.

Done so far:
    get_sites()                -- find monitoring locations
    get_site()                 -- one location by id
    get_sites_from_shapefile() -- locations in a shapefile's bbox
    get_available_parameters() -- list downloadable series at a site

TODO:
    get_data()                 -- download selected series

Notes to self:
    - GeoJSON coordinates come back as [longitude, latitude].
    - The API filters states by FIPS code ("41"), not by postal
      code ("OR"), so I translate that in _state_to_fips().
    - get_sites() only pulls location metadata, no time series.
"""

import os
import struct
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import pandas as pd
import requests

from .base import BaseDataSource, DataPoint, SiteInfo


# =========================================================
# STATE LOOKUP TABLES
# =========================================================
# (postal abbreviation, ANSI/FIPS code, full name)
# One table, then I derive the lookups I need from it below
# instead of maintaining three separate copies.
_STATE_TABLE = [
    ("AL", "01", "Alabama"), ("AK", "02", "Alaska"),
    ("AZ", "04", "Arizona"), ("AR", "05", "Arkansas"),
    ("CA", "06", "California"), ("CO", "08", "Colorado"),
    ("CT", "09", "Connecticut"), ("DE", "10", "Delaware"),
    ("DC", "11", "District of Columbia"), ("FL", "12", "Florida"),
    ("GA", "13", "Georgia"), ("HI", "15", "Hawaii"),
    ("ID", "16", "Idaho"), ("IL", "17", "Illinois"),
    ("IN", "18", "Indiana"), ("IA", "19", "Iowa"),
    ("KS", "20", "Kansas"), ("KY", "21", "Kentucky"),
    ("LA", "22", "Louisiana"), ("ME", "23", "Maine"),
    ("MD", "24", "Maryland"), ("MA", "25", "Massachusetts"),
    ("MI", "26", "Michigan"), ("MN", "27", "Minnesota"),
    ("MS", "28", "Mississippi"), ("MO", "29", "Missouri"),
    ("MT", "30", "Montana"), ("NE", "31", "Nebraska"),
    ("NV", "32", "Nevada"), ("NH", "33", "New Hampshire"),
    ("NJ", "34", "New Jersey"), ("NM", "35", "New Mexico"),
    ("NY", "36", "New York"), ("NC", "37", "North Carolina"),
    ("ND", "38", "North Dakota"), ("OH", "39", "Ohio"),
    ("OK", "40", "Oklahoma"), ("OR", "41", "Oregon"),
    ("PA", "42", "Pennsylvania"), ("RI", "44", "Rhode Island"),
    ("SC", "45", "South Carolina"), ("SD", "46", "South Dakota"),
    ("TN", "47", "Tennessee"), ("TX", "48", "Texas"),
    ("UT", "49", "Utah"), ("VT", "50", "Vermont"),
    ("VA", "51", "Virginia"), ("WA", "53", "Washington"),
    ("WV", "54", "West Virginia"), ("WI", "55", "Wisconsin"),
    ("WY", "56", "Wyoming"), ("AS", "60", "American Samoa"),
    ("GU", "66", "Guam"), ("MP", "69", "Northern Mariana Islands"),
    ("PR", "72", "Puerto Rico"), ("VI", "78", "Virgin Islands"),
]

# Derived lookups, e.g. "OR" -> "41", "41" -> "OR", "oregon" -> "41"
_STATE_ABBR_TO_FIPS = {abbr: fips for abbr, fips, _ in _STATE_TABLE}
_STATE_FIPS_TO_ABBR = {fips: abbr for abbr, fips, _ in _STATE_TABLE}
_STATE_NAME_TO_FIPS = {name.lower(): fips for _, fips, name in _STATE_TABLE}


class USGSDataSource(BaseDataSource):
    """USGS Water Data (NWIS) data source.

    Example:
        usgs = USGSDataSource()
        sites = usgs.get_sites(state="OR", site_type_code="ST")
    """

    # Page size for API requests. Just a performance knob, the
    # pagination in _fetch_all_features() handles the rest.
    DEFAULT_PAGE_LIMIT = 1000

    # Extra filters get_sites() will pass through to the API.
    # I check against this list so a typo (site_typ=) errors out
    # instead of silently returning every site in the state.
    _SUPPORTED_SITE_KWARGS = {
        "agency_code",
        "site_type_code",
        "hydrologic_unit_code",
        "county_code",
        "limit",
    }

    def __init__(self, timeout: int = 30, api_key: Optional[str] = None):
        """Initialize the USGS data source.

        timeout: seconds to wait on an API response before
            giving up (no timeout = a hung server hangs me too).
        api_key: optional USGS API key. Falls back to
            config.USGS_API_KEY (.env), then the USGS_API_KEY
            environment variable. No key anywhere = anonymous,
            which still works, just ~50 requests/hour instead
            of ~1,000 with a key.
        """
        super().__init__()  # logger + cache from BaseDataSource

        self.timeout = timeout

        # Figure out the key once here so all later requests just
        # carry it. Order: argument, then config, then env var.
        # Blank strings count as no key (an empty USGS_API_KEY=
        # line in .env shouldn't send a blank key to USGS).
        self._api_key = self._resolve_api_key(api_key)

        # Session so connections get reused across paginated
        # requests and headers only have to be set once.
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/geo+json, application/json",
            "User-Agent": "DataDownloader USGSDataSource",
        })

        if self._api_key:
            # Send it as a header, not ?api_key= in the URL --
            # URLs end up in logs, headers don't. Never log the key.
            self.session.headers["X-Api-Key"] = self._api_key
            self.logger.info(
                "USGS API key loaded (higher rate limit applies)"
            )
        else:
            self.logger.info(
                "No USGS API key configured; connecting anonymously "
                "(~50 requests/hour). Add USGS_API_KEY to .env for "
                "the higher limit -- see .env.example."
            )

    @staticmethod
    def _resolve_api_key(api_key: Optional[str]) -> Optional[str]:
        """Return the first non-blank API key found, else None."""
        if api_key and api_key.strip():
            return api_key.strip()

        try:
            # Imported here, not at the top, so data_sources still
            # imports if it's ever used outside this project layout.
            from config import USGS_API_KEY as config_api_key
        except ImportError:
            config_api_key = None

        if config_api_key and config_api_key.strip():
            return config_api_key.strip()

        env_key = os.getenv("USGS_API_KEY")
        if env_key and env_key.strip():
            return env_key.strip()

        return None

    @property
    def has_api_key(self) -> bool:
        """True if an API key is configured (the key is not exposed)."""
        return self._api_key is not None

    # ---------------------------------------------------------
    # ABSTRACT PROPERTIES (required by BaseDataSource)
    # ---------------------------------------------------------

    @property
    def source_name(self) -> str:
        """Return the name of this data source."""
        return "USGS"

    @property
    def base_url(self) -> str:
        """Return the base URL for this API."""
        return "https://api.waterdata.usgs.gov/ogcapi/v1"

    # ---------------------------------------------------------
    # SITE DISCOVERY
    # ---------------------------------------------------------

    def get_sites(
        self,
        state: Optional[str] = None,
        bbox: Optional[tuple] = None,
        site_ids: Optional[List[str]] = None,
        **kwargs
    ) -> List[SiteInfo]:
        """
        Get available USGS monitoring locations.

        state: two-letter postal code ("OR"), a full state name
            ("Oregon"), or a two-digit FIPS code ("41"). All three
            are translated to the FIPS code the API requires.
        bbox: bounding box (min_lon, min_lat, max_lon, max_lat).
        site_ids: specific locations, either as bare numbers
            ("14211400") or full USGS ids ("USGS-14211400").
            When given, these are fetched directly and the
            state/bbox filters are not used.
        **kwargs: optional USGS filters -- agency_code,
            site_type_code (e.g. "ST" for stream sites),
            hydrologic_unit_code, county_code, and limit
            (page size used while following pagination).

        returns a list of SiteInfo objects
        """
        unknown = set(kwargs) - self._SUPPORTED_SITE_KWARGS
        if unknown:
            raise ValueError(
                f"Unsupported get_sites() argument(s): {sorted(unknown)}. "
                f"Supported arguments: {sorted(self._SUPPORTED_SITE_KWARGS)}"
            )

        # The cache key captures every input that changes the result.
        # Sorting kwargs makes {"a": 1, "b": 2} and {"b": 2, "a": 1}
        # (same meaning) share one cache entry.
        cache_key = (
            f"sites|state={state}|bbox={bbox}|"
            f"site_ids={site_ids}|kwargs={sorted(kwargs.items())}"
        )
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        if site_ids:
            features = [self._fetch_site_by_id(site_id) for site_id in site_ids]
        else:
            params = self._build_site_params(state=state, bbox=bbox, **kwargs)
            features = self._fetch_all_features(params)

        sites = [self._feature_to_site(feature) for feature in features]

        self.logger.info(f"Found {len(sites):,} USGS monitoring location(s)")
        self._set_cached(cache_key, sites)
        return sites

    # ---------------------------------------------------------
    # SITE SELECTION
    # ---------------------------------------------------------
    # Three ways I actually pick gauges: one by id, a list of ids,
    # or everything in an area. Keeping these as plain id / list /
    # bbox calls for now -- if I build the map GUI later it can
    # call these same methods (click = one id, drawn box = bbox).

    def get_site(self, site_id: str) -> SiteInfo:
        """Get one monitoring location by id.

        site_id: bare number ("14211400") or full id
            ("USGS-14211400"). Just a wrapper so I don't have to
            unwrap a one-item list for the single-gauge case.
        """
        return self.get_sites(site_ids=[site_id])[0]

    def get_sites_from_shapefile(
        self,
        shapefile_path: str,
        **kwargs
    ) -> List[SiteInfo]:
        """Get monitoring locations within a shapefile's bbox.

        I use this with watershed boundary shapefiles. It reads
        the bbox out of the shapefile and queries that rectangle,
        so sites near the corners can fall outside the actual
        polygon. Exact point-in-polygon filtering is TODO for
        whenever I bring in a geometry library.

        shapefile_path: path to the .shp file (.shx/.dbf/.prj
            sidecars expected next to it). get_sites() filters
            like site_type_code can be passed as kwargs.
        """
        bbox = self.shapefile_bbox(shapefile_path)
        self.logger.info(f"Shapefile bounding box: {bbox}")
        return self.get_sites(bbox=bbox, **kwargs)

    def shapefile_bbox(self, shapefile_path: str) -> Tuple[float, float, float, float]:
        """Read the bounding box stored in a shapefile's header.

        The .shp header is 100 bytes and bytes 36-67 hold the
        bbox as four little-endian doubles (Xmin, Ymin, Xmax,
        Ymax), so I can get it with struct and skip pulling in a
        GIS library just for this. "<" = little-endian, "4d" =
        four doubles.

        I validate the result as lon/lat. A projected shapefile
        (State Plane etc., big foot/metre values) would otherwise
        quietly query the wrong place on Earth, so those fail
        here until I add reprojection support.
        """
        path = Path(shapefile_path)

        if path.suffix.lower() != ".shp":
            raise ValueError(f"Expected a .shp file, got: {path}")
        if not path.is_file():
            raise FileNotFoundError(f"Shapefile not found: {path}")

        with open(path, "rb") as file:
            header = file.read(100)

        if len(header) < 100:
            raise ValueError(f"File is too small to be a shapefile: {path}")

        # Bytes 0-3: file code, big-endian (">i"), always 9994.
        # Cheap check that I actually got a shapefile.
        file_code = struct.unpack_from(">i", header, 0)[0]
        if file_code != 9994:
            raise ValueError(f"Not a shapefile (bad file code): {path}")

        xmin, ymin, xmax, ymax = struct.unpack_from("<4d", header, 36)

        if not (xmin <= xmax and ymin <= ymax):
            raise ValueError(f"Shapefile has an invalid bounding box: {path}")
        if not (-180 <= xmin <= 180 and -180 <= xmax <= 180
                and -90 <= ymin <= 90 and -90 <= ymax <= 90):
            raise ValueError(
                "Shapefile bounding box is not in longitude/latitude "
                f"coordinates: {(xmin, ymin, xmax, ymax)}. The file "
                "is likely in a projected coordinate system; "
                "reproject it to WGS84 (EPSG:4326) before use. "
                "Automatic reprojection is a planned future feature."
            )

        self._check_shapefile_crs(path)
        return (xmin, ymin, xmax, ymax)

    def _check_shapefile_crs(self, shp_path: Path) -> None:
        """Check the shapefile's .prj file if there is one.

        Projected CRSs (WKT starting with PROJCS) get rejected.
        No .prj at all = just a warning, since the lon/lat range
        check already passed I'll assume WGS84, but I want the
        log to say I assumed it.
        """
        prj_path = shp_path.with_suffix(".prj")
        if not prj_path.is_file():
            self.logger.warning(
                f"No .prj file alongside {shp_path.name}; "
                "assuming WGS84 (EPSG:4326) coordinates."
            )
            return

        wkt = prj_path.read_text(errors="ignore").strip().upper()
        if wkt.startswith("PROJCS"):
            raise ValueError(
                f"Shapefile uses a projected coordinate system "
                f"({prj_path}). Reproject it to WGS84 (EPSG:4326) "
                "before use; automatic reprojection is planned."
            )
        # GEOGCS[...] (a geographic system such as WGS84/NAD83) is
        # close enough for site discovery purposes.

    def _build_site_params(
        self,
        state: Optional[str] = None,
        bbox: Optional[tuple] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Build the USGS query parameters for a site search."""
        params: Dict[str, Any] = {
            "f": "json",
            "limit": kwargs.pop("limit", self.DEFAULT_PAGE_LIMIT),
        }

        if params["limit"] < 1:
            raise ValueError("limit must be at least 1")

        if state is not None:
            params["state_code"] = self._state_to_fips(state)

        if bbox is not None:
            if len(bbox) != 4:
                raise ValueError(
                    "bbox must be (min_lon, min_lat, max_lon, max_lat)"
                )
            # The API expects a comma-separated string. str() on each
            # value keeps ints and floats both working.
            params["bbox"] = ",".join(str(value) for value in bbox)

        # Remaining kwargs are already USGS parameter names.
        params.update(kwargs)
        return params

    @staticmethod
    def _state_to_fips(state: str) -> str:
        """Translate 'OR' / 'Oregon' / '41' to the FIPS code '41'."""
        text = str(state).strip()

        if text.upper() in _STATE_ABBR_TO_FIPS:
            return _STATE_ABBR_TO_FIPS[text.upper()]
        if text.lower() in _STATE_NAME_TO_FIPS:
            return _STATE_NAME_TO_FIPS[text.lower()]
        # Zero-pad so a numeric 41 or "41" both become "41".
        if text.isdigit() and text.zfill(2) in _STATE_FIPS_TO_ABBR:
            return text.zfill(2)

        raise ValueError(
            f"Unrecognized state: {state!r}. Use a postal code "
            "('OR'), a state name ('Oregon'), or a FIPS code ('41')."
        )

    def _fetch_all_features(
        self,
        params: Dict[str, Any],
        collection: str = "monitoring-locations",
    ) -> List[Dict[str, Any]]:
        """Fetch every page of an OGC collection query.

        Responses come back with at most `limit` features plus a
        rel="next" link (with a cursor token in it) when there's
        another page. I follow those links until there isn't one,
        rather than building offset URLs myself.

        collection: "monitoring-locations" for sites,
            "time-series-metadata" for parameters. Same
            pagination either way, hence the shared helper.
        """
        url: Optional[str] = f"{self.base_url}/collections/{collection}/items"
        features: List[Dict[str, Any]] = []

        while url:
            page = self._get_json(url, params=params)
            features.extend(page.get("features", []))

            # Find the "next page" link, if this was not the last page.
            url = next(
                (link.get("href") for link in page.get("links", [])
                 if link.get("rel") == "next"),
                None,
            )
            # Query parameters are already embedded in the next
            # link's href, so they must not be sent a second time.
            params = None

        return features

    def _fetch_site_by_id(self, site_id: str) -> Dict[str, Any]:
        """Fetch one monitoring location directly by its id."""
        normalized = self._normalize_site_id(site_id)
        # quote() makes the id safe to embed in a URL path.
        url = (
            f"{self.base_url}/collections/monitoring-locations"
            f"/items/{quote(normalized, safe='')}"
        )
        return self._get_json(url, params={"f": "json"})

    @staticmethod
    def _normalize_site_id(site_id: str) -> str:
        """Normalize '14211400' to the full id 'USGS-14211400'.

        Ids are always kept as strings: site numbers can have
        leading zeros, and int("01421000") would silently lose one.
        An id that already contains a hyphen is assumed to already
        be in agency-number form and is kept as supplied.
        """
        text = str(site_id).strip()
        if "-" in text:
            return text
        return f"USGS-{text}"

    def _get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """GET a URL and return parsed JSON, raising on HTTP errors."""
        self.logger.debug(f"GET {url} params={params}")
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            # Turn 4xx/5xx responses into an exception immediately,
            # instead of discovering later that an error page is
            # not valid JSON.
            response.raise_for_status()
        except requests.RequestException as exc:
            self.logger.error(f"USGS request failed: {exc}")
            raise
        return response.json()

    @staticmethod
    def _feature_to_site(feature: Dict[str, Any]) -> SiteInfo:
        """Convert one GeoJSON feature into a SiteInfo.

        All the USGS-specific field names get translated here so
        nothing else in the project has to know them.
        """
        props = feature.get("properties", {})

        # GeoJSON Point coordinates are [longitude, latitude],
        # and some locations have no geometry at all.
        coordinates = (feature.get("geometry") or {}).get("coordinates") or [None, None]
        longitude, latitude = coordinates[0], coordinates[1]

        state_fips = props.get("state_code")

        return SiteInfo(
            # Other USGS endpoints want the full id
            # ("USGS-14211400") as monitoring_location_id, so
            # that's what I keep as site_id, not the bare number.
            site_id=props.get("id", ""),
            name=props.get("monitoring_location_name", ""),
            latitude=latitude,
            longitude=longitude,
            source="USGS",
            # Postal code back out of the FIPS code when I can.
            state=_STATE_FIPS_TO_ABBR.get(state_fips, props.get("state_name")),
            county=props.get("county_name"),
            elevation_ft=props.get("altitude"),
            # USGS stuff SiteInfo has no field for -> metadata.
            metadata={
                "monitoring_location_number": props.get("monitoring_location_number"),
                "agency_code": props.get("agency_code"),
                "agency_name": props.get("agency_name"),
                "site_type_code": props.get("site_type_code"),
                "site_type": props.get("site_type"),
                "hydrologic_unit_code": props.get("hydrologic_unit_code"),
                "drainage_area": props.get("drainage_area"),
                "contributing_drainage_area": props.get("contributing_drainage_area"),
                "time_zone_abbreviation": props.get("time_zone_abbreviation"),
                "vertical_datum": props.get("vertical_datum"),
            },
        )

    # ---------------------------------------------------------
    # PARAMETER / SERIES DISCOVERY
    # ---------------------------------------------------------
    # One parameter at a site is usually several series:
    # discharge (00060) might be instantaneous readings, a daily
    # mean, a daily max... statistic_id / computation_identifier
    # are what tell them apart. So each dict here is one series,
    # with its begin/end so I know the period of record before
    # I try downloading anything from it.

    def get_available_parameters(self, site_id: str) -> List[Dict[str, str]]:
        """
        Get list of available parameters (series) at a site.

        site_id: bare number ("14211400") or full id
            ("USGS-14211400").

        returns a list of dicts, one per downloadable series, with
        keys: site_id, code, name, unit, statistic_id, computation,
        begin, end, time_series_id, primary, description,
        sublocation, web_description. I need those last two --
        some sites have upper/middle/bottom sensors for the same
        parameter and that's the only way to tell them apart.
        All values are strings ("" when USGS has none), sorted by
        code then computation so the list reads in a sane order.
        """
        normalized = self._normalize_site_id(site_id)

        cache_key = f"parameters|site={normalized}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        features = self._fetch_all_features(
            params={
                "f": "json",
                "limit": self.DEFAULT_PAGE_LIMIT,
                "monitoring_location_id": normalized,
            },
            collection="time-series-metadata",
        )

        parameters = [self._feature_to_parameter(f) for f in features]
        parameters.sort(key=lambda p: (p["code"], p["computation"], p["statistic_id"]))

        if not parameters:
            # Empty is a real answer (site exists, no series in
            # this collection) -- just log it loudly so I notice.
            self.logger.warning(
                f"No time series found for {normalized}. The site "
                "may be discontinued or publish no continuous data."
            )
        else:
            self.logger.info(
                f"Found {len(parameters):,} available series at {normalized}"
            )

        self._set_cached(cache_key, parameters)
        return parameters

    def get_available_parameters_for_sites(
        self,
        site_ids: List[str],
    ) -> List[Dict[str, str]]:
        """Available series for several sites, in one combined list.

        Batch version of get_available_parameters(). Every dict
        carries its site_id, so the combined list still says
        which site each series belongs to.
        """
        combined: List[Dict[str, str]] = []
        for site_id in site_ids:
            combined.extend(self.get_available_parameters(site_id))
        return combined

    def available_parameters_dataframe(self, site_ids: List[str]) -> pd.DataFrame:
        """Available series for one or more sites, as a DataFrame.

        Same list as get_available_parameters_for_sites(), just
        in the form I actually want for browsing options, saving
        a catalogue CSV, or (later) showing in a GUI table.
        """
        records = self.get_available_parameters_for_sites(site_ids)
        columns = [
            "site_id", "code", "name", "unit", "statistic_id",
            "computation", "begin", "end", "time_series_id",
            "primary", "description", "sublocation", "web_description",
        ]
        if not records:
            # Still return the columns, so anything using this
            # doesn't blow up on an empty result.
            return pd.DataFrame(columns=columns)
        return pd.DataFrame.from_records(records, columns=columns)

    @staticmethod
    def _feature_to_parameter(feature: Dict[str, Any]) -> Dict[str, str]:
        """Convert one time-series-metadata feature to a plain dict.

        Everything gets stringified: USGS returns None for some
        fields (statistic_id on instantaneous series, for one),
        and I don't want "00060" ever turning into the int 60
        and losing its leading zeros.
        """
        props = feature.get("properties", {})

        def text(key: str) -> str:
            value = props.get(key)
            return "" if value is None else str(value)

        return {
            "site_id": text("monitoring_location_id"),
            "code": text("parameter_code"),
            "name": text("parameter_name"),
            "unit": text("unit_of_measure"),
            "statistic_id": text("statistic_id"),
            "computation": text("computation_identifier"),
            "begin": text("begin"),
            "end": text("end"),
            "time_series_id": text("id"),
            "primary": text("primary"),
            "description": text("parameter_description"),
            "sublocation": text("sublocation_identifier"),
            "web_description": text("web_description"),
        }

    # ---------------------------------------------------------
    # TODO: DATA DOWNLOAD (not implemented yet)
    # ---------------------------------------------------------
    # Has to exist or BaseDataSource won't let me instantiate
    # this class at all (abstractmethod). Raising for now --
    # I'd rather see an error than a fake empty result that
    # looks like "no data available".

    def get_data(
        self,
        site_ids: List[str],
        parameter: str,
        start_date: datetime,
        end_date: datetime,
        **kwargs
    ) -> List[DataPoint]:
        """
        Get time series data.

        TODO: implement this next. Start with one site / one
        parameter as a smoke test, then expand from there.
        """
        raise NotImplementedError("USGS get_data() is not implemented yet.")
