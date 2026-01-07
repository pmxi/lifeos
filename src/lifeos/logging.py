import logging
import os
from datetime import datetime, timezone


class UTCFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def setup():
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    formatter = UTCFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    handlers = [
        logging.StreamHandler(),
        logging.FileHandler("lifeos.log"),
    ]
    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(level=level, handlers=handlers)
