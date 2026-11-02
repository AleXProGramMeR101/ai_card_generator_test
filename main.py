"""Точка входа: генерирует черновики карточек товаров из JSON-файлов.

Пример запуска: python main.py examples/input
"""

import argparse
import sys
import time
from pathlib import Path

from loguru import logger

from card_generator.config import get_settings
from card_generator.input_loader import InputError, collect_input_files, load_products, validate_product
from card_generator.llm_client import LLMClient, LLMError
from card_generator.logging_setup import setup_logging
from card_generator.models import CardResult
from card_generator.output_writer import save_result
from card_generator.pipeline import CardGenerator, InsufficientDataError
from card_generator.schema_registry import SchemaError, load_schemas


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Разбирает аргументы командной строки.

    Args:
        argv: Аргументы; None - взять из sys.argv.

    Returns:
        Разобранные аргументы.
    """
    parser = argparse.ArgumentParser(description="Черновики карточек товаров для B2B-магазина КИП")
    parser.add_argument("paths", nargs="+", type=Path, help="JSON-файлы или каталоги с ними")
    parser.add_argument("-o", "--output-dir", type=Path, default=None, help="куда сохранить результаты")
    return parser.parse_args(argv)


def report_result(result: CardResult, json_path: Path, markdown_path: Path) -> None:
    """Выводит в консоль краткую сводку по карточке.

    Args:
        result: Результат генерации.
        json_path: Путь к JSON-файлу.
        markdown_path: Путь к Markdown-файлу.
    """
    quality = result.quality
    log = logger.success if quality.status == "ok" else logger.warning
    log(
        "«{}»: {} | заполненность {:.0%} | попыток: {} | {}, {}",
        result.input.get("name"),
        "готово" if quality.status == "ok" else "требует проверки",
        quality.completeness,
        quality.attempts,
        json_path,
        markdown_path.name,
    )
    missing = [item.name for item in quality.missing_fields if item.critical]
    if missing:
        logger.warning("  нет важных данных: {}", ", ".join(missing))
    for item in quality.needs_clarification:
        logger.warning("  уточнить: {}", item)
    for item in quality.warnings:
        logger.warning("  проверка не пройдена: {}", item)


def process_file(path: Path, generator: CardGenerator, output_dir: Path, max_chars: int = 0) -> int:
    """Обрабатывает все товары из одного файла.

    Args:
        path: Путь к JSON-файлу.
        generator: Генератор карточек.
        output_dir: Каталог для результатов.
        max_chars: Предельный объём текста одного товара; 0 - без ограничения.

    Returns:
        Количество товаров, которые не удалось обработать.
    """
    logger.info("Файл {}", path)
    try:
        raw_products = load_products(path)
    except (InputError, OSError) as error:
        logger.error("{}", error)
        return 1
    failed = 0
    for index, raw in enumerate(raw_products, start=1):
        label = f"{path.name}, товар №{index}"
        try:
            product = validate_product(raw, max_chars)
            started = time.perf_counter()
            result = generator.generate(product)
            json_path, markdown_path = save_result(result, output_dir)
            logger.debug("{}: обработан за {:.1f} c", label, time.perf_counter() - started)
            report_result(result, json_path, markdown_path)
        except InputError as error:
            logger.error("{}: некорректные данные - {}", label, error)
            failed += 1
        except InsufficientDataError as error:
            logger.error("{}: {}. Добавьте: {}", label, error, ", ".join(error.missing))
            failed += 1
        except LLMError as error:
            logger.error("{}: {}", label, error)
            failed += 1
        except Exception:
            logger.exception("{}: непредвиденная ошибка, подробности в файле логов", label)
            failed += 1
    return failed


def main(argv: list[str] | None = None) -> int:
    """Запускает генерацию карточек для переданных файлов.

    Args:
        argv: Аргументы командной строки; None - взять из sys.argv.

    Returns:
        Код выхода: 0 - всё обработано, 1 - были ошибки.
    """
    args = parse_args(argv)
    settings = get_settings()
    log_file = setup_logging(settings.log_dir)
    output_dir = args.output_dir or settings.output_dir
    logger.info("Модель: {} ({}), логи: {}", settings.llm_model, settings.llm_base_url, log_file)
    if not settings.llm_api_key:
        logger.warning("LLM_API_KEY не задан: для облачных провайдеров впишите ключ в файл .env")
    try:
        files = collect_input_files(args.paths)
        schemas = load_schemas(settings.schemas_dir)
    except (InputError, SchemaError) as error:
        logger.error("{}", error)
        return 1
    generator = CardGenerator(
        llm=LLMClient(settings),
        schemas=schemas,
        schemas_dir=settings.schemas_dir,
        repair_attempts=settings.repair_attempts,
    )
    failed = sum(process_file(path, generator, output_dir, settings.max_product_chars) for path in files)
    if failed:
        logger.error("Готово с ошибками: не обработано {}", failed)
        return 1
    logger.success("Готово, результаты в {}", output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
