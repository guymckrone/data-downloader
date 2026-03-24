
from config import OUTPUT_DIR
from logging_setup import setup_logging, get_logger
from data_loader import find_latest_database, load_rainfall_data, filter_by_date

setup_logging()
logger = get_logger(__name__)

def main():

    logger.info("Starting gauge analysis...")
    # Find the database
    db_path = find_latest_database(OUTPUT_DIR)
    logger.info(f"Using database: {db_path}")

    if db_path is None:
        logger.error("Cannot continue without a database file")
        return
    
    # Load into DataFrame
    rain_df = load_rainfall_data(db_path)

    # Limit dates
    rain_df = filter_by_date(rain_df, START_DATE, END_DATE)

if __name__ == "__main__":
    main()