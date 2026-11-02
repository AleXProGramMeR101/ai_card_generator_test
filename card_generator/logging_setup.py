"""Настройка логирования через loguru: консоль и файл logs/app.log с ротацией по 100 МБ."""

import sys
from pathlib import Path

from loguru import logger

CONSOLE_FORMAT = "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}"


def setup_logging(log_dir: Path, console_level: str = "INFO") -> Path:
    """Настраивает вывод логов в консоль и в файл.

    Args:
        log_dir: Каталог для файла логов.
        console_level: Минимальный уровень сообщений в консоли.

    Returns:
        Путь к файлу логов.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"
    logger.remove()
    logger.add(sys.stderr, level=console_level, format=CONSOLE_FORMAT, colorize=True)
    logger.add(
        log_file,
        level="DEBUG",
        format=FILE_FORMAT,
        rotation="100 MB",
        retention=3,
        encoding="utf-8",
        backtrace=True,
        diagnose=False,
    )
    return log_file
