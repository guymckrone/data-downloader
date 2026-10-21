"""
Aquarius (Portland BES portal) data source.

Retrofit of the standalone aquarius_data_downloader.py into the
BaseDataSource shape, so Aquarius and USGS can sit behind the
same interface (and eventually the same GUI).

Done so far (inventory only):
    get_sites()                -- portal locations as SiteInfo
    get_available_parameters() -- datasets at a location
    available_datasets_dataframe() -- whole-portal catalogue

TODO:
    get_data() -- download a selected dataset. For now the
    existing download_all_precipitation() flow in
    aquarius_data_downloader.py still does the downloading;
    I don't want to break that working code while I build this.

Notes to self:
    - Aquarius "series" are datasets. The identifier looks like
      "Precip.15min@HYDRA-1": parameter.label@location.
    - The portal connection only happens when a method is
      called (see _portal), not on init -- I don't want
      creating the object to hit the network.
"""

from datetime import datetime
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
    # TODO: DATA DOWNLOAD (not implemented yet)
    # ---------------------------------------------------------
    # The standalone downloader already downloads precip
    # datasets fine. Wiring get_data() to dataset selection is
    # the next Aquarius step; raising here for now beats
    # returning a fake empty result.

    def get_data(
        self,
        site_ids: List[str],
        parameter: str,
        start_date: datetime,
        end_date: datetime,
        **kwargs
    ) -> List[DataPoint]:
        """Get time series data. TODO: not wired up yet."""
        raise NotImplementedError(
            "Aquarius get_data() is not implemented yet; use "
            "aquarius_data_downloader.download_all_precipitation() "
            "for now."
        )
