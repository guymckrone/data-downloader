
from config import OUTPUT_DIR
from logging_setup import setup_logging, get_logger
from data_loader import find_latest_database, load_database_to_dataframe, _load_from_database

setup_logging()
logger = get_logger(__name__)

def main():

    logger.info("Starting gauge analysis...")
    # Find the database
    db_path = find_latest_database(OUTPUT_DIR)
    print(f"Using database: {db_path}")

    if db_path is None:
        logger.error("Cannot continue without a database file")
        return
    
    # Load into DataFrame
    rain_df = load_database_to_dataframe(db_path)

    print(rain_df)

if __name__ == "__main__":
    main()