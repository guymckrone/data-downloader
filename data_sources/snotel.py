"""
NRCS SNOTEL source (AWDB REST API).

Uses https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1
instead of the older SOAP service.

Done so far:
    get_sites()                -- SNOTEL stations as SiteInfo
    get_available_parameters() -- elements measured at a station

TODO:
    get_data() -- download element data (daily/hourly)

Notes to self:
    - Station ids are triplets: "302:OR:SNTL" is
      station:state:network. Most calls want the triplet.
    - The stations endpoint can return each station's element
      list inline (returnStationElements), which is how
      get_available_parameters() works -- no separate call.
    - On the work network this host has the same SSL
      interception thing as Aquarius, so verify_ssl is a
      constructor option (pass False there, like Aquarius).
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from .base import BaseDataSource, DataPoint, SiteInfo


# Friendly names for the element codes I actually care about.
# Anything not in here just shows its code as the name --
# AWDB has hundreds of elements and I'm not typing them all.
ELEMENT_NAMES = {
    "WTEQ": "Snow Water Equivalent",
    "SNWD": "Snow Depth",
    "PREC": "Precipitation Accumulation",
    "PRCP": "Precipitation Increment",
    "TOBS": "Air Temperature Observed",
    "TAVG": "Air Temperature Average",
    "TMAX": "Air Temperature Maximum",
    "TMIN": "Air Temperature Minimum",
    "SMS": "Soil Moisture Percent",
    "STO": "Soil Temperature Observed",
    "SWEQ": "Snow Water Equivalent (derived)",
    "PRC": "Precipitation (period)",
    "BATT": "Battery Voltage",
    "WDIR": "Wind Direction",
    "WSPDX": "Wind Speed Maximum",
    "WSPDV": "Wind Speed Average",
    "SRDO": "Solar Radiation",
    "RHUM": "Relative Humidity",
    "PRES": "Barometric Pressure",
}


class SNOTELDataSource(BaseDataSource):
    """NRCS SNOTEL (AWDB) data source.

    Example:
        snotel = SNOTELDataSource(verify_ssl=False)
        sites = snotel.get_sites(state="OR")
        params = snotel.get_available_parameters("302:OR:SNTL")
    """

    def __init__(self, timeout: int = 90, verify_ssl: bool = True):
        """Initialize the SNOTEL data source.

        timeout: the stations endpoint can be slow (tens of
            seconds for a state), so this defaults higher than
            my USGS timeout.
        verify_ssl: leave True normally; False for networks
            with SSL inspection (work VPN etc.), same reason
            Aquarius runs with it off.
        """
        super().__init__()  # logger + cache from BaseDataSource
        self.timeout = timeout
        self.verify_ssl = verify_ssl

        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "DataDownloader SNOTELDataSource",
        })
        if not verify_ssl:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            self.logger.warning("SSL verification disabled")

    # ---------------------------------------------------------
    # ABSTRACT PROPERTIES (required by BaseDataSource)
    # ---------------------------------------------------------

    @property
    def source_name(self) -> str:
        """Return the name of this data source."""
        return "SNOTEL"

    @property
    def base_url(self) -> str:
        """Return the base URL for this API."""
        return "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"

    # ---------------------------------------------------------
    # STATION DISCOVERY
    # ---------------------------------------------------------

    def get_sites(
        self,
        state: Optional[str] = None,
        bbox: Optional[tuple] = None,
        site_ids: Optional[List[str]] = None,
        **kwargs
    ) -> List[SiteInfo]:
        """
        Get available SNOTEL stations.

        state: two-letter state code ("OR"). Without it (and
            without site_ids), this pulls every SNOTEL station,
            which works but is slow.
        bbox: (min_lon, min_lat, max_lon, max_lat). The stations
            endpoint doesn't do bbox for me, so I filter the
            returned stations by their lat/lon myself.
        site_ids: station triplets ("302:OR:SNTL") or bare ids
            ("302" -- needs state= to build the triplet, or I
            wildcard the state part).
        **kwargs: network_code (default "SNTL"; "SCAN" also
            lives in AWDB), active_only=True for active only.

        returns a list of SiteInfo objects
        """
        network_code = str(kwargs.pop("network_code", "SNTL")).upper()
        active_only = kwargs.pop("active_only", False)
        if kwargs:
            raise ValueError(
                f"Unsupported get_sites() argument(s): {sorted(kwargs)}. "
                "Supported: network_code, active_only"
            )
        if bbox is not None and len(bbox) != 4:
            raise ValueError(
                "bbox must be (min_lon, min_lat, max_lon, max_lat)"
            )

        if site_ids:
            triplets = [
                self._normalize_triplet(site_id, state=state,
                                        network_code=network_code)
                for site_id in site_ids
            ]
        else:
            state_part = str(state).strip().upper() if state else "*"
            triplets = [f"*:{state_part}:{network_code}"]

        # bbox has to be in the key: I cache the filtered list,
        # so two calls with the same triplets but different
        # bboxes are different results. (First version of this
        # key forgot bbox and a bbox call happily returned the
        # whole state's cached stations.)
        cache_key = (
            f"snotel_sites|triplets={triplets}|active={active_only}"
            f"|bbox={bbox}"
        )
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        stations = self._fetch_stations(
            triplets=triplets, active_only=active_only,
            include_elements=False,
        )
        sites = [self._station_to_site(s) for s in stations]

        if bbox is not None:
            min_lon, min_lat, max_lon, max_lat = bbox
            sites = [
                s for s in sites
                if s.latitude is not None and s.longitude is not None
                and min_lon <= s.longitude <= max_lon
                and min_lat <= s.latitude <= max_lat
            ]

        self.logger.info(f"Found {len(sites):,} SNOTEL station(s)")
        self._set_cached(cache_key, sites)
        return sites

    def get_site(self, site_id: str, **kwargs) -> SiteInfo:
        """Get one station by triplet or bare id."""
        sites = self.get_sites(site_ids=[site_id], **kwargs)
        if not sites:
            raise ValueError(f"No SNOTEL station with id {site_id!r}")
        return sites[0]

    @staticmethod
    def _normalize_triplet(
        site_id: str,
        state: Optional[str] = None,
        network_code: str = "SNTL",
    ) -> str:
        """Turn "302" into a triplet pattern AWDB understands.

        Full triplets pass through as-is. A bare id gets the
        given state (or a * wildcard -- AWDB triplet patterns
        support wildcards, so "302:*:SNTL" still finds it).
        """
        text = str(site_id).strip()
        if text.count(":") == 2:
            return text.upper()
        state_part = str(state).strip().upper() if state else "*"
        return f"{text}:{state_part}:{network_code.upper()}"

    def _fetch_stations(
        self,
        triplets: List[str],
        active_only: bool = False,
        include_elements: bool = False,
    ) -> List[Dict[str, Any]]:
        """Call the stations endpoint for the given triplets."""
        params = {
            "stationTriplets": ",".join(triplets),
            "activeOnly": str(active_only).lower(),
            "returnStationElements": str(include_elements).lower(),
            "returnForecastPointMetadata": "false",
            "returnReservoirMetadata": "false",
        }
        return self._get_json(f"{self.base_url}/stations", params=params)

    def _get_json(self, url: str, params: Dict[str, Any]) -> Any:
        """GET a URL and return parsed JSON, raising on HTTP errors."""
        self.logger.debug(f"GET {url} params={params}")
        try:
            response = self.session.get(
                url, params=params, timeout=self.timeout,
                verify=self.verify_ssl,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            self.logger.error(f"SNOTEL request failed: {exc}")
            raise
        return response.json()

    @staticmethod
    def _station_to_site(station: Dict[str, Any]) -> SiteInfo:
        """Convert one AWDB station dict into a SiteInfo."""
        return SiteInfo(
            # The triplet is the id every other AWDB call wants.
            site_id=station.get("stationTriplet", ""),
            name=station.get("name", ""),
            latitude=station.get("latitude"),
            longitude=station.get("longitude"),
            source="SNOTEL",
            state=station.get("stateCode"),
            county=station.get("countyName"),
            # AWDB elevation is already in feet. Nice for once.
            elevation_ft=station.get("elevation"),
            metadata={
                "station_number": station.get("stationId"),
                "network_code": station.get("networkCode"),
                "huc": station.get("huc"),
                "operator": station.get("operator"),
                "shef_id": station.get("shefId"),
                "data_time_zone": station.get("dataTimeZone"),
                "begin_date": station.get("beginDate"),
                "end_date": station.get("endDate"),
            },
        )

    # ---------------------------------------------------------
    # ELEMENT DISCOVERY (SNOTEL's version of parameters)
    # ---------------------------------------------------------
    # A station measures "elements" (WTEQ, SNWD, SMS...), and
    # the same element can repeat at different ordinals (sensor
    # 1, sensor 2) and durations (DAILY, HOURLY). Each combo is
    # a separate row here, with its own begin/end -- same
    # "one row per series" idea as the USGS catalogue.

    def get_available_parameters(self, site_id: str) -> List[Dict[str, str]]:
        """
        Get list of available elements at a station.

        site_id: station triplet ("302:OR:SNTL") or bare id
            (with the state wildcarded).

        returns a list of dicts with keys: site_id, code, name,
        unit, duration, ordinal, height_depth, begin, end.
        All values are strings.
        """
        triplet = self._normalize_triplet(site_id)

        cache_key = f"snotel_parameters|site={triplet}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        stations = self._fetch_stations(
            triplets=[triplet], active_only=False, include_elements=True,
        )
        if not stations:
            raise ValueError(f"No SNOTEL station with id {site_id!r}")

        station = stations[0]
        parameters = [
            self._element_to_parameter(station.get("stationTriplet", ""), el)
            for el in station.get("stationElements") or []
        ]
        parameters.sort(key=lambda p: (p["code"], p["duration"], p["ordinal"]))

        if not parameters:
            self.logger.warning(f"No elements found for {triplet}")
        else:
            self.logger.info(
                f"Found {len(parameters):,} elements at {triplet}"
            )

        self._set_cached(cache_key, parameters)
        return parameters

    def get_available_parameters_for_sites(
        self,
        site_ids: List[str],
    ) -> List[Dict[str, str]]:
        """Available elements for several stations, combined."""
        combined: List[Dict[str, str]] = []
        for site_id in site_ids:
            combined.extend(self.get_available_parameters(site_id))
        return combined

    def available_parameters_dataframe(self, site_ids: List[str]) -> pd.DataFrame:
        """Available elements for one or more stations, as a table."""
        records = self.get_available_parameters_for_sites(site_ids)
        columns = [
            "site_id", "code", "name", "unit", "duration",
            "ordinal", "height_depth", "begin", "end",
        ]
        if not records:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame.from_records(records, columns=columns)

    @staticmethod
    def _element_to_parameter(
        site_id: str, element: Dict[str, Any]
    ) -> Dict[str, str]:
        """Convert one stationElements entry to a catalogue dict."""

        def text(key: str) -> str:
            value = element.get(key)
            return "" if value is None else str(value)

        code = text("elementCode")
        return {
            "site_id": site_id,
            "code": code,
            "name": ELEMENT_NAMES.get(code, code),
            "unit": text("storedUnitCode"),
            "duration": text("durationName"),
            "ordinal": text("ordinal"),
            # Soil elements measure at a depth; most elements
            # don't have one, hence "" most of the time.
            "height_depth": text("heightDepth"),
            "begin": text("beginDate"),
            "end": text("endDate"),
        }

    # ---------------------------------------------------------
    # TODO: DATA DOWNLOAD (not implemented yet)
    # ---------------------------------------------------------

    def get_data(
        self,
        site_ids: List[str],
        parameter: str,
        start_date: datetime,
        end_date: datetime,
        **kwargs
    ) -> List[DataPoint]:
        """Get time series data. TODO: not wired up yet."""
        raise NotImplementedError("SNOTEL get_data() is not implemented yet.")
