"""
Aquarius (Portland BES portal) data source.

Retrofit of the standalone aquarius_data_downloader.py into the
BaseDataSource shape, so Aquarius and USGS can sit behind the
same interface (and eventually the same GUI).

Done so far:
    get_sites()                -- portal locations as SiteInfo
    get_available_parameters() -- datasets at a location
    available_datasets_dataframe() -- whole-portal catalogue
    get_data()                 -- download selected datasets
                                  (by site + parameter/label, or
                                  by exact dataset identifier)
    get_all_datasets_data()    -- download every dataset at the
                                  given locations (preview with
                                  preview_all_datasets() first)

The existing download_all_precipitation() flow in
aquarius_data_downloader.py is untouched -- it still does the
bulk precip-to-SQLite job it always did.

Notes to self:
    - Aquarius "series" are datasets. The identifier looks like
      "Precip.15min@HYDRA-1": parameter.label@location.
    - The portal connection only happens when a method is
      called (see _portal), not on init -- I don't want
      creating the object to hit the network.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from .base import BaseDataSource, DataPoint, SiteInfo


class AquariusDataSource(BaseDataSource):
    """Portland BES Aquarius portal, BaseDataSource style.

    Example:
        aquarius = AquariusDataSource()
        sites = aquarius.get_sites()
        catalogue = aquarius.available_parameters_dataframe(
            [sites[0].site_id]
        )
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        verify_ssl: bool = False,
    ):
        """Store connection settings; don't connect yet.

        Anything left as None falls back to config.py (.env)
        when the portal is first created. verify_ssl defaults
        to False to match how the existing downloader is run
        on the work network.
        """
        super().__init__()  # logger + cache from BaseDataSource
        self._base_url = base_url
        self._username = username
        self._password = password
        self._verify_ssl = verify_ssl
        self._portal_instance = None

    # ---------------------------------------------------------
    # CONNECTION (lazy)
    # ---------------------------------------------------------

    def _portal(self):
        """Create (once) and return the AquariusPortal client.

        Imported here, not at the top: aquarius_data_downloader
        pulls in config.py at import time, and I don't want
        importing data_sources to depend on that. Reusing
        AquariusPortal instead of writing a second Aquarius
        client -- it already handles auth and the endpoints.
        """
        if self._portal_instance is None:
            from aquarius_data_downloader import AquariusPortal

            base_url, username, password = (
                self._base_url, self._username, self._password,
            )
            if base_url is None or username is None or password is None:
                from config import BASE_URL, USERNAME, PASSWORD
                base_url = base_url or BASE_URL
                username = username or USERNAME
                password = password or PASSWORD

            self._portal_instance = AquariusPortal(
                base_url=base_url,
                username=username,
                password=password,
                verify_ssl=self._verify_ssl,
            )
        return self._portal_instance

    # ---------------------------------------------------------
    # ABSTRACT PROPERTIES (required by BaseDataSource)
    # ---------------------------------------------------------

    @property
    def source_name(self) -> str:
        """Return the name of this data source."""
        return "Aquarius"

    @property
    def base_url(self) -> str:
        """Return the base URL for this API."""
        if self._base_url:
            return self._base_url
        try:
            from config import BASE_URL
            return BASE_URL or ""
        except ImportError:
            return ""

    # ---------------------------------------------------------
    # RAW PORTAL DATA (cached -- these lists don't change
    # while I'm working, and re-downloading 600+ locations /
    # 2,000+ datasets on every call would be wasteful)
    # ---------------------------------------------------------

    def _locations_raw(self) -> List[Dict[str, Any]]:
        cached = self._get_cached("aquarius_locations")
        if cached is not None:
            return cached
        response = self._portal().get_locations() or {}
        locations = response.get("locations", [])
        self._set_cached("aquarius_locations", locations)
        return locations

    def _datasets_raw(self) -> List[Dict[str, Any]]:
        cached = self._get_cached("aquarius_datasets")
        if cached is not None:
            return cached
        response = self._portal().get_datasets() or {}
        datasets = response.get("datasets", [])
        self._set_cached("aquarius_datasets", datasets)
        return datasets

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
        Get available Aquarius locations.

        The portal is Portland-only, so state/bbox/site_ids are
        applied as filters over the full location list:
        state: only "OR"/"Oregon" makes sense here; anything
            else returns an empty list (with a warning logged).
        bbox: (min_lon, min_lat, max_lon, max_lat), applied to
            the locations' lat/lon.
        site_ids: location ids ("HYDRA-1", ...) to keep.
        **kwargs: active_only=True drops inactive locations,
            site_type="..." matches the portal location type.

        returns a list of SiteInfo objects
        """
        if state is not None and str(state).strip().upper() not in ("OR", "OREGON"):
            self.logger.warning(
                f"Aquarius is a Portland, OR portal; state={state!r} "
                "won't match anything."
            )
            return []

        if bbox is not None and len(bbox) != 4:
            raise ValueError(
                "bbox must be (min_lon, min_lat, max_lon, max_lat)"
            )

        active_only = kwargs.pop("active_only", False)
        site_type = kwargs.pop("site_type", None)
        if kwargs:
            raise ValueError(
                f"Unsupported get_sites() argument(s): {sorted(kwargs)}. "
                "Supported: active_only, site_type"
            )

        sites = [self._location_to_site(loc) for loc in self._locations_raw()]

        if site_ids:
            wanted = {str(site_id) for site_id in site_ids}
            sites = [s for s in sites if s.site_id in wanted]
        if bbox is not None:
            min_lon, min_lat, max_lon, max_lat = bbox
            sites = [
                s for s in sites
                if s.latitude is not None and s.longitude is not None
                and min_lon <= s.longitude <= max_lon
                and min_lat <= s.latitude <= max_lat
            ]
        if active_only:
            sites = [s for s in sites if s.metadata.get("active")]
        if site_type:
            sites = [
                s for s in sites
                if (s.metadata.get("type") or "").lower() == site_type.lower()
            ]

        self.logger.info(f"Found {len(sites):,} Aquarius location(s)")
        return sites

    def get_site(self, site_id: str) -> SiteInfo:
        """Get one location by id (same idea as the USGS one)."""
        sites = self.get_sites(site_ids=[site_id])
        if not sites:
            raise ValueError(f"No Aquarius location with id {site_id!r}")
        return sites[0]

    @staticmethod
    def _location_to_site(location: Dict[str, Any]) -> SiteInfo:
        """Convert one portal location dict into a SiteInfo."""
        # Elevation comes back in metres (elevationUnit says so
        # when it's there). SiteInfo wants feet, so I convert --
        # storing metres in a field named _ft would be a quiet
        # landmine for whoever uses it later. Me, probably.
        elevation_ft = None
        elevation = location.get("elevation")
        if elevation is not None:
            unit_id = (location.get("elevationUnit") or {}).get("id", "m")
            elevation_ft = elevation * 3.28084 if unit_id == "m" else elevation

        tags = [
            tag.get("value") for tag in (location.get("tags") or [])
            if tag.get("value")
        ]

        return SiteInfo(
            site_id=str(location.get("id", "")),
            name=location.get("name", ""),
            latitude=location.get("latitude"),
            longitude=location.get("longitude"),
            source="Aquarius",
            # Portal doesn't give state/county; it's Portland, OR.
            state="OR",
            county=None,
            elevation_ft=elevation_ft,
            metadata={
                "location_number": location.get("locationId"),
                "type": location.get("type"),
                "folder": location.get("folder"),
                "active": location.get("active"),
                "utc_offset": location.get("utcOffset"),
                "tags": tags,
            },
        )

    # ---------------------------------------------------------
    # DATASET DISCOVERY (Aquarius's version of parameters)
    # ---------------------------------------------------------

    def get_available_parameters(self, site_id: str) -> List[Dict[str, str]]:
        """
        Get list of available datasets at a location.

        site_id: location id ("HYDRA-1", ...).

        returns a list of dicts, one per dataset, with keys:
        site_id, code, name, unit, label, begin, end,
        dataset_identifier, primary, active, type, utc_offset.
        code/dataset_identifier are the full Aquarius dataset
        identifier ("Precip.15min@HYDRA-1") -- that's the id a
        download call will need. unit is "" for now; the dataset
        list doesn't carry units (they show up in exported data,
        which is a get_data()-time thing).
        """
        datasets = [
            ds for ds in self._datasets_raw()
            if ds.get("locationIdentifier") == site_id
        ]
        parameters = [self._dataset_to_parameter(ds) for ds in datasets]
        parameters.sort(key=lambda p: (p["name"], p["code"]))

        if not parameters:
            self.logger.warning(
                f"No datasets found for Aquarius location {site_id!r}"
            )
        else:
            self.logger.info(
                f"Found {len(parameters):,} datasets at {site_id}"
            )
        return parameters

    def get_available_parameters_for_sites(
        self,
        site_ids: List[str],
    ) -> List[Dict[str, str]]:
        """Available datasets for several locations, combined."""
        combined: List[Dict[str, str]] = []
        for site_id in site_ids:
            combined.extend(self.get_available_parameters(site_id))
        return combined

    def available_parameters_dataframe(self, site_ids: List[str]) -> pd.DataFrame:
        """Available datasets for one or more locations, as a table."""
        records = self.get_available_parameters_for_sites(site_ids)
        return self._parameters_dataframe(records)

    def available_datasets_dataframe(
        self,
        site_ids: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """Catalogue of datasets, optionally for named locations.

        No site_ids = the whole portal. This is the Aquarius
        equivalent of browsing the full USGS catalogue before
        picking anything.
        """
        if site_ids:
            records = self.get_available_parameters_for_sites(site_ids)
        else:
            records = [
                self._dataset_to_parameter(ds) for ds in self._datasets_raw()
            ]
            records.sort(key=lambda p: (p["site_id"], p["name"], p["code"]))
            self.logger.info(f"Catalogued {len(records):,} Aquarius datasets")
        return self._parameters_dataframe(records)

    @staticmethod
    def _parameters_dataframe(records: List[Dict[str, str]]) -> pd.DataFrame:
        columns = [
            "site_id", "code", "name", "unit", "label", "begin",
            "end", "dataset_identifier", "primary", "active",
            "type", "utc_offset",
        ]
        if not records:
            # Same trick as USGS: keep the columns on an empty
            # frame so downstream code doesn't blow up.
            return pd.DataFrame(columns=columns)
        return pd.DataFrame.from_records(records, columns=columns)

    @staticmethod
    def _dataset_to_parameter(dataset: Dict[str, Any]) -> Dict[str, str]:
        """Convert one portal dataset dict to a catalogue dict."""

        def text(key: str) -> str:
            value = dataset.get(key)
            return "" if value is None else str(value)

        return {
            "site_id": text("locationIdentifier"),
            "code": text("identifier"),
            "name": text("parameter"),
            "unit": "",  # not in the dataset list, see docstring
            "label": text("label"),
            "begin": text("startOfRecord"),
            "end": text("endOfRecord"),
            "dataset_identifier": text("identifier"),
            "primary": text("primaryDataset"),
            "active": text("active"),
            "type": text("type"),
            "utc_offset": text("utcOffset"),
        }

    # ---------------------------------------------------------
    # DATA DOWNLOAD
    # ---------------------------------------------------------
    # Two ways in: name the datasets directly, or give me
    # sites + a parameter and let me resolve which dataset(s)
    # that means. Downloads go through the portal's bulk
    # export in chunks (same as the standalone downloader),
    # just aimed at the requested dates instead of the whole
    # record.

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

        site_ids: one or more location ids.
        parameter: dataset parameter name ("Precipitation
            Incremental", "Depth", "Flow", ...; "precip" /
            "precipitation" also match) or an exact dataset
            identifier.
        start_date / end_date: datetime, date, or ISO string.

        kwargs:
            dataset_identifiers: exact datasets to download
                (from the catalogue). If given, these are used
                as-is and site_ids/parameter are ignored for
                selection.
            label: when a parameter has several datasets at a
                site (15Minute / 1Hour / Primary / Forecast),
                pick the one with this label. Without it, several
                matches = an error listing the options, same
                no-guessing rule as USGS.
            chunk_years: years per export request (default 5).

        returns a list of DataPoint objects, oldest first.
        """
        dataset_identifiers = kwargs.pop("dataset_identifiers", None)
        label = kwargs.pop("label", None)
        chunk_years = kwargs.pop("chunk_years", 5)
        if kwargs:
            raise ValueError(
                f"Unsupported get_data() argument(s): {sorted(kwargs)}. "
                "Supported: dataset_identifiers, label, chunk_years"
            )

        if dataset_identifiers:
            datasets = []
            raw_by_id = {
                ds.get("identifier"): ds for ds in self._datasets_raw()
            }
            for identifier in dataset_identifiers:
                if identifier not in raw_by_id:
                    raise ValueError(
                        f"Dataset identifier not found: {identifier!r}. "
                        "Check available_datasets_dataframe()."
                    )
                datasets.append(raw_by_id[identifier])
        else:
            datasets = []
            for site_id in site_ids:
                datasets.append(
                    self._resolve_dataset(site_id, parameter, label=label)
                )

        return self._download_datasets(
            datasets, start_date, end_date, chunk_years=chunk_years
        )

    def get_dataset_data(
        self,
        dataset_identifiers: List[str],
        start_date: datetime,
        end_date: datetime,
        chunk_years: int = 5,
    ) -> List[DataPoint]:
        """Download exact datasets by identifier.

        Convenience wrapper for when I already picked datasets
        out of the catalogue and don't want to go through the
        site + parameter resolution.
        """
        return self.get_data(
            [], "", start_date, end_date,
            dataset_identifiers=dataset_identifiers,
            chunk_years=chunk_years,
        )

    # ---------------------------------------------------------
    # ALL-DATASETS MODE
    # ---------------------------------------------------------
    # Same deal as USGS all-series mode: driven off the
    # catalogue, preview and download share _select_datasets()
    # so they can't disagree. With 2,255 datasets on the
    # portal, the preview matters even more here -- an
    # unfiltered all-portal download is a LOT of requests.

    def _select_datasets(
        self,
        site_ids: Optional[List[str]] = None,
        parameters: Optional[List[str]] = None,
        active_only: bool = False,
        primary_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Work out which datasets an all-datasets call covers."""
        datasets = list(self._datasets_raw())

        if site_ids:
            wanted_sites = {str(site_id) for site_id in site_ids}
            datasets = [
                ds for ds in datasets
                if ds.get("locationIdentifier") in wanted_sites
            ]

        if parameters:
            wanted = {str(p).strip().lower() for p in parameters}
            aliases = {"precip", "precipitation", "rainfall", "rain"}

            def matches(ds):
                param = (ds.get("parameter") or "").lower()
                identifier = (ds.get("identifier") or "").lower()
                if param in wanted or identifier in wanted:
                    return True
                # the precip aliases match any precip parameter
                return bool(wanted & aliases) and "precip" in param

            datasets = [ds for ds in datasets if matches(ds)]

        if active_only:
            datasets = [ds for ds in datasets if ds.get("active")]
        if primary_only:
            datasets = [ds for ds in datasets if ds.get("primaryDataset")]

        datasets.sort(key=lambda ds: (
            ds.get("locationIdentifier") or "",
            ds.get("parameter") or "",
            ds.get("identifier") or "",
        ))
        return datasets

    def preview_all_datasets(
        self,
        site_ids: Optional[List[str]] = None,
        parameters: Optional[List[str]] = None,
        active_only: bool = False,
        primary_only: bool = False,
    ) -> pd.DataFrame:
        """Show what an all-datasets download WOULD pull.

        Same filters as get_all_datasets_data(). No site_ids
        means the whole portal -- I always look at this before
        an all-datasets run, the count can be sobering.
        """
        selected = self._select_datasets(
            site_ids, parameters=parameters,
            active_only=active_only, primary_only=primary_only,
        )
        records = [self._dataset_to_parameter(ds) for ds in selected]
        sites_covered = len({ds.get("locationIdentifier") for ds in selected})
        self.logger.info(
            f"All-datasets preview: {len(records):,} datasets "
            f"across {sites_covered:,} location(s)"
        )
        return self._parameters_dataframe(records)

    def get_all_datasets_data(
        self,
        site_ids: Optional[List[str]] = None,
        start_date: datetime = None,
        end_date: datetime = None,
        parameters: Optional[List[str]] = None,
        active_only: bool = False,
        primary_only: bool = False,
        chunk_years: int = 5,
    ) -> List[DataPoint]:
        """Download every dataset matching the filters.

        site_ids: locations to cover. None = the whole portal
            (all 2,000+ datasets -- only do that on purpose).
        parameters: optional shortlist of parameter names /
            identifiers ("Depth", "precip", ...). None = all.
        active_only / primary_only: narrow to active datasets /
            portal-designated primary datasets.

        One failing dataset doesn't sink the rest; I log it and
        keep going, same as USGS all-series mode. All failing =
        raise, not a fake empty success.

        returns a list of DataPoint objects. Preview first.
        """
        if start_date is None or end_date is None:
            raise ValueError(
                "get_all_datasets_data() needs start_date and end_date"
            )

        selected = self._select_datasets(
            site_ids, parameters=parameters,
            active_only=active_only, primary_only=primary_only,
        )
        if not selected:
            raise ValueError(
                "No datasets matched the all-datasets filters. "
                "Check preview_all_datasets()."
            )

        per_site: Dict[str, int] = {}
        for ds in selected:
            site = ds.get("locationIdentifier") or ""
            per_site[site] = per_site.get(site, 0) + 1
        self.logger.info(
            f"All-datasets download: {len(selected):,} datasets "
            f"across {len(per_site):,} location(s)"
        )

        all_points: List[DataPoint] = []
        failures = 0
        for dataset in selected:
            try:
                points = self._download_datasets(
                    [dataset], start_date, end_date,
                    chunk_years=chunk_years,
                )
            except Exception as exc:
                failures += 1
                self.logger.error(
                    f"Skipping dataset {dataset.get('identifier')}: {exc}"
                )
                continue
            all_points.extend(points)

        if failures and not all_points:
            raise RuntimeError(
                f"All {failures} datasets failed to download. "
                "See log above for the individual errors."
            )
        if failures:
            self.logger.warning(
                f"All-datasets download finished with {failures} "
                f"failed datasets out of {len(selected):,}"
            )

        all_points.sort(
            key=lambda p: (p.timestamp, p.location_id, p.parameter)
        )
        self.logger.info(
            f"All-datasets download complete: {len(all_points):,} "
            f"points from {len(selected) - failures:,} datasets"
        )
        return all_points

    def get_all_datasets_dataframe(
        self,
        site_ids: Optional[List[str]] = None,
        start_date: datetime = None,
        end_date: datetime = None,
        **kwargs
    ) -> pd.DataFrame:
        """get_all_datasets_data(), converted to a DataFrame."""
        return self.to_dataframe(
            self.get_all_datasets_data(
                site_ids, start_date, end_date, **kwargs
            )
        )

    def _resolve_dataset(
        self,
        site_id: str,
        parameter: str,
        label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Pick the one dataset a get_data() call means.

        Same rule as USGS: if the filters leave more than one
        candidate I error out and list them rather than guess.
        """
        available = [
            ds for ds in self._datasets_raw()
            if ds.get("locationIdentifier") == site_id
        ]
        if not available:
            raise ValueError(
                f"No datasets at Aquarius location {site_id!r}. "
                "Check get_sites() / get_available_parameters()."
            )

        wanted = str(parameter).strip().lower()
        aliases = {"precip", "precipitation", "rainfall", "rain"}
        candidates = [
            ds for ds in available
            if (ds.get("identifier") or "").lower() == wanted
            or (ds.get("parameter") or "").lower() == wanted
            or (wanted in aliases and "precip" in (ds.get("parameter") or "").lower())
        ]

        if label:
            candidates = [
                ds for ds in candidates
                if (ds.get("label") or "").lower() == label.lower()
            ]

        if not candidates:
            offered = sorted({
                f"{ds.get('parameter')} ({ds.get('label')}, "
                f"{ds.get('identifier')})" for ds in available
            })
            raise ValueError(
                f"No dataset matching parameter={parameter!r}"
                + (f" label={label!r}" if label else "")
                + f" at {site_id}. Available: {offered}"
            )
        if len(candidates) > 1:
            listing = "; ".join(
                f"{ds.get('parameter')} ({ds.get('label')}, "
                f"{ds.get('identifier')}, "
                f"{str(ds.get('startOfRecord'))[:10]} to "
                f"{str(ds.get('endOfRecord'))[:10]})"
                for ds in candidates
            )
            raise ValueError(
                f"Parameter {parameter!r} at {site_id} matches "
                f"{len(candidates)} datasets and I won't guess. "
                f"Pass label= (or dataset_identifiers=) to pick: "
                f"{listing}"
            )
        return candidates[0]

    def _download_datasets(
        self,
        datasets: List[Dict[str, Any]],
        start_date,
        end_date,
        chunk_years: int = 5,
    ) -> List[DataPoint]:
        """Download the given datasets over a date range."""
        if not isinstance(chunk_years, int) or chunk_years < 1:
            raise ValueError("chunk_years must be a positive integer")

        start = self._coerce_datetime(start_date, "start_date")
        end = self._coerce_datetime(end_date, "end_date")
        if end < start:
            raise ValueError("end_date is before start_date")

        portal = self._portal()
        all_points: List[DataPoint] = []

        for dataset in datasets:
            identifier = dataset.get("identifier")
            points: List[DataPoint] = []
            skipped = 0

            for chunk_start, chunk_end in self._chunk_ranges(
                start, end, chunk_years
            ):
                result = portal.export_bulk(
                    dataset_identifiers=[identifier],
                    start_time=chunk_start.isoformat(),
                    end_time=chunk_end.isoformat(),
                    include_grade_codes=True,
                    include_qualifiers=True,
                    include_approval_levels=True,
                    include_interpolation_types=True,
                )
                if not result or "series" not in result:
                    self.logger.warning(
                        f"No data returned for {identifier} "
                        f"{chunk_start.date()} to {chunk_end.date()}"
                    )
                    continue

                for series in result["series"]:
                    series_info = series.get("dataset", {})
                    for raw_point in series.get("points", []):
                        point = self._point_to_datapoint(
                            raw_point, series_info
                        )
                        if point is None:
                            skipped += 1
                        else:
                            points.append(point)

            # Export chunks share a boundary instant like USGS,
            # so dedupe on timestamp before sorting.
            unique = {point.timestamp: point for point in points}
            points = sorted(unique.values(), key=lambda p: p.timestamp)
            self.logger.info(
                f"{identifier}: {len(points):,} points "
                f"({start.date()} to {end.date()})"
                + (f", {skipped} missing values skipped" if skipped else "")
            )
            all_points.extend(points)

        all_points.sort(
            key=lambda p: (p.timestamp, p.location_id, p.parameter)
        )
        return all_points

    @staticmethod
    def _chunk_ranges(start: datetime, end: datetime, years: int):
        """Yield (chunk_start, chunk_end) pairs covering a range.

        Same chunking idea as USGS / the Aquarius full-record
        export. Feb 29 falls back to Feb 28 on non-leap years.
        """
        if start == end:
            yield start, end
            return
        chunk_start = start
        while chunk_start < end:
            try:
                candidate = chunk_start.replace(
                    year=chunk_start.year + years
                )
            except ValueError:  # Feb 29 -> non-leap year
                candidate = chunk_start.replace(
                    year=chunk_start.year + years, day=28
                )
            chunk_end = min(candidate, end)
            yield chunk_start, chunk_end
            chunk_start = chunk_end

    @staticmethod
    def _coerce_datetime(value, name: str) -> datetime:
        """Turn a date/datetime/string into a datetime.

        I keep whatever timezone (or lack of one) the caller
        gave me -- Aquarius data is local portal time with an
        offset on the returned points, not UTC like USGS.
        """
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                raise ValueError(
                    f"{name} isn't a valid ISO date/datetime: {value!r}"
                )
        raise TypeError(
            f"{name} must be a datetime, date, or ISO string, "
            f"got {type(value).__name__}"
        )

    @staticmethod
    def _parse_timestamp(text: str) -> datetime:
        """Parse an Aquarius timestamp.

        Points come back like "2026-10-19T00:05:00.0000000-08:00"
        -- seven fractional digits, which fromisoformat can be
        picky about, so I trim the fraction to six digits first.
        """
        if "." in text:
            head, rest = text.split(".", 1)
            fraction = ""
            suffix = ""
            for char in rest:
                if char.isdigit() and len(fraction) < 6:
                    fraction += char
                else:
                    suffix += char
            text = f"{head}.{fraction}{suffix}"
        return datetime.fromisoformat(text)

    @staticmethod
    def _point_to_datapoint(
        raw_point: Dict[str, Any],
        series_info: Dict[str, Any],
    ) -> Optional[DataPoint]:
        """Convert one exported Aquarius point to a DataPoint.

        Grade/approval names and qualifiers go into
        quality_flag together (same idea as USGS). Qualifiers
        can be a string, a list, or None depending on the point.
        """
        raw_value = raw_point.get("value")
        if raw_value is None or raw_value == "":
            return None
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return None

        quality_parts = []
        for item in [
            raw_point.get("gradeName") or raw_point.get("gradeCode"),
            raw_point.get("approvalName") or raw_point.get("approvalLevel"),
            raw_point.get("qualifiers"),
        ]:
            if isinstance(item, (list, tuple)):
                quality_parts.extend(str(part) for part in item if part)
            elif item not in (None, ""):
                quality_parts.append(str(item))

        return DataPoint(
            timestamp=AquariusDataSource._parse_timestamp(
                raw_point["timestamp"]
            ),
            value=value,
            location_id=series_info.get("locationIdentifier", ""),
            parameter=series_info.get("parameter", ""),
            unit=series_info.get("unit", ""),
            source="Aquarius",
            quality_flag="|".join(quality_parts) if quality_parts else None,
        )
