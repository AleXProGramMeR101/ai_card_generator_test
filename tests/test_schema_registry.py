"""Тесты схем категорий."""

from pathlib import Path

import pytest
import yaml

from card_generator.models import ProductInput
from card_generator.schema_registry import (
    CategorySchema,
    SchemaError,
    SchemaField,
    detect_schema,
    load_schemas,
    save_suggested_schema,
    schema_from_suggestion,
)


def test_manometer_detected_by_name(schemas: list[CategorySchema]) -> None:
    """Манометр определяется по слову в названии."""
    schema = detect_schema(ProductInput(name="МП4-У - манометр показывающий"), schemas)
    assert schema is not None and schema.name == "манометр"


def test_category_field_is_used(schemas: list[CategorySchema]) -> None:
    """Поле category тоже участвует в определении категории."""
    schema = detect_schema(ProductInput(name="ДМ 02-100", category="Манометры"), schemas)
    assert schema is not None and schema.name == "манометр"


def test_unknown_category(schemas: list[CategorySchema]) -> None:
    """Для товара без схемы возвращается None."""
    assert detect_schema(ProductInput(name="Паяльная станция Quick 203H"), schemas) is None


def test_longer_keyword_wins() -> None:
    """Более длинное ключевое слово имеет приоритет."""
    short = CategorySchema(name="термометр", keywords=["термометр"], fields=[])
    long = CategorySchema(name="термометр биметаллический", keywords=["термометр биметаллический"], fields=[])
    product = ProductInput(name="Термометр биметаллический ТБ-2")
    assert detect_schema(product, [short, long]) is long


@pytest.mark.parametrize(
    ("key", "field_name"),
    [
        ("Диаметр корпуса (мм)", "диаметр корпуса"),
        ("Резьба присоединительного штуцера", "резьба присоединения"),
        ("присоединение", "резьба присоединения"),
        ("Корпус", "материал корпуса"),
        ("Класс точности прибора", "класс точности"),
    ],
)
def test_aliases_match(schemas: list[CategorySchema], key: str, field_name: str) -> None:
    """Названия с сайта сопоставляются с полями схемы через синонимы."""
    schema = next(item for item in schemas if item.name == "манометр")
    found = schema.find_field(key)
    assert found is not None and found.name == field_name


def test_unrelated_key_does_not_match(schemas: list[CategorySchema]) -> None:
    """Посторонняя характеристика не сопоставляется с полями схемы."""
    schema = next(item for item in schemas if item.name == "манометр")
    assert schema.find_field("Масса прибора") is None


def test_broken_schema_file(tmp_path: Path) -> None:
    """Ошибка в YAML-файле схемы сообщается с именем файла."""
    (tmp_path / "bad.yaml").write_text("name: x\nfields: 5\n", encoding="utf-8")
    with pytest.raises(SchemaError, match="bad.yaml"):
        load_schemas(tmp_path)


def test_suggested_schema_saved_and_loadable(tmp_path: Path) -> None:
    """Предложенная схема сохраняется в подкаталог и читается как обычная."""
    schema = schema_from_suggestion("Гигрометр психрометрический", ["диапазон влажности", "диапазон влажности", " "])
    path = save_suggested_schema(schema, tmp_path)
    assert path.parent.name == "suggested"
    loaded = CategorySchema.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    assert loaded.fields == [SchemaField(name="диапазон влажности")]
    assert loaded.keywords == ["гигрометр психрометрический"]
    assert load_schemas(tmp_path) == []
