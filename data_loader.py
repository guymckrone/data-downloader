import os
import pickle
import sqlite3
import pandas as pd
from logging_setup import setup_logging, get_logger

# Setup logging
setup_logging()
logger = get_logger(__name__)

def find_latest_database(output_dir):
    logger.info(f"Looking for database files in {output_dir}...")

    # Get all files in the directory
    all_files = os.listdir(output_dir)
    
    # Filter to only .db files
    db_files = [f for f in all_files if f.endswith('.db')]

    if not db_files:
        logger.error(f"No .db files found in {output_dir}")
        return None
    
    logger.info(f"Found {len(db_files)} database file(s)")

    #If multiple databases, picks most recent
    if len(db_files) > 1:
        # Sort by modification time, with most recent first
        db_files.sort(
            key=lambda f: os.path.getmtime(os.path.join(output_dir, f)),
            reverse=True
        )
    
    # Builds the full path
    db_path = os.path.join(output_dir, db_files[0])
    logger.info(f"Using database: {db_path}")

    return db_path

def load_rainfall_data(db_path, round_timestep='15min', aggfunc='first'):
    """Load a precipitation database as a wide DataFrame.

    "Wide" means: one row per timestamp, one column per gauge, rainfall
    values in the cells -- the shape the analysis modules expect.

    round_timestep: timestamps are rounded to this interval before
        pivoting (default '15min', matching the downloaded data, and
        matching what this function always did). Pass None to keep the
        raw timestamps exactly as stored.
    aggfunc: what to do when rounding (or the raw data) puts two values
        in the same timestamp x gauge cell. 'first' keeps the first
        value (the long-standing behaviour here); 'sum' adds them,
        which is the right choice if you ever round several smaller
        readings up into one bigger interval -- but it is NOT the
        default, because silently changing it would change results.

    Note: the portland-bes-tools version of this function also accepted
    resample / fill_limit arguments, but its body never used them, so
    they are deliberately not copied over -- an argument that does
    nothing is a trap for whoever reads the code next.
    """
    logger.info("Loading data from database")

    df = _load_from_database(db_path)

    if round_timestep:
        df['timestamp_aligned'] = df['timestamp'].dt.round(round_timestep)
        logger.info(f"  Example: {df['timestamp'].iloc[0]} -> {df['timestamp_aligned'].iloc[0]}")
        index_col = 'timestamp_aligned'
    else:
        index_col = 'timestamp'

    logger.info("Pivoting to wide format")

    wide = df.pivot_table(
        index=index_col,      # Rows = (aligned) timestamps
        columns='location',   # Columns will be gauge names
        values='value',       # Cell values will be rainfall amounts
        aggfunc=aggfunc       # How to resolve duplicate timestamp+gauge cells
    )

    logger.info(f"Result: {len(wide):,} timestamps x {len(wide.columns)} gauges")
    logger.info(f"gauges: {', '.join(wide.columns[:5])}{'...' if len(wide.columns) > 5 else ''}")

    return wide

def load_rainfall_data_cached(db_path, cache_dir=None, **kwargs):
    """load_rainfall_data(), but backed by a pickle (.pkl) disk cache.

    Loading and pivoting millions of rows is slow; the wide result is
    comparatively small. So the result is saved to a .pkl file and, on
    the next call, reloaded from disk in seconds -- PROVIDED the cache
    file is newer than the database (an older cache would be stale
    data from a previous download, so its modification time is checked
    against the database's).

    Extra keyword arguments (round_timestep, aggfunc) are forwarded to
    load_rainfall_data() and are included in the cache filename, so
    differently-shaped results never overwrite each other's cache.
    """
    # Build cache filename based on database name + load options
    db_name = os.path.basename(db_path).replace('.db', '')
    options = "_".join(f"{k}-{v}" for k, v in sorted(kwargs.items())) or "default"
    cache_file = f"{db_name}_{options}_cache.pkl"

    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, cache_file)

    # If cache exists and is newer than database, use it
    if os.path.exists(cache_file):
        cache_time = os.path.getmtime(cache_file)
        db_time = os.path.getmtime(db_path)

        if cache_time > db_time:
            logger.info(f"Loading from cache: {cache_file}")
            with open(cache_file, 'rb') as f:
                return pickle.load(f)

    # Otherwise load from database (uses the function above)
    logger.info("No cache found, loading from database...")
    rain_df = load_rainfall_data(db_path, **kwargs)

    # Save cache for next time. pickle serializes the DataFrame object
    # to bytes; it is fast and exact, but only ever load .pkl files you
    # created yourself -- unpickling untrusted files can run code.
    with open(cache_file, 'wb') as f:
        pickle.dump(rain_df, f)
    logger.info(f"Cached to: {cache_file}")

    return rain_df

def _load_from_database(db_path):
    """Read precipitation_data out of SQLite, one year at a time.

    Previously this was a single read_sql() over the whole table. For
    a decades-long, many-gauge database that is one enormous query
    result. Instead we now ask SQLite for the first/last timestamps,
    then loop over calendar years issuing one bounded query per year
    (WHERE timestamp >= start AND timestamp < end) and concatenate the
    yearly frames. The timestamp INDEX created by
    aquarius_data_downloader.initialize_database() is what makes those
    bounded queries fast -- without it SQLite would scan the whole
    table once per year.

    Honest limitation: the concatenated result is still one DataFrame
    in memory at the end. This upgrade buys you progress logging, a
    much smaller in-flight query result, and index-friendly queries --
    not infinite size. (Reading the database in chunks only helps if
    the consumer also processes it in chunks.)
    """
    # First, find the bounds of what is actually in the table
    with sqlite3.connect(db_path) as conn:
        bounds = pd.read_sql(
            "SELECT MIN(timestamp) AS t_min, MAX(timestamp) AS t_max FROM precipitation_data",
            conn
        )

    # An empty table gives None bounds; fail with a clear message
    # rather than a confusing crash further down.
    if bounds['t_min'].isna().all() or bounds['t_max'].isna().all():
        raise ValueError(f"No data found in precipitation_data in {db_path}")

    t_min = str(bounds['t_min'][0])[:4]  # "YYYY" of the first timestamp
    t_max = str(bounds['t_max'][0])[:4]  # "YYYY" of the last timestamp

    periods = pd.period_range(t_min, t_max, freq='Y')
    logger.info(f"Loading {len(periods)} years of data in chunks...")

    chunks = []
    with sqlite3.connect(db_path) as conn:
        for period in periods:
            start = str(period.start_time.date())
            # +1 day turns Dec 31 into next Jan 1, so `< end` cleanly
            # includes all of Dec 31 without overlapping the next year.
            end = str((period.end_time + pd.Timedelta(days=1)).date())

            # Named parameters (:start / :end) keep values out of the
            # SQL string itself -- safer and clearer than f-strings.
            chunk = pd.read_sql("""
                SELECT timestamp, value, location
                FROM precipitation_data
                WHERE timestamp >= :start AND timestamp < :end
                ORDER BY timestamp
            """, conn, params={'start': start, 'end': end})

            if not chunk.empty:
                chunk['timestamp'] = pd.to_datetime(chunk['timestamp'])
                chunks.append(chunk)
                logger.debug(f"  {period}: {len(chunk):,} rows")

    if not chunks:
        raise ValueError(f"No data found in precipitation_data in {db_path}")

    df = pd.concat(chunks, ignore_index=True)
    logger.info(f"Loaded {len(df):,} rows from database")
    return df

def filter_by_date(rain_df, start_date, end_date):
    if start_date and end_date:
        rain_df = rain_df.loc[start_date:end_date]
        logger.info(f"Filtered to {start_date} to {end_date}: {len(rain_df):,} timestamps")
    return rain_df

def load_gauge_locations(db_path=None, hydra_only=True, output_dir=None):
    """Load gauge coordinates from a precipitation database.

    The locations come from the gauge_locations table, which
    aquarius_data_downloader.initialize_database() creates and fills
    from the Aquarius API every time a download runs. So the database
    file now carries its own station metadata -- no separate lat/lon
    extraction step needed.

    db_path:    database to read. If omitted, the newest .db in
                output_dir (or config.OUTPUT_DIR) is used.
    hydra_only: restrict to HYDRA gauges (location_id LIKE 'HYDRA%').
    """
    if db_path is None:
        if output_dir is None:
            from config import OUTPUT_DIR
            output_dir = OUTPUT_DIR
        db_path = find_latest_database(output_dir)
        if db_path is None:
            raise FileNotFoundError(f"No database found in {output_dir}")

    # Older databases (created before gauge_locations existed) cannot
    # answer this query. Check first so the error message explains
    # what to do, instead of a raw SQLite "no such table" error.
    with sqlite3.connect(db_path) as conn:
        table_exists = conn.execute("""
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'gauge_locations'
        """).fetchone()
    if not table_exists:
        raise ValueError(
            f"{db_path} has no gauge_locations table -- it was created "
            "by an older version of aquarius_data_downloader.py. "
            "Run a download with the current version to create one."
        )

    query = """
        SELECT location_id, name, latitude, longitude
        FROM gauge_locations
        WHERE latitude IS NOT NULL
          AND longitude IS NOT NULL
    """
    if hydra_only:
        query += " AND location_id LIKE 'HYDRA%'"
    query += " ORDER BY location_id"

    with sqlite3.connect(db_path) as conn:
        locations = pd.read_sql(query, conn)

    locations["location_id"] = locations["location_id"].astype(str)
    logger.info(f"Loaded {len(locations)} gauge locations from {db_path}")
    return locations
