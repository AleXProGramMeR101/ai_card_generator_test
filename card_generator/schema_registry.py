"""Схемы категорий товаров: ожидаемые характеристики, определение категории, сохранение предложенных схем."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from card_generator.models import ProductInput
from card_generator.text_utils import normalize_key, normalize_text, slugify

SUGGESTED_DIR_NAME = "suggested"


class SchemaError(Exception):
    """Ошибка в файле схемы категории."""


class SchemaField(BaseModel):
    """Ожидаемая характеристика категории."""

    name: str
    critical: bool = False
    aliases: list[str] = Field(default_factory=list)

    def matches(self, key: str) -> bool:
        """Проверяет, относится ли название характеристики из входных данных к этому полю.

        Args:
            key: Название характеристики из входного JSON.

        Returns:
            True, если название совпадает с полем или одним из синонимов.
        """
        normalized = normalize_key(key)
        return normalized in {normalize_key(name) for name in [self.name, *self.aliases]}


class CategorySchema(BaseModel):
    """Схема категории: ключевые слова для определения и список характеристик."""

    name: str
    keywords: list[str] = Field(default_factory=list)
    fields: list[SchemaField]

    def find_field(self, key: str) -> SchemaField | None:
        """Ищет поле схемы по названию характеристики.

        Args:
            key: Название характеристики из входного JSON.

        Returns:
            Поле схемы или None, если совпадения нет.
        """
        return next((field for field in self.fields if field.matches(key)), None)


def load_schemas(directory: Path) -> list[CategorySchema]:
    """Загружает все схемы категорий из каталога (без подкаталогов).

    Args:
        directory: Каталог с YAML-файлами схем.

    Returns:
        Список схем категорий.
    """
    schemas = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            schemas.append(CategorySchema.model_validate(data))
        except (yaml.YAMLError, ValidationError) as error:
            raise SchemaError(f"Ошибка в схеме {path.name}: {error}") from error
    return schemas


def detect_schema(product: ProductInput, schemas: list[CategorySchema]) -> CategorySchema | None:
    """Определяет категорию товара по ключевым словам в категории и названии.

    Более длинные ключевые слова проверяются первыми, чтобы «мановакуумметр» не путался с «манометром».

    Args:
        product: Товар.
        schemas: Доступные схемы категорий.

    Returns:
        Подходящая схема или None.
    """
    haystack = normalize_text(f"{product.category or ''} {product.name}")
    candidates = [(normalize_text(keyword), schema) for schema in schemas for keyword in schema.keywords]
    candidates.sort(key=lambda item: len(item[0]), reverse=True)
    return next((schema for keyword, schema in candidates if keyword and keyword in haystack), None)


def schema_from_suggestion(category: str, field_names: list[str]) -> CategorySchema:
    """Строит временную схему из характеристик, предложенных моделью.

    Args:
        category: Тип товара, определённый моделью.
        field_names: Названия характеристик.

    Returns:
        Схема категории.
    """
    unique_names = list(dict.fromkeys(name.strip() for name in field_names if name.strip()))
    keyword = normalize_text(category)
    return CategorySchema(
        name=category or "без категории",
        keywords=[keyword] if keyword else [],
        fields=[SchemaField(name=name) for name in unique_names],
    )


def save_suggested_schema(schema: CategorySchema, directory: Path) -> Path:
    """Сохраняет предложенную моделью схему на проверку человеку.

    Args:
        schema: Схема категории.
        directory: Основной каталог схем.

    Returns:
        Путь к сохранённому файлу.
    """
    target_dir = directory / SUGGESTED_DIR_NAME
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{slugify(schema.name)}.yaml"
    data = schema.model_dump(exclude={"fields": {"__all__": {"aliases"}}})
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path
