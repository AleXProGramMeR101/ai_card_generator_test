"""Модели данных: входной товар, ответ LLM и итоговая карточка."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SpecSource = Literal["specs", "description", "none"]
CardStatus = Literal["ok", "needs_review"]
SchemaSource = Literal["config", "llm_suggested"]

NO_DATA = "данных нет"


def _empty_to_none(value: Any) -> Any:
    """Превращает пустые строки в None, остальное возвращает как есть.

    Args:
        value: Исходное значение поля.

    Returns:
        None для пустой строки, иначе исходное значение.
    """
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _spec_value_to_str(value: Any) -> str | None:
    """Приводит значение характеристики к строке.

    Args:
        value: Значение из входного JSON: строка, число, список или null.

    Returns:
        Строковое значение или None, если значение пустое.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = [_spec_value_to_str(item) for item in value]
        joined = "; ".join(part for part in parts if part)
        return joined or None
    if isinstance(value, dict):
        raise ValueError("значение характеристики не может быть объектом")
    text = str(value).strip()
    return text or None


class ProductInput(BaseModel):
    """Входные данные о товаре."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    name: str = Field(min_length=1)
    manufacturer: str | None = None
    category: str | None = None
    specs: dict[str, str | None] = Field(default_factory=dict)
    description: str | None = None

    @field_validator("manufacturer", "category", "description", mode="before")
    @classmethod
    def _blank_strings(cls, value: Any) -> Any:
        """Считает пустые строки отсутствующими значениями.

        Args:
            value: Исходное значение поля.

        Returns:
            None для пустой строки, иначе исходное значение.
        """
        return _empty_to_none(value)

    @field_validator("specs", mode="before")
    @classmethod
    def _normalize_specs(cls, value: Any) -> dict[str, str | None]:
        """Проверяет, что specs - объект, и приводит значения к строкам.

        Args:
            value: Исходное значение поля specs.

        Returns:
            Словарь «характеристика → значение или None».
        """
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError('specs должен быть объектом вида {"характеристика": "значение"}')
        normalized: dict[str, str | None] = {}
        for key, raw in value.items():
            clean_key = str(key).strip()
            if clean_key:
                normalized[clean_key] = _spec_value_to_str(raw)
        return normalized

    def filled_specs(self) -> dict[str, str]:
        """Возвращает только заполненные характеристики.

        Returns:
            Словарь характеристик с непустыми значениями.
        """
        return {key: value for key, value in self.specs.items() if value}

    def empty_spec_keys(self) -> list[str]:
        """Возвращает характеристики, переданные с пустым значением.

        Returns:
            Список названий пустых характеристик.
        """
        return [key for key, value in self.specs.items() if not value]

    def extra_fields(self) -> dict[str, Any]:
        """Возвращает поля, которых нет в формате входных данных.

        Returns:
            Словарь дополнительных полей.
        """
        return dict(self.model_extra or {})


class ExtractedSpec(BaseModel):
    """Характеристика, найденная моделью в тексте описания."""

    name: str
    value: str
    quote: str


class ManagerNote(BaseModel):
    """Блок для менеджера: кому подходит прибор и какие задачи решает."""

    suitable_for: list[str] = Field(default_factory=list)
    solves: list[str] = Field(default_factory=list)


class LLMDraft(BaseModel):
    """Ответ модели в формате JSON."""

    model_config = ConfigDict(extra="ignore")

    category: str = ""
    suggested_fields: list[str] = Field(default_factory=list)
    extracted_specs: list[ExtractedSpec] = Field(default_factory=list)
    seo_title: str
    seo_description: str
    search_queries: list[str]
    manager_note: ManagerNote
    clarifications: list[str] = Field(default_factory=list)


class SpecRow(BaseModel):
    """Строка таблицы характеристик карточки."""

    name: str
    value: str
    source: SpecSource


class MissingField(BaseModel):
    """Характеристика, которой нет во входных данных."""

    name: str
    critical: bool


class Card(BaseModel):
    """Черновик карточки товара."""

    seo_title: str
    seo_title_length: int
    seo_description: str
    seo_description_length: int
    key_specs: list[SpecRow]
    search_queries: list[str]
    manager_note: ManagerNote


class QualityReport(BaseModel):
    """Отчёт о полноте данных и проверках сгенерированного текста."""

    status: CardStatus
    category: str | None
    schema_source: SchemaSource
    completeness: float
    missing_fields: list[MissingField]
    needs_clarification: list[str]
    warnings: list[str]
    dropped_specs: list[str]
    attempts: int
    model: str


class CardResult(BaseModel):
    """Итог обработки товара: исходные данные, карточка и отчёт."""

    input: dict[str, Any]
    card: Card
    quality: QualityReport
