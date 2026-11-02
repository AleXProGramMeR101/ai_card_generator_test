"""Тесты проверок ответа модели."""

from card_generator.fact_check import check_draft, find_evaluative_words, find_unknown_numbers, verify_extracted_specs
from card_generator.models import ExtractedSpec, LLMDraft, ProductInput
from tests.conftest import make_draft


def test_valid_draft_has_no_problems(mp4u: ProductInput) -> None:
    """Корректный ответ проходит все проверки."""
    report = check_draft(LLMDraft.model_validate(make_draft()), mp4u)
    assert report.all_problems == []
    assert len(report.verified_specs) == 1


def test_invented_number_is_detected(mp4u: ProductInput) -> None:
    """Число, которого нет во входных данных, считается выдумкой."""
    draft = LLMDraft.model_validate(make_draft(seo_title="Манометр МП4-У 0–16 МПа"))
    problems = check_draft(draft, mp4u).problems
    assert any("seo_title" in problem and "16" in problem for problem in problems)


def test_number_formats_are_equivalent() -> None:
    """«1,5» во входе и «1.5» в тексте - одно и то же число."""
    assert find_unknown_numbers("класс 1.5, диаметр 160", {"1.5", "160"}) == []


def test_long_title_is_detected(mp4u: ProductInput) -> None:
    """Заголовок длиннее 70 символов - проблема с подсказкой, на сколько сократить."""
    draft = LLMDraft.model_validate(make_draft(seo_title="Манометр показывающий МП4-У " * 3))
    assert any("seo_title" in problem and "сократи" in problem for problem in check_draft(draft, mp4u).problems)


def test_short_description_is_detected(mp4u: ProductInput) -> None:
    """Слишком короткое описание - проблема с подсказкой, сколько добавить."""
    draft = LLMDraft.model_validate(make_draft(seo_description="Коротко."))
    assert any("seo_description" in problem and "добавь" in problem for problem in check_draft(draft, mp4u).problems)


def test_query_count_and_duplicates(mp4u: ProductInput) -> None:
    """Неверное число запросов и повторы - проблемы."""
    draft = LLMDraft.model_validate(make_draft(search_queries=["манометр МП4-У", "Манометр  МП4-У"]))
    problems = " ".join(check_draft(draft, mp4u).problems)
    assert "search_queries - 2 шт." in problems
    assert "повторы" in problems


def test_empty_manager_note(mp4u: ProductInput) -> None:
    """Пустой блок для менеджера - проблема."""
    draft = LLMDraft.model_validate(make_draft(manager_note={"suitable_for": [], "solves": ["x"]}))
    assert any("manager_note" in problem for problem in check_draft(draft, mp4u).problems)


def test_fake_quote_is_dropped() -> None:
    """Характеристика с выдуманной цитатой отбрасывается."""
    spec = ExtractedSpec(name="диапазон измерений", value="0–16 МПа", quote="диапазон 0–16 МПа")
    verified, dropped = verify_extracted_specs([spec], "Манометр МП4-У, корпус 160 мм")
    assert verified == []
    assert "цитата не найдена" in dropped[0]


def test_value_must_match_quote() -> None:
    """Значение с числом, которого нет в цитате, отбрасывается."""
    spec = ExtractedSpec(name="диаметр корпуса", value="100 мм", quote="Диаметр корпуса - 160 мм")
    verified, dropped = verify_extracted_specs([spec], "Диаметр корпуса - 160 мм.")
    assert verified == []
    assert "не совпадает" in dropped[0]


def test_quote_with_different_dashes_is_accepted() -> None:
    """Цитата с другим видом тире и пробелов считается совпадающей."""
    spec = ExtractedSpec(name="диаметр корпуса", value="160 мм", quote="Диаметр корпуса - 160  мм")
    verified, _ = verify_extracted_specs([spec], "Диаметр корпуса - 160 мм.")
    assert verified == [spec]


def test_evaluative_words_detected(mp4u: ProductInput) -> None:
    """Оценочные слова без опоры на данные считаются проблемой."""
    draft = LLMDraft.model_validate(make_draft(seo_description=make_draft()["seo_description"] + " Прочный корпус."))
    assert any("оценочные слова" in problem and "прочный" in problem for problem in check_draft(draft, mp4u).problems)


def test_evaluative_words_allowed_when_in_input() -> None:
    """Оценочное слово допустимо, если оно есть во входных данных."""
    assert find_evaluative_words("Надёжный прибор", "Надежный манометр для котельных") == []
    assert find_evaluative_words("Высокая точность", "Манометр") == ["высокая точность"]


def test_service_phrases_detected(mp4u: ProductInput) -> None:
    """Служебные фразы о входных данных в тексте для покупателя - проблема."""
    description = make_draft()["seo_description"] + " В описании не указан диапазон, свяжитесь с представителем производителя."
    problems = " ".join(check_draft(LLMDraft.model_validate(make_draft(seo_description=description)), mp4u).problems)
    assert "служебные фразы" in problems
    for phrase in ["в описании", "не указан", "свяжитесь", "представителем производителя"]:
        assert phrase in problems


def test_new_evaluative_patterns() -> None:
    """«Стабильная работа» и «обеспечивает точность» без опоры на данные - оценки."""
    assert find_evaluative_words("Обеспечивает стабильную работу и обеспечивает точность", "Гигрометр") == [
        "обеспечивает точность",
        "стабильную",
    ]
