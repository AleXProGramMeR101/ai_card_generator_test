"""Сборка таблицы характеристик и отчёта о полноте данных."""

import re
from dataclasses import dataclass, field

from card_generator.models import NO_DATA, ExtractedSpec, MissingField, ProductInput, SpecRow
from card_generator.schema_registry import CategorySchema
from card_generator.text_utils import UNIT_IN_KEY_PATTERN

NUMERIC_VALUE_PATTERN = re.compile(r"^[\d\s.,;…\-–х*x]+$")


@dataclass
class SpecsSplit:
    """Характеристики товара, разделённые на попавшие в схему и остальные."""

    matched: dict[str, str] = field(default_factory=dict)
    other: dict[str, str | None] = field(default_factory=dict)


def capitalize(text: str) -> str:
    """Делает первую букву заглавной, не трогая остальные.

    Args:
        text: Исходная строка.

    Returns:
        Строка с заглавной первой буквой.
    """
    return text[:1].upper() + text[1:]


def value_with_unit(key: str, value: str) -> str:
    """Переносит единицу измерения из названия в значение, если значение - только число.

    Args:
        key: Название характеристики, например «Диаметр корпуса (мм)».
        value: Значение, например «160».

    Returns:
        Значение с единицей, например «160 мм».
    """
    match = UNIT_IN_KEY_PATTERN.search(key.strip())
    if not match or not NUMERIC_VALUE_PATTERN.match(value):
        return value
    unit = (match.group(1) or match.group(2)).strip()
    return f"{value} {unit}"


def split_specs(product: ProductInput, schema: CategorySchema | None) -> SpecsSplit:
    """Сопоставляет характеристики товара с полями схемы.

    Args:
        product: Товар.
        schema: Схема категории или None.

    Returns:
        Характеристики схемы с найденными значениями и все остальные.
    """
    result = SpecsSplit()
    for key, value in product.specs.items():
        schema_field = schema.find_field(key) if schema else None
        if schema_field and value and schema_field.name not in result.matched:
            result.matched[schema_field.name] = value_with_unit(key, value)
        elif schema_field and not value:
            continue
        else:
            result.other[key] = value
    return result


def build_key_specs(
    schema: CategorySchema | None,
    split: SpecsSplit,
    extracted: list[ExtractedSpec],
) -> list[SpecRow]:
    """Строит таблицу характеристик: сначала поля схемы по порядку, затем остальные.

    Args:
        schema: Схема категории или None.
        split: Характеристики из входного JSON.
        extracted: Подтверждённые характеристики из описания.

    Returns:
        Строки таблицы характеристик.
    """
    from_description: dict[str, str] = {}
    unmatched_extracted: list[ExtractedSpec] = []
    for spec in extracted:
        schema_field = schema.find_field(spec.name) if schema else None
        if schema_field:
            from_description.setdefault(schema_field.name, spec.value)
        else:
            unmatched_extracted.append(spec)
    rows: list[SpecRow] = []
    for schema_field in schema.fields if schema else []:
        name = capitalize(schema_field.name)
        if schema_field.name in split.matched:
            rows.append(SpecRow(name=name, value=split.matched[schema_field.name], source="specs"))
        elif schema_field.name in from_description:
            rows.append(SpecRow(name=name, value=from_description[schema_field.name], source="description"))
        else:
            rows.append(SpecRow(name=name, value=NO_DATA, source="none"))
    for key, value in split.other.items():
        rows.append(SpecRow(name=key, value=value or NO_DATA, source="specs" if value else "none"))
    known = {row.name.lower() for row in rows}
    for spec in unmatched_extracted:
        if spec.name.lower() not in known:
            rows.append(SpecRow(name=capitalize(spec.name), value=spec.value, source="description"))
    return rows


def critical_from_description(
    schema: CategorySchema | None,
    split: SpecsSplit,
    extracted: list[ExtractedSpec],
) -> list[str]:
    """Отмечает важные характеристики, значение которых взято из описания, а не из характеристик.

    Args:
        schema: Схема категории или None.
        split: Характеристики из входного JSON.
        extracted: Подтверждённые характеристики из описания.

    Returns:
        Пункты для раздела «Требует уточнения».
    """
    if schema is None:
        return []
    notes = []
    for spec in extracted:
        schema_field = schema.find_field(spec.name)
        if schema_field and schema_field.critical and schema_field.name not in split.matched:
            notes.append(
                f"Важная характеристика «{capitalize(schema_field.name)}: {spec.value}» взята из описания, "
                f"а не из характеристик (цитата: «{spec.quote}») - проверьте, что это именно она"
            )
    return notes


def find_missing(schema: CategorySchema | None, rows: list[SpecRow]) -> list[MissingField]:
    """Составляет список характеристик без данных.

    Args:
        schema: Схема категории или None.
        rows: Таблица характеристик.

    Returns:
        Список отсутствующих характеристик с пометкой важности.
    """
    critical = {capitalize(item.name) for item in schema.fields if item.critical} if schema else set()
    return [MissingField(name=row.name, critical=row.name in critical) for row in rows if row.source == "none"]


def completeness(schema: CategorySchema | None, rows: list[SpecRow]) -> float:
    """Считает долю заполненных ожидаемых характеристик.

    Args:
        schema: Схема категории или None.
        rows: Таблица характеристик.

    Returns:
        Число от 0 до 1; без схемы считается по всем строкам таблицы.
    """
    expected = {capitalize(item.name) for item in schema.fields} if schema else {row.name for row in rows}
    if not expected:
        return 0.0
    filled = sum(1 for row in rows if row.name in expected and row.source != "none")
    return round(filled / len(expected), 2)
