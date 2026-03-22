from loguru import logger


def setup_logging(level: str = "INFO", log_file: str = "logs/screening.log", console: bool = True):
    logger.remove()
    level_map = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
    log_level = level_map.get(level.upper(), 20)
    if console:
        logger.add(
            __import__("sys").stderr,
            level=log_level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        )
    logger.add(
        log_file,
        rotation="100 MB",
        retention="7 days",
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    )
    logger.info(f"Logging initialized: level={level}, file={log_file}")
