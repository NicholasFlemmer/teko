import logging
import os
import sys


def configure_logging():
    """Configure root logging so INFO and above reach stdout, in a format
    Cloud Run captures and can parse (timestamp, level, logger name,
    message).

    Must run before any other module logs anything -- app.py calls this
    as the very first thing, before any other import, since several
    modules call logger.info()/logger.error() during initialization
    (e.g. FirebaseService.initialize()).

    LOG_LEVEL defaults to INFO and is only meant to be overridden locally
    for debugging -- never set it to DEBUG in production. DEBUG-level log
    lines are allowed to carry more detail (e.g. message length) than
    INFO-level ones and are for local debugging only.

    Returns the resolved logging level (int) so callers can verify it.
    """
    log_level_name = os.environ.get('LOG_LEVEL', 'INFO').upper()
    level = getattr(logging, log_level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
        stream=sys.stdout,
        force=True,
    )
    return level
