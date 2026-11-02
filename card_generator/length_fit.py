"""Подгонка длины текстов кодом: лишние предложения отрезаются без нового запроса к модели."""

import re

from card_generator.limits import DESCRIPTION_MAX_LENGTH, DESCRIPTION_MIN_LENGTH, TITLE_MAX_LENGTH
from card_generator.models import LLMDraft

SENTENCE_END_PATTERN = re.compile(r"[.!?…](?=\s|$)")


def fit_description(text: str, max_length: int = DESCRIPTION_MAX_LENGTH, min_length: int = DESCRIPTION_MIN_LENGTH) -> str:
    """Укорачивает описание по границе предложения, если оно длиннее предела.

    Args:
        text: Описание.
        max_length: Максимальная длина.
        min_length: Минимальная длина, ниже которой резать нельзя.

    Returns:
        Описание целыми предложениями не длиннее max_length или исходный текст, если так не получается.
    """
    text = text.strip()
    if len(text) <= max_length:
        return text
    cut = 0
    for match in SENTENCE_END_PATTERN.finditer(text):
        if match.end() > max_length:
            break
        cut = match.end()
    if cut < min_length:
        return text
    return text[:cut].rstrip()


def fit_title(text: str, max_length: int = TITLE_MAX_LENGTH) -> str:
    """Укорачивает заголовок, отбрасывая последние части после запятой.

    Args:
        text: Заголовок.
        max_length: Максимальная длина.

    Returns:
        Заголовок не длиннее max_length или исходный текст, если подходящей запятой нет.
    """
    text = text.strip()
    if len(text) <= max_length:
        return text
    cut = text.rfind(",", 0, max_length + 1)
    candidate = text[:cut].rstrip(" ,–-") if cut > 0 else ""
    return candidate if len(candidate) >= max_length // 2 else text


def fit_draft(draft: LLMDraft) -> tuple[LLMDraft, list[str]]:
    """Подгоняет длину заголовка и описания в ответе модели.

    Args:
        draft: Ответ модели.

    Returns:
        Ответ с подогнанными текстами и описание сделанных изменений.
    """
    title = fit_title(draft.seo_title)
    description = fit_description(draft.seo_description)
    notes = []
    if title != draft.seo_title.strip():
        notes.append(f"заголовок сокращён с {len(draft.seo_title.strip())} до {len(title)} символов")
    if description != draft.seo_description.strip():
        notes.append(f"описание сокращено с {len(draft.seo_description.strip())} до {len(description)} символов")
    return draft.model_copy(update={"seo_title": title, "seo_description": description}), notes
