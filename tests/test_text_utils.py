"""Тесты текстовых утилит."""

import pytest

from card_generator.text_utils import (
    extract_numbers,
    is_similar_key,
    normalize_key,
    normalize_number,
    normalize_text,
    slugify,
    strip_unit,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1,5", "1.5"), ("1.50", "1.5"), ("1.0", "1"), ("0,6", "0.6"), ("007", "7"), ("0", "0"), ("160", "160")],
)
def test_normalize_number(raw: str, expected: str) -> None:
    """Разные записи одного числа приводятся к одному виду."""
    assert normalize_number(raw) == expected


def test_extract_numbers_from_specs_text() -> None:
    """Из технического текста извлекаются все числа."""
    assert extract_numbers("0–1,6 МПа, G1/2, IP54, кгс/см²") == {"0", "1.6", "1", "2", "54"}


def test_normalize_text_unifies_dashes_and_spaces() -> None:
    """Тире, неразрывные пробелы, регистр и «ё» приводятся к одному виду."""
    assert normalize_text("Ёмкость  0–1,6") == "емкость 0-1,6"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Диаметр корпуса (мм)", "диаметр корпуса"),
        ("Диапазон измерения влажности, %", "диапазон измерения влажности"),
        ("  Класс   точности ", "класс точности"),
    ],
)
def test_normalize_key(raw: str, expected: str) -> None:
    """Названия характеристик очищаются от единиц и знаков препинания."""
    assert normalize_key(raw) == expected


def test_slugify_transliterates_cyrillic() -> None:
    """Кириллица переводится в латиницу для имени файла."""
    assert slugify("МП4-У - манометр показывающий") == "mp4-u-manometr-pokazyvayuschiy"


def test_slugify_fallback() -> None:
    """Если от названия ничего не осталось, используется запасное имя."""
    assert slugify("!!!") == "product"


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ("Рабочий диапазон влажности", "Диапазон измерения влажности, %", True),
        ("Цена деления", "Цена деления шкалы, °С", True),
        ("Погрешность измерения влажности", "Диапазон измерения влажности, %", False),
        ("Диапазон измерений", "Диапазон измерения температуры, °С", False),
        ("Питание", "Термометрическая жидкость", False),
    ],
)
def test_is_similar_key(first: str, second: str, expected: bool) -> None:
    """Одна характеристика под разными названиями распознаётся, разные - нет."""
    assert is_similar_key(first, second) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Диапазон измерения влажности, %", "Диапазон измерения влажности"), ("Диаметр корпуса (мм)", "Диаметр корпуса"),
     ("Масса прибора", "Масса прибора")],
)
def test_strip_unit(raw: str, expected: str) -> None:
    """Единица измерения убирается из конца названия."""
    assert strip_unit(raw) == expected
