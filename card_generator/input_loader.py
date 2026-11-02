"""Чтение входных JSON-файлов и проверка данных о товаре."""

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from card_generator.models import ProductInput

ERROR_MESSAGES = {
    "missing": "обязательное поле отсутствует",
    "string_too_short": "поле не может быть пустым",
    "string_type": "ожидается строка",
    "dict_type": "ожидается объект",
}


class InputError(Exception):
    """Ошибка во входных данных, которую нужно показать пользователю."""


def collect_input_files(paths: list[Path]) -> list[Path]:
    """Собирает список JSON-файлов из переданных путей.

    Args:
        paths: Пути к файлам или каталогам.

    Returns:
        Отсортированный список JSON-файлов без повторов.
    """
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            found = sorted(path.glob("*.json"))
            if not found:
                raise InputError(f"В каталоге {path} нет файлов .json")
            files.extend(found)
        elif path.is_file():
            files.append(path)
        else:
            raise InputError(f"Файл или каталог не найден: {path}")
    return list(dict.fromkeys(files))


def decode_bytes(data: bytes) -> str:
    """Декодирует содержимое файла из UTF-8 (в том числе с BOM) или, если не вышло, из Windows-1251.

    Args:
        data: Содержимое файла.

    Returns:
        Текст файла.
    """
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1251", errors="replace")


def read_text(path: Path) -> str:
    """Читает текстовый файл с автоопределением кодировки.

    Args:
        path: Путь к файлу.

    Returns:
        Содержимое файла.
    """
    return decode_bytes(path.read_bytes())


def parse_products(text: str, source: str) -> list[dict[str, Any]]:
    """Разбирает JSON с одним товаром или списком товаров.

    Args:
        text: Содержимое JSON-файла.
        source: Название источника для сообщений об ошибках.

    Returns:
        Список «сырых» товаров в виде словарей.
    """
    if not text.strip():
        raise InputError(f"{source}: файл пустой")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise InputError(
            f"{source}: некорректный JSON - строка {error.lineno}, столбец {error.colno}: {error.msg}"
        ) from error
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list) and data and all(isinstance(item, dict) for item in data):
        return data
    raise InputError(f"{source}: ожидается объект товара или непустой список объектов")


def load_products(path: Path) -> list[dict[str, Any]]:
    """Читает файл и возвращает список «сырых» товаров.

    Args:
        path: Путь к JSON-файлу.

    Returns:
        Список товаров в виде словарей.
    """
    return parse_products(read_text(path), path.name)


def format_validation_error(error: ValidationError) -> str:
    """Превращает ошибку Pydantic в понятное сообщение на русском.

    Args:
        error: Ошибка валидации.

    Returns:
        Сообщение вида «name: поле не может быть пустым».
    """
    parts = []
    for item in error.errors():
        location = ".".join(str(part) for part in item["loc"]) or "товар"
        message = ERROR_MESSAGES.get(item["type"], item["msg"].removeprefix("Value error, "))
        parts.append(f"{location}: {message}")
    return "; ".join(parts)


def validate_product(raw: dict[str, Any], max_chars: int = 0) -> ProductInput:
    """Проверяет данные товара и приводит их к модели.

    Args:
        raw: Товар в виде словаря из JSON.
        max_chars: Предельный объём текста товара в символах; 0 - без ограничения.

    Returns:
        Проверенный товар.
    """
    try:
        product = ProductInput.model_validate(raw)
    except ValidationError as error:
        raise InputError(format_validation_error(error)) from error
    size = product_text_size(product)
    if max_chars and size > max_chars:
        raise InputError(
            f"слишком много текста для одного товара: {size} символов при пределе {max_chars}. "
            "Сократите описание до сути или увеличьте MAX_PRODUCT_CHARS"
        )
    return product


def product_text_size(product: ProductInput) -> int:
    """Считает объём текста товара, который уйдёт в модель.

    Args:
        product: Товар.

    Returns:
        Количество символов в названии, характеристиках и описании.
    """
    specs_size = sum(len(key) + len(value or "") for key, value in product.specs.items())
    return len(product.name) + len(product.manufacturer or "") + len(product.description or "") + specs_size
