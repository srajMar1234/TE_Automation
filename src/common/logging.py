import logging
import sys
from pathlib import Path


def configure_logging(log_dir: Path, run_id: str, level: int = logging.INFO) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("reporting_automation")
    logger.setLevel(level)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | run_id=%(run_id)s | %(name)s | %(message)s"
    )

    class RunIdFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            record.run_id = run_id
            return True

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(RunIdFilter())

    file_handler = logging.FileHandler(log_dir / f"{run_id}.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(RunIdFilter())

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    return logger
