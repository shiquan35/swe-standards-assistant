import sys

from loguru import logger as _loguru_logger

from app.core.env import env

app_logger = _loguru_logger
app_logger.remove()
app_logger.add(
    sys.stderr,
    colorize=True,
    format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>",
    level=10,
)

if env.ENVIRONMENT == "production":
    app_logger.add("logs/log.log", rotation="1 MB", level="DEBUG", compression="zip")
