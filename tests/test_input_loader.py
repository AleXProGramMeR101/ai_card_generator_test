"""Тесты чтения и проверки входных данных."""

from pathlib import Path

import pytest

from card_generator.config import PROJECT_ROOT
from card_generator.input_loader import (
    InputError,
    collect_input_files,
    load_products,
    parse_products,
    validate_product,
)


def test_single_object_is_wrapped_in_list() -> None:
    """Один объект превращается в список из одного товара."""
    assert parse_products('{"name": "Манометр"}', "test.json") == [{"name": "Манометр"}]


def test_list_of_products() -> None:
    """Список товаров разбирается целиком."""
    assert len(parse_products('[{"name": "А"}, {"name": "Б"}]', "test.json")) == 2


def test_broken_json_reports_line_and_column() -> None:
    """Для битого JSON сообщается строка и столбец ошибки."""
    path = PROJECT_ROOT / "examples" / "bad_input" / "broken_syntax.json"
    with pytest.raises(InputError, match=r"строка 4, столбец 3"):
        load_products(path)


@pytest.mark.parametrize("text", ["", "   ", "[]", "42", '["строка"]'])
def test_unsupported_json_is_rejected(text: str) -> None:
    """Пустой файл, пустой список и не-объекты отклоняются."""
    with pytest.raises(InputError):
        parse_products(text, "test.json")


def test_utf8_with_bom_is_read(tmp_path: Path) -> None:
    """Файл из «Блокнота» Windows с BOM читается корректно."""
    path = tmp_path / "bom.json"
    path.write_bytes('{"name": "Манометр"}'.encode("utf-8-sig"))
    assert load_products(path)[0]["name"] == "Манометр"


def test_cp1251_file_is_read(tmp_path: Path) -> None:
    """Файл в кодировке Windows-1251 тоже читается."""
    path = tmp_path / "cp1251.json"
    path.write_bytes('{"name": "Манометр"}'.encode("cp1251"))
    assert load_products(path)[0]["name"] == "Манометр"


def test_empty_name_is_rejected() -> None:
    """Пустое название - ошибка с понятным текстом."""
    with pytest.raises(InputError, match="name: поле не может быть пустым"):
        validate_product({"name": "  "})


def test_missing_name_is_rejected() -> None:
    """Отсутствующее название - ошибка с понятным текстом."""
    with pytest.raises(InputError, match="name: обязательное поле отсутствует"):
        validate_product({"specs": {}})


def test_specs_must_be_object() -> None:
    """specs в виде списка отклоняется с подсказкой о формате."""
    with pytest.raises(InputError, match="specs должен быть объектом"):
        validate_product({"name": "Термометр", "specs": ["0–100 °С"]})


def test_empty_values_become_none() -> None:
    """Пустые строки и null считаются отсутствующими значениями."""
    product = validate_product(
        {"name": "Манометр", "description": "  ", "specs": {"класс точности": "", "диапазон": None}}
    )
    assert product.description is None
    assert product.filled_specs() == {}
    assert product.empty_spec_keys() == ["класс точности", "диапазон"]


def test_numeric_and_list_values_become_strings() -> None:
    """Числа и списки в specs приводятся к строкам."""
    product = validate_product({"name": "Манометр", "specs": {"диаметр": 100, "резьба": ["G1/2", "M20x1,5"]}})
    assert product.specs == {"диаметр": "100", "резьба": "G1/2; M20x1,5"}


def test_extra_fields_are_kept() -> None:
    """Дополнительные поля не ломают проверку и сохраняются."""
    product = validate_product({"name": "Манометр", "sku": "63859"})
    assert product.extra_fields() == {"sku": "63859"}


def test_collect_files_from_directory() -> None:
    """Из каталога берутся все JSON-файлы по алфавиту."""
    files = collect_input_files([PROJECT_ROOT / "examples" / "input"])
    assert [file.name for file in files] == ["dm-02.json", "mp3-u.json", "mp4-u.json", "vit-2.json"]


def test_collect_files_missing_path(tmp_path: Path) -> None:
    """Несуществующий путь - понятная ошибка."""
    with pytest.raises(InputError, match="не найден"):
        collect_input_files([tmp_path / "nope.json"])


def test_too_large_product_is_rejected() -> None:
    """Слишком большой объём текста одного товара отклоняется до запроса к модели."""
    with pytest.raises(InputError, match="слишком много текста"):
        validate_product({"name": "Манометр", "description": "а" * 500}, max_chars=100)


def test_size_limit_disabled_by_zero() -> None:
    """Ограничение 0 означает «без ограничения»."""
    assert validate_product({"name": "Манометр", "description": "а" * 500}, max_chars=0).name == "Манометр"
