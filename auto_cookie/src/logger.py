import logging
from pathlib import Path

# Silence seleniumwire debug logs
logging.getLogger("seleniumwire").setLevel(logging.WARNING)


def setup_logger(name: str, log_file: str, level=logging.INFO) -> logging.Logger:
    """
    Creates and returns a logger that writes to <PROJECT_ROOT>/data/logs/log_file.
    """
    # Resolve the project root: <auto_cookie>/src/ → <auto_cookie> → <PROJECT_ROOT>
    project_root = Path(__file__).resolve().parents[2]
    log_dir = project_root / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_path = log_dir / log_file

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler = logging.FileHandler(log_path, encoding='utf-8')
    handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Prevent duplicate handlers if logger is reused
    if not logger.handlers:
        logger.addHandler(handler)

    return logger
