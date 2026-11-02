"""Проверки ответа модели: длины текстов, выдуманные числа, оценочные слова, подлинность цитат."""

import re
from dataclasses import dataclass, field

from card_generator.limits import (
    CHARS_PER_WORD,
    DESCRIPTION_MAX_LENGTH,
    DESCRIPTION_MIN_LENGTH,
    DESCRIPTION_TARGET_MAX,
    DESCRIPTION_TARGET_MIN,
    QUERIES_MAX,
    QUERIES_MIN,
    TITLE_MAX_LENGTH,
)
from card_generator.models import ExtractedSpec, LLMDraft, ProductInput
from card_generator.text_utils import extract_numbers, normalize_text
EVALUATIVE_PATTERNS = [
    re.compile(pattern)
    for pattern in [
        r"\bпрочн\w*",
        r"\bнадежн\w*",
        r"\bвысок\w* точн\w*",
        r"\bточн\w* (?:данн|показани)\w*",
        r"\bлегк\w* интегр\w*",
        r"\bкомпактн\w*",
        r"\bлучш\w*",
        r"\b\w*качествен\w*",
        r"\bэффективн\w*",
        r"\bсовременн\w*",
        r"\bдолговечн\w*",
        r"\bуникальн\w*",
        r"\bинновац\w*",
        r"\bуниверсальн\w*",
        r"\bпревосходн\w*",
        r"\bоптимальн\w*",
        r"\bстабильн\w*",
        r"\bобеспечива\w* (?:высок\w* |подтвержд\w* )?точност\w*",
        r"\bподтвержд\w* точност\w*",
    ]
]
SERVICE_PATTERNS = [
    re.compile(pattern)
    for pattern in [
        r"\bв описании\b",
        r"\bвходн\w* данн\w*",
        r"\bданных нет\b",
        r"\bнет (?:данных|сведений|информации)\b",
        r"\bотсутству\w* (?:данн|сведен|информац)\w*",
        r"\bне указан\w*",
        r"\bпредставител\w* производител\w*",
        r"\bсвяж\w*тесь\b",
        r"\bсвязаться\b",
    ]
]


@dataclass
class CheckReport:
    """Результат проверки ответа модели."""

    problems: list[str] = field(default_factory=list)
    verified_specs: list[ExtractedSpec] = field(default_factory=list)
    dropped_specs: list[str] = field(default_factory=list)

    @property
    def all_problems(self) -> list[str]:
        """Возвращает все проблемы, включая отброшенные характеристики.

        Returns:
            Список проблем для повторного запроса к модели.
        """
        dropped = [f"extracted_specs: {item}, quote должен быть дословным фрагментом описания" for item in self.dropped_specs]
        return self.problems + dropped


def build_source_text(product: ProductInput) -> str:
    """Собирает весь текст входных данных, по которому сверяются факты.

    Args:
        product: Товар.

    Returns:
        Текст из названия, категории, производителя, характеристик и описания.
    """
    parts = [product.name, product.category or "", product.manufacturer or ""]
    parts.extend(f"{key}: {value}" for key, value in product.filled_specs().items())
    parts.append(product.description or "")
    return "\n".join(part for part in parts if part)


def find_unknown_numbers(text: str, allowed: set[str]) -> list[str]:
    """Находит числа, которых нет во входных данных.

    Args:
        text: Проверяемый текст.
        allowed: Числа из входных данных.

    Returns:
        Отсортированный список «лишних» чисел.
    """
    return sorted(extract_numbers(text) - allowed)


def check_lengths(draft: LLMDraft) -> list[str]:
    """Проверяет длину заголовка, описания и количество запросов.

    Args:
        draft: Ответ модели.

    Returns:
        Список проблем.
    """
    problems = []
    title_length = len(draft.seo_title.strip())
    if title_length == 0:
        problems.append("seo_title пустой")
    elif title_length > TITLE_MAX_LENGTH:
        problems.append(
            f"seo_title - {title_length} символов, максимум {TITLE_MAX_LENGTH}: сократи на {title_length - TITLE_MAX_LENGTH}"
        )
    description_length = len(draft.seo_description.strip())
    target_middle = (DESCRIPTION_TARGET_MIN + DESCRIPTION_TARGET_MAX) // 2
    if description_length < DESCRIPTION_MIN_LENGTH:
        missing = target_middle - description_length
        problems.append(
            f"seo_description - {description_length} символов, допустимо {DESCRIPTION_MIN_LENGTH}–{DESCRIPTION_MAX_LENGTH}: "
            f"добавь примерно {missing} символов (около {missing // CHARS_PER_WORD} слов), используя только факты из данных"
        )
    elif description_length > DESCRIPTION_MAX_LENGTH:
        extra = description_length - target_middle
        problems.append(
            f"seo_description - {description_length} символов, допустимо {DESCRIPTION_MIN_LENGTH}–{DESCRIPTION_MAX_LENGTH}: "
            f"сократи примерно на {extra} символов (около {extra // CHARS_PER_WORD} слов)"
        )
    queries = [query.strip() for query in draft.search_queries if query.strip()]
    if not QUERIES_MIN <= len(queries) <= QUERIES_MAX:
        problems.append(f"search_queries - {len(queries)} шт., нужно от {QUERIES_MIN} до {QUERIES_MAX}")
    if len({normalize_text(query) for query in queries}) < len(queries):
        problems.append("search_queries содержит повторы")
    if not draft.manager_note.suitable_for or not draft.manager_note.solves:
        problems.append("manager_note: списки suitable_for и solves не должны быть пустыми")
    return problems


def check_numbers(draft: LLMDraft, allowed: set[str]) -> list[str]:
    """Ищет в текстах карточки числа, которых нет во входных данных.

    Args:
        draft: Ответ модели.
        allowed: Числа из входных данных.

    Returns:
        Список проблем.
    """
    texts = {
        "seo_title": draft.seo_title,
        "seo_description": draft.seo_description,
        "search_queries": " ".join(draft.search_queries),
        "manager_note": " ".join(draft.manager_note.suitable_for + draft.manager_note.solves),
    }
    problems = []
    for field_name, text in texts.items():
        unknown = find_unknown_numbers(text, allowed)
        if unknown:
            problems.append(f"{field_name}: числа {', '.join(unknown)} отсутствуют во входных данных - убери их")
    return problems


def find_evaluative_words(text: str, source_text: str) -> list[str]:
    """Находит оценочные слова, которых нет во входных данных.

    Args:
        text: Проверяемый текст.
        source_text: Текст входных данных.

    Returns:
        Отсортированный список найденных оценочных слов.
    """
    normalized_text = normalize_text(text)
    normalized_source = normalize_text(source_text)
    found = set()
    for pattern in EVALUATIVE_PATTERNS:
        if pattern.search(normalized_source):
            continue
        found.update(match.group(0) for match in pattern.finditer(normalized_text))
    return sorted(found)


def check_evaluative_words(draft: LLMDraft, source_text: str) -> list[str]:
    """Ищет в текстах карточки оценки товара, не подтверждённые данными.

    Args:
        draft: Ответ модели.
        source_text: Текст входных данных.

    Returns:
        Список проблем.
    """
    texts = {
        "seo_title": draft.seo_title,
        "seo_description": draft.seo_description,
        "manager_note": " ".join(draft.manager_note.suitable_for + draft.manager_note.solves),
    }
    problems = []
    for field_name, text in texts.items():
        words = find_evaluative_words(text, source_text)
        if words:
            problems.append(
                f"{field_name}: оценочные слова без подтверждения в данных ({', '.join(words)}) - "
                "убери их или замени фактами из данных"
            )
    return problems


def check_service_phrases(draft: LLMDraft) -> list[str]:
    """Ищет в текстах для покупателя служебные фразы о входных данных.

    Args:
        draft: Ответ модели.

    Returns:
        Список проблем.
    """
    texts = {
        "seo_title": draft.seo_title,
        "seo_description": draft.seo_description,
        "search_queries": " ".join(draft.search_queries),
    }
    problems = []
    for field_name, text in texts.items():
        normalized = normalize_text(text)
        found = sorted({match.group(0) for pattern in SERVICE_PATTERNS for match in pattern.finditer(normalized)})
        if found:
            problems.append(
                f"{field_name}: служебные фразы ({', '.join(found)}) - текст читает покупатель, "
                "не упоминай входные данные и отсутствие сведений, не отправляй к производителю"
            )
    return problems


def verify_extracted_specs(
    specs: list[ExtractedSpec], source_text: str
) -> tuple[list[ExtractedSpec], list[str]]:
    """Оставляет только характеристики, цитата которых действительно есть во входных данных.

    Args:
        specs: Характеристики, найденные моделью в описании.
        source_text: Текст входных данных.

    Returns:
        Подтверждённые характеристики и описания отброшенных.
    """
    normalized_source = normalize_text(source_text)
    verified, dropped = [], []
    for spec in specs:
        quote = normalize_text(spec.quote)
        if not quote or quote not in normalized_source:
            dropped.append(f"«{spec.name}: {spec.value}» - цитата не найдена во входных данных")
        elif not extract_numbers(spec.value) <= extract_numbers(spec.quote):
            dropped.append(f"«{spec.name}: {spec.value}» - значение не совпадает с цитатой")
        else:
            verified.append(spec)
    return verified, dropped


def check_draft(draft: LLMDraft, product: ProductInput) -> CheckReport:
    """Выполняет все проверки ответа модели.

    Args:
        draft: Ответ модели.
        product: Товар.

    Returns:
        Отчёт о проверке.
    """
    source_text = build_source_text(product)
    allowed_numbers = extract_numbers(source_text)
    verified, dropped = verify_extracted_specs(draft.extracted_specs, source_text)
    problems = check_lengths(draft) + check_numbers(draft, allowed_numbers)
    problems += check_evaluative_words(draft, source_text)
    problems += check_service_phrases(draft)
    return CheckReport(problems=problems, verified_specs=verified, dropped_specs=dropped)
