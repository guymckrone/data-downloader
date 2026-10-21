import os
from dotenv import load_dotenv

load_dotenv()

# Get credentials from environment
BASE_URL = os.getenv("AQUARIUS_BASE_URL")
USERNAME = os.getenv("AQUARIUS_USERNAME")
PASSWORD = os.getenv("AQUARIUS_PASSWORD")
# Date filters (set to None to use all data)
START_DATE = '1980-01-01'
END_DATE = '2010-12-31'

OUTPUT_DIR = os.getenv("OUTPUT_DIRECTORY")

DATASET_CONFIGS = {
    "15_min_precip_longest": {
        "must_contain_all": ["precip", "15min"],
        "must_contain_any": None,
        "must_start_before": "1980-01-01",
        "must_end_after": "2010-01-01"
    },

    "single_hydra": {
        "must_contain_all": ["precip", "15min"],
        "must_contain_any": ["HYDRA-1"],
        "must_start_before": None,
        "must_end_after": None
    },

    # Every 15-minute precipitation dataset, regardless of record length.
    # (Brought over from the portland-bes-tools version.)
    "all": {
        "must_contain_all": ["precip", "15min"],
        "must_contain_any": None,
        "must_start_before": None,
        "must_end_after": None
    },

    # "Primary" precipitation datasets, regardless of interval.
    # (Brought over from the portland-bes-tools version.)
    "primary": {
        "must_contain_all": ["precip", "Primary"],
        "must_contain_any": None,
        "must_start_before": None,
        "must_end_after": None
    }
}

ACTIVE_CONFIG = "15_min_precip_longest"

SAVE_CSV = True
SAVE_SQL = True