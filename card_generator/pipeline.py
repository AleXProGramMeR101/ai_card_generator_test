"""Генерация карточки товара: подготовка данных, запрос к модели, проверки и сборка результата."""

from pathlib import Path

from loguru import logger
from pydantic import ValidationError

from card_generator.card_builder import (
    build_key_specs,
    completeness,
    critical_from_description,
    find_missing,
    split_specs,
)
from card_generator.fact_check import CheckReport, check_draft
from card_generator.input_quality import find_input_issues
from card_generator.length_fit import fit_draft
from card_generator.llm_client import JSON_VALIDATE_FAILED, ChatModel, LLMError, parse_json_object
from card_generator.models import Card, CardResult, LLMDraft, ProductInput, QualityReport
from card_generator.prompts import SYSTEM_PROMPT, build_repair_prompt, build_user_prompt
from card_generator.schema_registry import (
    CategorySchema,
    detect_schema,
    save_suggested_schema,
    schema_from_suggestion,
)
from card_generator.text_utils import is_similar_key, strip_unit


class InsufficientDataError(Exception):
    """Данных о товаре слишком мало, чтобы писать карточку без выдумок."""

    def __init__(self, message: str, missing: list[str]) -> None:
        """Создаёт ошибку со списком недостающих данных.

        Args:
            message: Текст ошибки.
            missing: Что нужно добавить во входные данные.
        """
        super().__init__(message)
        self.missing = missing


def describe_format_error(error: ValueError) -> str:
    """Кратко описывает, чем ответ модели не соответствует формату.

    Args:
        error: Ошибка разбора JSON или валидации Pydantic.

    Returns:
        Описание проблемы для повторного запроса.
    """
    if isinstance(error, ValidationError):
        fields = sorted({".".join(str(part) for part in item["loc"]) for item in error.errors()})
        return f"ответ не соответствует структуре, проблемные поля: {', '.join(fields)}"
    return f"ответ не является корректным JSON-объектом ({error})"


class CardGenerator:
    """Генератор черновиков карточек товаров."""

    def __init__(
        self,
        llm: ChatModel,
        schemas: list[CategorySchema],
        schemas_dir: Path,
        repair_attempts: int = 1,
    ) -> None:
        """Создаёт генератор.

        Args:
            llm: Клиент модели.
            schemas: Схемы категорий.
            schemas_dir: Каталог схем, куда сохраняются предложенные моделью схемы.
            repair_attempts: Сколько раз просить модель исправить ответ.
        """
        self._llm = llm
        self._schemas = schemas
        self._schemas_dir = schemas_dir
        self._repair_attempts = max(repair_attempts, 0)

    def generate(self, product: ProductInput) -> CardResult:
        """Готовит черновик карточки для одного товара.

        Args:
            product: Проверенные данные о товаре.

        Returns:
            Карточка, исходные данные и отчёт о качестве.
        """
        schema = detect_schema(product, self._schemas)
        logger.info("Товар «{}»: категория - {}", product.name, schema.name if schema else "не определена по схемам")
        self._ensure_enough_data(product, schema)
        split = split_specs(product, schema)
        present = [item.name for item in schema.fields if item.name in split.matched] if schema else []
        absent = [item.name for item in schema.fields if item.name not in split.matched] if schema else []
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(product, schema, present, absent)},
        ]
        draft, report, attempts = self._request_draft(messages, product)
        clarifications = find_input_issues(product)
        schema_source = "config" if schema else "llm_suggested"
        if schema is None:
            schema = self._build_suggested_schema(product, draft)
            if schema is not None:
                saved = save_suggested_schema(schema, self._schemas_dir)
                logger.info("Схема категории «{}» предложена моделью и сохранена на проверку: {}", schema.name, saved)
                clarifications.append(
                    f"Категории «{schema.name}» нет в схемах: список характеристик предложен моделью "
                    f"и сохранён в schemas/suggested/{saved.name} - проверьте его"
                )
            split = split_specs(product, schema)
        rows = build_key_specs(schema, split, report.verified_specs)
        missing = find_missing(schema, rows)
        card_texts = {
            "SEO-заголовок": draft.seo_title,
            "SEO-описание": draft.seo_description,
            "поисковые запросы": " ".join(draft.search_queries),
            "блок для менеджера": " ".join(draft.manager_note.suitable_for + draft.manager_note.solves),
        }
        clarifications += critical_from_description(schema, split, report.verified_specs, card_texts)
        clarifications += draft.clarifications
        needs_review = bool(report.problems or clarifications or any(item.critical for item in missing))
        quality = QualityReport(
            status="needs_review" if needs_review else "ok",
            category=schema.name if schema else (draft.category or None),
            schema_source=schema_source,
            completeness=completeness(schema, rows),
            missing_fields=missing,
            needs_clarification=clarifications,
            warnings=report.problems,
            dropped_specs=report.dropped_specs,
            attempts=attempts,
            model=self._llm.model,
        )
        card = Card(
            seo_title=draft.seo_title.strip(),
            seo_title_length=len(draft.seo_title.strip()),
            seo_description=draft.seo_description.strip(),
            seo_description_length=len(draft.seo_description.strip()),
            key_specs=rows,
            search_queries=[query.strip() for query in draft.search_queries if query.strip()],
            manager_note=draft.manager_note,
        )
        return CardResult(input=product.model_dump(exclude_none=True), card=card, quality=quality)

    def _build_suggested_schema(self, product: ProductInput, draft: LLMDraft) -> CategorySchema | None:
        """Строит схему для товара без категории: имеющиеся характеристики плюс предложенные моделью.

        Предложения, повторяющие имеющиеся характеристики другими словами, отбрасываются.

        Args:
            product: Товар.
            draft: Ответ модели.

        Returns:
            Схема категории или None, если строить её не из чего.
        """
        suggested = []
        for name in draft.suggested_fields:
            duplicate_of = next((key for key in product.specs if is_similar_key(name, key)), None)
            if duplicate_of:
                logger.debug("Предложенная характеристика «{}» повторяет «{}», пропущена", name, duplicate_of)
            else:
                suggested.append(name)
        field_names = [strip_unit(key) for key in product.specs] + suggested
        if not field_names:
            return None
        return schema_from_suggestion(draft.category or product.name, field_names)

    def _ensure_enough_data(self, product: ProductInput, schema: CategorySchema | None) -> None:
        """Останавливает генерацию, если, кроме названия, данных нет совсем.

        Args:
            product: Товар.
            schema: Схема категории или None.
        """
        if product.filled_specs() or product.description:
            return
        missing = ["specs или description"]
        if schema:
            missing.extend(item.name for item in schema.fields if item.critical)
        raise InsufficientDataError(
            "Недостаточно данных: кроме названия ничего нет, карточка получилась бы выдуманной",
            missing,
        )

    def _request_draft(
        self, messages: list[dict[str, str]], product: ProductInput
    ) -> tuple[LLMDraft, CheckReport, int]:
        """Запрашивает черновик и при ошибках просит модель исправиться.

        Args:
            messages: Системное и пользовательское сообщения.
            product: Товар.

        Returns:
            Лучший черновик, отчёт о его проверке и число сделанных запросов.
        """
        best: tuple[LLMDraft, CheckReport] | None = None
        total_attempts = self._repair_attempts + 1
        last_finish_reason = None
        for attempt in range(1, total_attempts + 1):
            response = self._llm.chat(messages)
            last_finish_reason = response.finish_reason
            try:
                draft = LLMDraft.model_validate(parse_json_object(response.content))
            except ValueError as error:
                problems = [describe_format_error(error)]
            else:
                draft, fit_notes = fit_draft(draft)
                for note in fit_notes:
                    logger.info("Попытка {}: {} кодом по границе предложения", attempt, note)
                report = check_draft(draft, product)
                problems = report.all_problems
                if best is None or len(problems) < len(best[1].all_problems):
                    best = (draft, report)
                if not problems:
                    return draft, report, attempt
            logger.warning("Попытка {} из {}: найдено проблем - {}", attempt, total_attempts, len(problems))
            for problem in problems:
                logger.debug("Проблема: {}", problem)
            if attempt < total_attempts:
                messages = messages + [{"role": "user", "content": build_repair_prompt(problems)}]
                if response.content:
                    messages.insert(-1, {"role": "assistant", "content": response.content})
        if best is None:
            hint = ""
            if last_finish_reason == "length":
                hint = ": ответ обрезан по лимиту токенов, увеличьте LLM_MAX_TOKENS"
            elif last_finish_reason == JSON_VALIDATE_FAILED:
                hint = ": модель не справилась с JSON, попробуйте другую модель"
            raise LLMError(f"Модель не вернула корректный JSON за {total_attempts} попытк(и){hint}")
        return best[0], best[1], total_attempts
