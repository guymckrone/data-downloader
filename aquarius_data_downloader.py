import requests
from datetime import datetime
import logging
import csv
import os
import sqlite3

# All settings (credentials, output folder, which datasets to download,
# whether to save CSV / SQLite) live in config.py -- the same file the
# analysis modules already import from. Importing them here means there
# is ONE place to change a setting, instead of a second, private copy
# inside this file that could drift out of sync with config.py.
# (config.py itself loads the .env file, so credentials are read there.)
from config import (
    BASE_URL, USERNAME, PASSWORD, OUTPUT_DIR,
    DATASET_CONFIGS, ACTIVE_CONFIG,
    SAVE_CSV, SAVE_SQL
)


# Set up logging
logging.basicConfig(
    level = logging.DEBUG,
    format = "%(asctime)s - %(levelname)s - %(message)s",
    datefmt = "%H:%M:%S"
)
logger = logging.getLogger(__name__)

class AquariusPortal:
    def __init__(self, base_url, username, password, verify_ssl=True):
        self.base_url = base_url
        self.username = username
        self.password = password

        self.session = requests.Session()
        self.session.auth = (username, password)

        self.verify_ssl = verify_ssl

        if not verify_ssl:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            logger.warning("SSL verification disabled")

        logger.info(f"Connecting to {base_url}...")

        self.test_connection()

    def _get(self, endpoint):
        # Get Helper Function
        
        url = f"{self.base_url}/{endpoint}" # Building the full URL
        response = self.session.get(url, verify = self.verify_ssl) # Getting data

        if response.status_code == 200: # 200 success, 404 not found, 500 server error
            return response.json()
        else:
            logger.error(f"Error on {endpoint}: {response.status_code}")
            return
    
    def _post(self, endpoint, data):
        # POST Helper Function


        url = f"{self.base_url}/{endpoint}" # Building the full URL

        headers = {
            "Accept": "application/json", # Requesting JSON data from server
            "Content-Type": "application/json" # Telling server I am sending data in JSON format (Since POST requires data send)
        }
        # json = data converts python dictionary to json
        response = self.session.post(url, json = data, headers = headers, verify = self.verify_ssl)

        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Error on POST {endpoint}: {response.status_code}")
            logger.error(f"Response: {response.text[:500]}") # Error details
            return None

    def test_connection(self):
        # Testing connection to API
        url = f"{self.base_url}/version"
        response = self.session.get(url, verify=self.verify_ssl)

        if response.status_code == 200:
            version_info = response.json()
            logger.info(f"Connected Successfully! Version: {version_info['webPortalVersion']}")
        else:
            logger.error(f"Connection failed: {response.status_code}")

    
    # BASIC ENDPOINTS
    
    ## Locations ##

    def get_locations(self):
        return self._get("locations")
    
    def get_location(self, location_id):
        return self._get(f"locations/{location_id}")
    
    ## Datasets ##

    def get_datasets(self):
        return self._get("data-set")
    
    ## Alerts ##
    
    def get_alerts(self):
        return self._get("alerts")
    
    def get_alert(self, alert_id):
        return self._get(f"alerts/{alert_id}")
    
    ## Statistics ##
    
    def get_statistic_definitions(self):
        return self._get("statistics/latest")
    
    def get_statistic_definitions_by_param(self, param):
        return self._get(f"statistics/latest/{param}")
    
    def get_latest_values(self):
        return self._get("statistic-values/latest")
    
    def get_latest_values_by_param(self, param):
        return self._get(f"statistic-values/latest/{param}")
    
    ## Filters and Parameters
    
    def get_filters(self):
        return self._get("filters")
    
    def get_parameter_ranges(self):
        return self._get("parameter-ranges")
    
    def get_parameter_range(self, parameter_range_id):
        return self._get(f"parameters-ranges/{parameter_range_id}")
    
    ## Map Data (GeoJSON)

    def get_map_locations(self):
        return self._get("map/locations")
    
    def get_map_datasets(self, param):
        return self._get(f"map/datasets/{param}")
    
    ## Time Series Data Export

    def export_bulk(
        self,
        dataset_identifiers, # List of strings
        date_range = None, # Predefined range ex. Days7
        start_time = None,
        end_time = None,
        interval = "PointsAsRecorded", # How to group the data
        step = None, # Interval Multiplier
        timezone = None,
        round_data = False,
        include_grade_codes = False,
        include_qualifiers = False,
        include_approval_levels = False,
        include_interpolation_types = False):
        
        # Building datasets list
        datasets = []
        for identifier in dataset_identifiers:
            datasets.append({"identifier": identifier})

        # Building the request body
        body = {
            "Datasets": datasets, # See above
            "Interval": interval, # Aggreagation ex. "Hourly"
            "RoundData": round_data, 
            "IncludeGradeCodes": include_grade_codes,
            "IncludeQualifiers": include_qualifiers,
            "IncludeApprovalLevels": include_approval_levels,
            "IncludeInterpolationTypes": include_interpolation_types
        }

        if date_range: # Add date parameters (Only if specified)
            body["DateRange"] = date_range
        else: # Checks if start and end time were used instead of date_range
            if start_time:
                if isinstance(start_time, datetime):
                    start_time = start_time.isoformat()
                body["StartTime"] = start_time

            if end_time:
                if isinstance(end_time, datetime):
                    end_time = end_time.isoformat()
                body["EndTime"] = end_time
        
        # Optional Parameters
        if step is not None:
            body["Step"] = step

        if timezone is not None:
            body["Timezone"] = timezone
        
        # Logging
        logger.info(f"Exporting {len(dataset_identifiers)} datasets...")
        logger.info(f"  Interval: {interval}")
        if step:
            logger.info(f"  Step: {step}")
        
        if date_range:
            logger.info(f"  Date range: {date_range}")
        elif start_time or end_time:
            logger.info(f"  From: {start_time} To: {end_time}")

        # Request time!
        result = self._post("export/bulk", body)

        # Summarize results
        if result and "series" in result:
            total_points = 0
            for series in result["series"]:
                total_points += series.get("numPoints", 0)
            logger.info(f"Got {len(result['series'])} series with {total_points} total points")
        
        return result

    def find_datasets(
        self,
        must_contain_all = None,
        must_contain_any = None,
        must_start_before = None,
        must_end_after = None):

        datasets_response = self.get_datasets() # Gets all datasets
        datasets_list = datasets_response.get("datasets", []) 
        
        matching = []

        for ds in datasets_list:
            # `or ""` (rather than .get("identifier", "")) also turns a
            # JSON null identifier into "" -- .get's default only applies
            # when the key is missing, and `"@" in None` would crash.
            identifier = ds.get("identifier") or ""
            start = (ds.get("startOfRecord") or "")[:10]
            end = (ds.get("endOfRecord") or "")[:10]

            matches = True

            # Extract station name to prevent for exampole Hydra 10 when searching hydra 1
            if "@" in identifier:
                station = identifier.split("@")[-1]
            else:
                station = identifier

            if must_contain_any:
                contains = False
                for text in must_contain_any:
                    if text.lower() == station.lower():
                        contains = True
                        break
                if not contains:
                    matches = False

            if must_contain_all:
                for text in must_contain_all:
                    if text.lower() not in identifier.lower():
                        matches = False
                        break

            if must_start_before:
                if not start or start >= must_start_before:
                    matches = False
            
            if must_end_after:
                if not end or end <= must_end_after:
                    matches = False
            
            if matches:
                matching.append(ds)
            
        logger.info(f"Found {len(matching)}")
        return matching
    
def _add_years(dt, years):
    """Return `dt` shifted by whole years, safely.

    datetime(dt.year + years, dt.month, dt.day) crashes for a Feb 29
    start when the target year is not a leap year, so fall back to
    Feb 28 in that one case.
    """
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:  # Feb 29 -> non-leap target year
        return dt.replace(year=dt.year + years, day=28)


def export_full_record(api, dataset_info, chunk_years=15):
    """Download one dataset's full record, in time chunks.

    Why chunk at all? A gauge with decades of 15-minute data is
    millions of points. Asking the server for all of it in a single
    export/bulk request tends to fail (server timeouts / oversized
    responses). Splitting the record into <= chunk_years-long requests
    keeps every individual response modest, then the chunks are
    stitched back together below.

    The returned dict has the exact same shape as a single
    export_bulk() result ({"series": [{"points": [...], ...}]}), so
    save_to_csv() and the database code work unchanged either way.
    """
    identifier = dataset_info.get("identifier")
    start_of_record = dataset_info.get("startOfRecord")
    end_of_record = dataset_info.get("endOfRecord")

    logger.info(f"Exporting: {identifier}")
    logger.info(f"  Period: {start_of_record[:10]} to {end_of_record}")

    # [:19] keeps "YYYY-MM-DDTHH:MM:SS" and drops any fractional
    # seconds / timezone suffix that fromisoformat may not accept.
    start = datetime.fromisoformat(start_of_record[:19])
    end = datetime.fromisoformat(end_of_record[:19])

    combined = None

    while start < end:
        # min(...) = "chunk_years from now, OR the end of the record,
        # whichever comes first" -- so the final chunk never overshoots.
        chunk_end = min(_add_years(start, chunk_years), end)
        logger.info(f"  Chunk: {start.date()} -> {chunk_end.date()}")

        chunk = api.export_bulk(
            dataset_identifiers=[identifier],
            start_time=start.isoformat(),
            end_time=chunk_end.isoformat(),
            include_grade_codes=True,        # Data quality grades
            include_qualifiers=True,         # Flags like "Downtime", "Estimated"
            include_approval_levels=True,    # Working, Approved, etc.
            include_interpolation_types=True # How gaps were filled
        )

        if chunk and "series" in chunk and chunk["series"]:
            if combined is None:
                # First successful chunk becomes the template: its
                # "series" entries (dataset info etc.) are kept, and
                # later chunks only contribute more points.
                combined = chunk
            else:
                for i, series in enumerate(chunk["series"]):
                    # extend() adds each point individually;
                    # append() would nest the whole list as one item.
                    combined["series"][i]["points"].extend(series.get("points", []))
                    combined["series"][i]["numPoints"] = len(combined["series"][i]["points"])
        else:
            # Not fatal -- remaining chunks are still attempted -- but
            # make the gap visible instead of failing silently.
            logger.warning(f"  No data returned for chunk {start.date()} -> {chunk_end.date()}")

        start = chunk_end

    return combined

def save_to_csv(data, filename):

    if not data or "series" not in data:
        logger.error("No data to save!")
        return
    
    full_path = os.path.abspath(filename)
    
    with open(filename, "w", newline = "") as file:
        writer = csv.writer(file)

        # The four extra columns match the include_*=True flags passed
        # in export_full_record(): quality metadata for every point.
        writer.writerow(["timestamp", "value", "location", "parameter", "unit",
                         "grade_code", "qualifiers", "approval_level", "interpolation_type"])

        full_path = os.path.abspath(filename)
        total_points = sum(s.get("numPoints", 0) for s in data["series"])
        logger.info(f"Saving {total_points} data points to {full_path}")

        for series in data["series"]:
            dataset_info = series["dataset"]
            location = dataset_info.get("locationIdentifier", "")
            parameter = dataset_info.get("parameter", "")
            unit = dataset_info.get("unit", "")

            points = series.get("points", [])

            for point in points:
                timestamp = point.get("timestamp", "")
                value = point.get("value", "")

                # camelCase keys are the names the Aquarius API
                # returns; the CSV columns above use snake_case.
                grade_code = point.get("gradeCode", "")
                qualifiers = point.get("qualifiers", "")
                approval_level = point.get("approvalLevel", "")
                interpolation_type = point.get("interpolationType", "")

                writer.writerow([timestamp, value, location, parameter, unit,
                                 grade_code, qualifiers, approval_level, interpolation_type])
    
    logger.info(f"Saved to {full_path}")
    
    return

def clean_for_filename(text):

    if not text:
        return "unknown"
    
    replacements = {
        "@": "_at_",
        ".": "_",
        "/": "_",
        "\\": "_",
        ":": "_",
        "*": "_",
        "?": "_",
        '"': "_",
        "<": "_",
        ">": "_",
        "|": "_",
        " ": "_"
    }

    result = text
    for old, new in replacements.items():
        result = result.replace(old, new)

    return result

def generate_filename(dataset_info=None, output_dir=None, dl_csv=False, dl_sql=False):

    download_date = datetime.now().strftime("%Y-%m-%d")

    if dl_csv:
        identifier = dataset_info.get("identifier", "unknown")
        start_of_record = dataset_info.get("startOfRecord")[:10]
        end_of_record = dataset_info.get("endOfRecord")[:10]
        

        safe_identifier = clean_for_filename(identifier)

        filename = f"{safe_identifier}_{start_of_record}_to_{end_of_record}_downloaded_{download_date}.csv"
    
    elif dl_sql:
        # Named after the active config (not hardcoded "15min") so the
        # filename itself records which selection produced the database.
        filename = f"precipitation_{ACTIVE_CONFIG}_downloaded_{download_date}.db"

    else:
        raise ValueError("Must specify either dl_csv=True or dl_sql=True")

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        return os.path.join(output_dir, filename)
    
    return filename

def save_dataset_to_csv(dataset_info, data, output_dir):

    filepath = generate_filename(dataset_info, output_dir, dl_csv = True)

    return save_to_csv(data, filepath)

def download_all_precipitation(api, output_dir, dl_csv, dl_sql, config_name):

    logger.info(f"Using configuration: {config_name}")

    config = DATASET_CONFIGS[config_name]
    
    logger.info(f"  Filters: {config['must_contain_all']}")
    logger.info(f"  Stations: {config['must_contain_any'] or 'All'}")

    matching_datasets = api.find_datasets(**config)

    if not matching_datasets:
        logger.error("No datasets found!")
        return
    
    logger.info(f"Found {len(matching_datasets)} datasets")

    # Set the database up ONCE, before downloading anything.
    # Each dataset is then written to disk as soon as it is downloaded
    # (see append_dataset_to_database below) instead of keeping every
    # dataset in a Python list until the end. For a large download the
    # old collect-everything-first approach meant memory use grew with
    # the TOTAL download size; now it only has to hold ONE dataset at
    # a time, and finished datasets are safely on disk if a later one
    # fails or the run is stopped.
    if dl_sql:
        db_path = generate_filename(output_dir=output_dir, dl_sql=True)
        initialize_database(db_path, api)

    for i, dataset_info in enumerate(matching_datasets, 1):
        identifier = dataset_info.get("identifier")
        logger.info(f"[{i}/{len(matching_datasets)}] {identifier}")

        data = export_full_record(api, dataset_info)

        if not data:
            logger.warning("  Skipped - no data returned")
            continue

        if dl_csv:
            save_dataset_to_csv(dataset_info, data, output_dir)

        if dl_sql:
            append_dataset_to_database(db_path, dataset_info, data)
            # `data` is overwritten on the next loop iteration, so the
            # previous dataset's points can be freed from memory
            # (garbage collected) instead of piling up.

    logger.info(f"Complete! Files saved to: {os.path.abspath(output_dir)}")

def initialize_database(db_path, api):
    """Create tables (if needed) and save gauge location metadata once.

    Split out from append_dataset_to_database() because table creation
    and the locations list only need to happen a single time per run,
    not once per dataset.
    """
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # Column notes (types are SQLite's):
        #   id               INTEGER PRIMARY KEY AUTOINCREMENT -- unique
        #                    row number, automatically assigned 1, 2, 3...
        #   timestamp        TEXT NOT NULL -- must always have a value
        #   value            REAL -- decimal numbers (0.1, 3.22, ...)
        #   grade_code etc.  the per-point quality metadata requested
        #                    with the include_*=True export flags
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS precipitation_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                value REAL,
                location TEXT,
                parameter TEXT,
                unit TEXT,
                dataset_identifier TEXT,
                grade_code INTEGER,
                qualifiers TEXT,
                approval_level INTEGER,
                interpolation_type TEXT
            )
        """)

        # One row per gauge/station: where it is. Saved alongside the
        # measurements so a database file is self-describing -- tools
        # reading it later don't need a separate locations lookup.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gauge_locations (
                location_id TEXT PRIMARY KEY,
                name TEXT,
                latitude REAL,
                longitude REAL,
                type TEXT,
                elevation REAL,
                active INTEGER
            )
        """)

        # An index on timestamp makes later "give me this date range"
        # queries fast on very large tables (SQLite can jump straight
        # to the relevant rows instead of scanning every row). It
        # slightly slows inserts and uses some disk -- a worthwhile
        # trade for a table that is written once and read many times.
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_precipitation_timestamp
            ON precipitation_data (timestamp)
        """)

        logger.info("Fetching and saving location metadata...")
        loc_response = api.get_locations()
        if loc_response and 'locations' in loc_response:
            loc_rows = []
            for loc in loc_response['locations']:
                loc_rows.append((
                    loc.get('id'),
                    loc.get('name'),
                    loc.get('latitude'),
                    loc.get('longitude'),
                    loc.get('type'),
                    loc.get('elevation'),
                    1 if loc.get('active') else 0  # SQLite has no bool; 1/0
                ))
            # INSERT OR REPLACE: re-running a download refreshes an
            # existing location row instead of failing on its
            # PRIMARY KEY already being present.
            cursor.executemany("""
                INSERT OR REPLACE INTO gauge_locations
                (location_id, name, latitude, longitude, type, elevation, active)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, loc_rows)
            logger.info(f"Saved {len(loc_rows)} locations.")

        conn.commit()

def append_dataset_to_database(db_path, dataset_info, data):
    """Insert one downloaded dataset's points into the database.

    Called once per dataset from download_all_precipitation(), right
    after that dataset is downloaded -- this is what keeps memory use
    to roughly one dataset instead of the whole download.
    """
    if not data or "series" not in data:
        logger.warning("  No series data to insert.")
        return

    rows_to_insert = []
    for series in data["series"]:
        series_info = series["dataset"]
        location = series_info.get("locationIdentifier", "")
        parameter = series_info.get("parameter", "")
        unit = series_info.get("unit", "")
        identifier = series_info.get("identifier", "")

        for point in series.get("points", []):
            rows_to_insert.append((
                point.get("timestamp", ""),
                point.get("value", ""),
                location,
                parameter,
                unit,
                identifier,
                point.get("gradeCode", ""),
                # qualifiers can come back as a list; str() flattens
                # it to text so it fits a single TEXT column.
                str(point.get("qualifiers", "")),
                point.get("approvalLevel", ""),
                point.get("interpolationType", "")
            ))

    if not rows_to_insert:
        logger.warning("  No points found in series.")
        return

    # executemany() runs the same INSERT for every tuple in the list --
    # far faster than executing row-by-row in a Python loop.
    # The `with` block closes the connection even if an error occurs;
    # if executemany fails partway, nothing is committed.
    with sqlite3.connect(db_path) as conn:
        conn.executemany("""
            INSERT INTO precipitation_data
            (timestamp, value, location, parameter, unit, dataset_identifier,
             grade_code, qualifiers, approval_level, interpolation_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows_to_insert)
        conn.commit()

    logger.info(f"  Inserted {len(rows_to_insert):,} rows into database.")

def check_database(output_dir):
    db_path = generate_filename(output_dir = output_dir, dl_sql = True)

    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        return
    
    logger.info(f"Checking database: {db_path}")

    with sqlite3.connect(db_path) as conn:
    
        cursor = conn.cursor()

        cursor.execute("""
            SELECT location, COUNT(*) as count
            FROM precipitation_data
            GROUP BY location
            ORDER BY count DESC
        """)
        logger.info("Rows per location:")
        for row in cursor.fetchall():
            print(f"  {row[0]}: {row[1]:,} rows")

        cursor.execute("SELECT * FROM precipitation_data LIMIT 5")
        logger.info("First 5 rows:")
        for row in cursor.fetchall():
            print(row)

def main():
    #OUTPUT_DIR = "C:/Users/Guy.McFeeters/OneDrive - Geosyntec/BES_SPEC_MOD_ONCALL_TEAM - GC001_BES_Rainfall_Analysis_Task/Code/Outputs/Tests"
    api = AquariusPortal(
        base_url = BASE_URL,
        username = USERNAME,
        password = PASSWORD,
        verify_ssl = False # Skip SSL verification for work network
    )

    download_all_precipitation(api, OUTPUT_DIR, SAVE_CSV, SAVE_SQL, ACTIVE_CONFIG)

    check_database(OUTPUT_DIR)

if __name__ == "__main__":
    main()