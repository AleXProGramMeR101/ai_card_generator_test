"""Точка входа веб-интерфейса.

Пример запуска: python server.py
"""

import argparse
import sys

import uvicorn
from loguru import logger

from card_generator.config import Settings, get_settings
from card_generator.logging_setup import setup_logging
from card_generator.schema_registry import SchemaError
from card_generator.web_app import create_app


def parse_args(argv: list[str] | None, settings: Settings) -> argparse.Namespace:
    """Разбирает аргументы командной строки.

    Args:
        argv: Аргументы; None - взять из sys.argv.
        settings: Настройки со значениями по умолчанию.

    Returns:
        Разобранные аргументы.
    """
    parser = argparse.ArgumentParser(description="Веб-интерфейс генератора карточек товаров")
    parser.add_argument("--host", default=settings.web_host, help="адрес, на котором слушать (на сервере - 0.0.0.0)")
    parser.add_argument("--port", type=int, default=settings.web_port, help="порт")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Запускает веб-сервер.

    Args:
        argv: Аргументы командной строки; None - взять из sys.argv.

    Returns:
        Код выхода.
    """
    settings = get_settings()
    args = parse_args(argv, settings)
    setup_logging(settings.log_dir)
    if not settings.llm_api_key:
        logger.warning("LLM_API_KEY не задан: для облачных провайдеров впишите ключ в файл .env")
    try:
        app = create_app(settings)
    except SchemaError as error:
        logger.error("{}", error)
        return 1
    shown_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    logger.info("Модель: {} ({})", settings.llm_model, settings.llm_base_url)
    logger.success("Откройте в браузере: http://{}:{}", shown_host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=True, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
