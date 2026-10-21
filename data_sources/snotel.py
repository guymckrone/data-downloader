"""
NRCS SNOTEL source (AWDB REST API).

Uses https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1
instead of the older SOAP service.

Done so far:
    get_sites()                -- SNOTEL stations as SiteInfo
    get_available_parameters() -- elements measured at a station
    get_data()                 -- download element data

TODO:
    all-elements mode (same parity step USGS/Aquarius got)

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

from datetime import date, datetime
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

    # Default chunk sizes for get_data(), same reasoning as
    # USGS: hourly data is dense (24 readings/day), daily is
    # one value a day so a decade per request is still small.
    HOURLY_CHUNK_YEARS = 1
    DAILY_CHUNK_YEARS = 10

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
    # DATA DOWNLOAD
    # ---------------------------------------------------------

    # Extra names I might type that should map to a code.
    _EXTRA_ALIASES = {
        "swe": "WTEQ",
        "snow_water_equivalent": "WTEQ",
        "snow_depth": "SNWD",
        "soil_moisture": "SMS",
        "soil_temperature": "STO",
        "precipitation_accumulation": "PREC",
        "air_temperature": "TOBS",
    }

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

        site_ids: one or more stations, triplets or bare ids
            (bare ids can take state= in kwargs).
        parameter: element code ("WTEQ") or a friendly name
            ("Snow Water Equivalent", "soil moisture", ...).
        start_date / end_date: datetime, date, or ISO string.
            AWDB works in whole days, so these get sent as
            YYYY-MM-DD regardless of any time I pass.

        kwargs:
            duration: "DAILY" (default), "HOURLY", "MONTHLY",
                etc. -- whatever the station catalogue lists.
            ordinal: sensor number (default 1, the primary
                sensor). Soil stations can have several; check
                the catalogue and pass this to pick another.
            state: state code for building triplets out of
                bare station ids.
            chunk_years: split the date range into chunks of
                this many years (one request per chunk).
                Defaults: 1 year for HOURLY, 10 for everything
                else. Long records need this -- one request
                for 40 years of hourly data is asking for a
                timeout.

        All sites go in each request together -- AWDB accepts
        a list of triplets, unlike USGS where I loop per site.

        returns a list of DataPoint objects, oldest first.
        """
        duration = str(kwargs.pop("duration", "DAILY")).upper()
        ordinal = kwargs.pop("ordinal", 1)
        state = kwargs.pop("state", None)
        chunk_years = kwargs.pop("chunk_years", None)
        if kwargs:
            raise ValueError(
                f"Unsupported get_data() argument(s): {sorted(kwargs)}. "
                "Supported: duration, ordinal, state, chunk_years"
            )
        if chunk_years is not None and (
            not isinstance(chunk_years, int) or chunk_years < 1
        ):
            raise ValueError("chunk_years must be a positive integer")

        element_code = self._resolve_element_code(parameter)
        triplets = [
            self._normalize_triplet(site_id, state=state)
            for site_id in site_ids
        ]
        start_moment = self._coerce_datetime(start_date, "start_date")
        end_moment = self._coerce_datetime(end_date, "end_date")
        if end_moment < start_moment:
            raise ValueError("end_date is before start_date")

        if chunk_years is None:
            chunk_years = (
                self.HOURLY_CHUNK_YEARS if duration == "HOURLY"
                else self.DAILY_CHUNK_YEARS
            )
        ranges = list(self._chunk_ranges(start_moment, end_moment, chunk_years))
        if len(ranges) > 1:
            self.logger.info(
                f"{element_code} ({duration}): downloading in "
                f"{len(ranges)} chunks of {chunk_years} year(s)"
            )

        points: List[DataPoint] = []
        skipped = 0
        for chunk_start, chunk_end in ranges:
            response = self._get_json(
                f"{self.base_url}/data",
                params={
                    "stationTriplets": ",".join(triplets),
                    "elements": element_code,
                    "ordinal": str(ordinal),
                    "duration": duration,
                    "beginDate": chunk_start.date().isoformat(),
                    "endDate": chunk_end.date().isoformat(),
                    "periodRef": "END",
                    "centralTendencyType": "NONE",
                    "returnFlags": "true",
                    "returnOriginalValues": "false",
                    "returnSuspectData": "false",
                    "alwaysReturnDailyFeb29": "false",
                },
            )

            for station_data in response or []:
                if station_data.get("error"):
                    raise ValueError(
                        f"AWDB error for "
                        f"{station_data.get('stationTriplet')}: "
                        f"{station_data['error']}"
                    )
                triplet = station_data.get("stationTriplet", "")
                for element_data in station_data.get("data") or []:
                    element_info = element_data.get("stationElement", {})
                    for raw_value in element_data.get("values") or []:
                        point = self._value_to_datapoint(
                            raw_value, triplet, element_info
                        )
                        if point is None:
                            skipped += 1
                        else:
                            points.append(point)

        # Chunk boundaries are inclusive at both ends, so the
        # boundary day/hour comes back twice. Dedupe on the
        # full series identity, not just the timestamp -- two
        # stations share timestamps all the time.
        unique = {
            (p.timestamp, p.location_id, p.parameter, p.unit): p
            for p in points
        }
        duplicates = len(points) - len(unique)
        points = sorted(
            unique.values(), key=lambda p: (p.timestamp, p.location_id)
        )

        self.logger.info(
            f"{element_code} ({duration}): {len(points):,} points "
            f"from {len(triplets)} station(s) "
            f"({start_moment.date()} to {end_moment.date()})"
            + (f", {skipped} missing values skipped" if skipped else "")
            + (f", {duplicates} boundary duplicates dropped"
               if duplicates else "")
        )
        return points

    @staticmethod
    def _add_years(moment: datetime, years: int) -> datetime:
        """Shift by whole years; Feb 29 falls back to Feb 28."""
        try:
            return moment.replace(year=moment.year + years)
        except ValueError:  # Feb 29 -> non-leap target year
            return moment.replace(year=moment.year + years, day=28)

    @staticmethod
    def _chunk_ranges(start: datetime, end: datetime, years: int):
        """Yield (chunk_start, chunk_end) pairs covering a range.

        Same chunking pattern as the other two sources. Yes,
        this is the third copy of this helper -- if a fourth
        source ever shows up, that's my cue to pull it into
        base.py instead of copying it again.
        """
        if start == end:
            yield start, end
            return
        chunk_start = start
        while chunk_start < end:
            chunk_end = min(
                SNOTELDataSource._add_years(chunk_start, years), end
            )
            yield chunk_start, chunk_end
            chunk_start = chunk_end

    @staticmethod
    def _resolve_element_code(parameter: str) -> str:
        """Turn "WTEQ" / "Snow Water Equivalent" into "WTEQ"."""
        text = str(parameter).strip()
        if text.upper() in ELEMENT_NAMES or text.isupper():
            # Codes are short and uppercase; anything all-caps
            # I treat as a code even if it's not in my friendly
            # name table (AWDB has far more codes than I listed).
            return text.upper()
        key = text.lower().replace(" ", "_").replace("-", "_")
        if key in SNOTELDataSource._EXTRA_ALIASES:
            return SNOTELDataSource._EXTRA_ALIASES[key]
        for code, name in ELEMENT_NAMES.items():
            if name.lower() == text.lower():
                return code
        raise ValueError(
            f"Unknown element: {parameter!r}. Pass an AWDB "
            f"element code (WTEQ, SNWD, SMS, ...) or one of: "
            f"{sorted(set(ELEMENT_NAMES.values()))}"
        )

    @staticmethod
    def _coerce_datetime(value, name: str) -> datetime:
        """Turn a date/datetime/string into a datetime."""
        if isinstance(value, datetime):
            moment = value
        elif isinstance(value, date):
            moment = datetime(value.year, value.month, value.day)
        elif isinstance(value, str):
            try:
                moment = datetime.fromisoformat(value)
            except ValueError:
                raise ValueError(
                    f"{name} isn't a valid ISO date/datetime: {value!r}"
                )
        else:
            raise TypeError(
                f"{name} must be a datetime, date, or ISO string, "
                f"got {type(value).__name__}"
            )
        return moment

    @staticmethod
    def _coerce_date_text(value, name: str) -> str:
        """Format a date/datetime/string as YYYY-MM-DD."""
        return SNOTELDataSource._coerce_datetime(value, name).date().isoformat()

    @staticmethod
    def _value_to_datapoint(
        raw_value: Dict[str, Any],
        triplet: str,
        element_info: Dict[str, Any],
    ) -> Optional[DataPoint]:
        """Convert one AWDB value entry to a DataPoint.

        The parameter label carries the depth/ordinal when
        they're not the plain default, so soil moisture at
        -8 in can't get mixed up with soil moisture at -20 in
        in the same DataFrame (same trick as USGS daily labels).
        """
        value = raw_value.get("value")
        if value is None or value == "":
            return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None

        code = element_info.get("elementCode", "")
        label = ELEMENT_NAMES.get(code, code)
        height_depth = element_info.get("heightDepth")
        ordinal = element_info.get("ordinal")
        if height_depth not in (None, "", 0, "0"):
            label = f"{label} ({height_depth} in)"
        if ordinal not in (None, "", 1, "1"):
            label = f"{label} #{ordinal}"

        date_text = str(raw_value.get("date", "")).replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(date_text)

        quality_parts = []
        if raw_value.get("qcFlag"):
            quality_parts.append(f"qc={raw_value['qcFlag']}")
        if raw_value.get("qaFlag"):
            quality_parts.append(f"qa={raw_value['qaFlag']}")

        return DataPoint(
            timestamp=timestamp,
            value=value,
            location_id=triplet,
            parameter=label,
            unit=element_info.get("storedUnitCode", ""),
            source="SNOTEL",
            quality_flag="|".join(quality_parts) if quality_parts else None,
        )
