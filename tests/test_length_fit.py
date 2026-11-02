"""Тесты подгонки длины текстов кодом."""

from card_generator.length_fit import fit_description, fit_draft, fit_title
from card_generator.limits import DESCRIPTION_TARGET_MAX, DESCRIPTION_TARGET_MIN
from card_generator.models import LLMDraft
from card_generator.prompts import SYSTEM_PROMPT
from tests.conftest import make_draft

SENTENCE = "Прибор измеряет избыточное давление жидкостей и газов в трубопроводах."


def test_short_description_untouched() -> None:
    """Описание в пределах нормы не меняется."""
    assert fit_description("Короткий текст.", max_length=100, min_length=5) == "Короткий текст."


def test_long_description_cut_at_sentence() -> None:
    """Длинное описание обрезается по последнему целому предложению в пределе."""
    text = " ".join([SENTENCE] * 30)
    result = fit_description(text, max_length=1200, min_length=800)
    assert 800 <= len(result) <= 1200
    assert result.endswith(".")
    assert text.startswith(result)


def test_paragraphs_preserved() -> None:
    """Деление на абзацы сохраняется."""
    text = "\n\n".join(" ".join([SENTENCE] * 6) for _ in range(4))
    result = fit_description(text, max_length=1200, min_length=800)
    assert "\n\n" in result
    assert len(result) <= 1200


def test_no_cut_below_minimum() -> None:
    """Если после обрезки текст стал бы короче минимума, он не трогается."""
    text = "Очень длинное предложение " * 60 + "."
    assert fit_description(text, max_length=1200, min_length=800) == text.strip()


def test_title_cut_at_comma() -> None:
    """Длинный заголовок теряет последнюю часть после запятой."""
    title = "Манометр показывающий МП4-У, корпус 160 мм, класс точности 1,5, IP40"
    long_title = title + ", климатическое исполнение У2"
    assert fit_title(long_title, max_length=70) == title


def test_title_without_comma_untouched() -> None:
    """Заголовок без запятой не режется: его исправит модель."""
    title = "Манометр " * 10
    assert fit_title(title, max_length=70) == title.strip()


def test_fit_draft_reports_changes() -> None:
    """Подгонка ответа сообщает, что именно сокращено."""
    draft = LLMDraft.model_validate(make_draft(seo_description=" ".join([SENTENCE] * 30)))
    fitted, notes = fit_draft(draft)
    assert len(fitted.seo_description) <= 1200
    assert notes and notes[0].startswith("описание сокращено")


def test_prompt_uses_target_range() -> None:
    """Модели задаётся целевой диапазон длины описания."""
    assert f"от {DESCRIPTION_TARGET_MIN} до {DESCRIPTION_TARGET_MAX} символов" in SYSTEM_PROMPT
