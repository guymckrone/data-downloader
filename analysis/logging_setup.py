import logging

def setup_logging(level=logging.DEBUG):
    
    # Set up logging
    logging.basicConfig(
        level = level,
        format = "%(asctime)s - %(levelname)s - %(message)s",
        datefmt = "%H:%M:%S"
    )
    return logging.getLogger(__name__)

def get_logger(name):
    return logging.getLogger(name)
    