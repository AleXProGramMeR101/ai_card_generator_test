"""Тесты полного цикла генерации карточки с подменённой моделью."""

from pathlib import Path

import pytest

from card_generator.card_builder import value_with_unit
from card_generator.llm_client import JSON_VALIDATE_FAILED, LLMError, LLMResponse
from card_generator.models import NO_DATA, ProductInput
from tests.conftest import make_draft, to_json


def test_happy_path(make_generator, mp4u: ProductInput) -> None:
    """Корректный ответ с первой попытки даёт карточку и честный отчёт."""
    generator, llm = make_generator([to_json(make_draft())])
    result = generator.generate(mp4u)
    specs = {row.name: row for row in result.card.key_specs}
    assert len(llm.calls) == 1
    assert result.quality.attempts == 1
    assert result.quality.schema_source == "config"
    assert specs["Диапазон измерений"].value == NO_DATA
    assert specs["Диаметр корпуса"].value == "160 мм"
    assert specs["Резьба присоединения"].source == "specs"
    assert specs["Измеряемая среда"].source == "description"
    assert specs["Масса прибора"].source == "specs"
    assert [item.name for item in result.quality.missing_fields if item.critical] == ["Диапазон измерений"]
    assert result.quality.status == "needs_review"
    assert result.input["name"] == mp4u.name


def test_prompt_lists_present_and_absent_fields(make_generator, mp4u: ProductInput) -> None:
    """В запрос к модели попадают найденные и недостающие характеристики схемы."""
    generator, llm = make_generator([to_json(make_draft())])
    generator.generate(mp4u)
    user_prompt = llm.calls[0][1]["content"]
    assert "Категория: манометр" in user_prompt
    assert "поищи их значения в описании): диапазон измерений, измеряемая среда" in user_prompt


def test_complete_product_is_ok(make_generator) -> None:
    """Товар со всеми важными характеристиками и без замечаний получает статус ok."""
    product = ProductInput(
        name="Манометр показывающий МП4-У",
        specs={
            "диапазон измерений": "0–1,6 МПа",
            "класс точности": "1,5",
            "резьба": "M20x1,5",
            "диаметр корпуса": "160 мм",
            "IP": "IP40; IP53; IP54",
            "климатическое исполнение": "У2",
        },
        description="Для жидкостей, пара и газа, в том числе кислорода, ацетилена.",
    )
    generator, _ = make_generator([to_json(make_draft())])
    result = generator.generate(product)
    assert result.quality.status == "ok"
    assert result.quality.missing_fields
    assert not any(item.critical for item in result.quality.missing_fields)


def test_repair_after_invented_number(make_generator, mp4u: ProductInput) -> None:
    """Если модель выдумала число, она получает список ошибок и исправляется."""
    bad = to_json(make_draft(seo_title="Манометр МП4-У 0–16 МПа"))
    generator, llm = make_generator([bad, to_json(make_draft())])
    result = generator.generate(mp4u)
    assert result.quality.attempts == 2
    assert result.quality.warnings == []
    repair_messages = llm.calls[1]
    assert repair_messages[2] == {"role": "assistant", "content": bad}
    assert "числа 0, 16 отсутствуют" in repair_messages[3]["content"]


def test_unfixed_problems_are_reported(make_generator, mp4u: ProductInput) -> None:
    """Если модель не исправилась, карточка отдаётся с предупреждениями, а не прячется."""
    bad = to_json(make_draft(seo_title="Манометр МП4-У 0–16 МПа"))
    generator, _ = make_generator([bad, bad])
    result = generator.generate(mp4u)
    assert result.quality.attempts == 2
    assert result.quality.status == "needs_review"
    assert any("16" in warning for warning in result.quality.warnings)


def test_invalid_json_then_valid(make_generator, mp4u: ProductInput) -> None:
    """Невалидный JSON исправляется повторным запросом."""
    generator, llm = make_generator(["Вот карточка: {битый json", to_json(make_draft())])
    result = generator.generate(mp4u)
    assert result.quality.attempts == 2
    assert "корректным JSON" in llm.calls[1][-1]["content"]


def test_json_in_code_fence_is_accepted(make_generator, mp4u: ProductInput) -> None:
    """Ответ, обёрнутый в ```json, разбирается без повторного запроса."""
    generator, _ = make_generator([f"```json\n{to_json(make_draft())}\n```"])
    assert generator.generate(mp4u).quality.attempts == 1


def test_missing_required_keys_trigger_repair(make_generator, mp4u: ProductInput) -> None:
    """Ответ без обязательных полей отправляется на исправление с их перечнем."""
    draft = make_draft()
    del draft["seo_title"]
    generator, llm = make_generator([to_json(draft), to_json(make_draft())])
    generator.generate(mp4u)
    assert "seo_title" in llm.calls[1][-1]["content"]


def test_provider_json_failure_is_retried(make_generator, mp4u: ProductInput) -> None:
    """Отказ провайдера из-за невалидного JSON приводит к повторному запросу."""
    failed = LLMResponse(content="", finish_reason=JSON_VALIDATE_FAILED)
    generator, llm = make_generator([failed, to_json(make_draft())])
    assert generator.generate(mp4u).quality.attempts == 2
    assert all(message["role"] != "assistant" for message in llm.calls[1])


def test_no_valid_json_at_all(make_generator, mp4u: ProductInput) -> None:
    """Если модель ни разу не вернула JSON, генерация завершается понятной ошибкой."""
    truncated = LLMResponse(content='{"seo_title": "Манометр', finish_reason="length")
    generator, _ = make_generator([truncated, truncated])
    with pytest.raises(LLMError, match="LLM_MAX_TOKENS"):
        generator.generate(mp4u)


def test_insufficient_data_skips_llm(make_generator) -> None:
    """Товар без характеристик и описания не отправляется в модель."""
    product = ProductInput(name="Манометр показывающий ДМ 02-100", specs={"класс точности": None})
    generator, llm = make_generator([])
    with pytest.raises(Exception, match="Недостаточно данных") as error:
        generator.generate(product)
    assert llm.calls == []
    assert "диапазон измерений" in error.value.missing


def test_unknown_category_uses_suggested_schema(make_generator, schemas_dir: Path) -> None:
    """Для товара без схемы таблица строится из имеющихся и предложенных характеристик, карточка идёт на проверку."""
    product = ProductInput(
        name="ВИТ-2 - гигрометр психрометрический",
        specs={"Диапазон измерения влажности, %": "20...90", "Цена деления шкалы, °С": "0,2"},
        description="Прибор для контроля температуры и влажности воздуха.",
    )
    draft = make_draft(
        category="гигрометр психрометрический",
        suggested_fields=["Рабочий диапазон влажности", "диапазон измерения температуры"],
        extracted_specs=[],
        seo_title="Гигрометр психрометрический ВИТ-2",
        search_queries=["гигрометр ВИТ-2", "гигрометр ВИТ-2 купить", "психрометрический гигрометр ВИТ-2"],
        seo_description="Текст описания без чисел. " * 40,
        manager_note={"suitable_for": ["Склады"], "solves": ["Контроль влажности"]},
    )
    generator, llm = make_generator([to_json(draft)])
    result = generator.generate(product)
    rows = [(row.name, row.value) for row in result.card.key_specs]
    assert "заполни suggested_fields" in llm.calls[0][1]["content"]
    assert result.quality.schema_source == "llm_suggested"
    assert result.quality.category == "гигрометр психрометрический"
    assert rows == [
        ("Диапазон измерения влажности", "20...90 %"),
        ("Цена деления шкалы", "0,2 °С"),
        ("Диапазон измерения температуры", NO_DATA),
    ]
    assert result.quality.completeness == 0.67
    assert result.quality.status == "needs_review"
    assert any("предложен моделью" in item for item in result.quality.needs_clarification)
    assert (schemas_dir / "suggested" / "gigrometr-psihrometricheskiy.yaml").exists()


def test_critical_value_from_description_needs_review(make_generator) -> None:
    """Важная характеристика, взятая из описания, отправляет карточку на проверку с цитатой."""
    product = ProductInput(
        name="Манометр МП4-У",
        specs={"класс точности": "1,5", "резьба": "M20x1,5", "диаметр корпуса": "160 мм"},
        description="С демпфером поставляется прибор с диапазоном показаний со 100 кгс/см², IP40, IP53, IP54, У2, Т2.",
    )
    extracted = [{"name": "диапазон измерений", "value": "со 100 кгс/см²", "quote": "с диапазоном показаний со 100 кгс/см²"}]
    generator, _ = make_generator([to_json(make_draft(extracted_specs=extracted))])
    result = generator.generate(product)
    assert {row.name: row.source for row in result.card.key_specs}["Диапазон измерений"] == "description"
    assert result.quality.status == "needs_review"
    assert any("Диапазон измерений: со 100 кгс/см²" in item for item in result.quality.needs_clarification)


def test_evaluative_words_trigger_repair(make_generator, mp4u: ProductInput) -> None:
    """Оценки вроде «надёжный» без опоры на данные отправляются на исправление."""
    bad_description = "Надёжный и компактный прибор. " + make_draft()["seo_description"]
    generator, llm = make_generator([to_json(make_draft(seo_description=bad_description)), to_json(make_draft())])
    result = generator.generate(mp4u)
    assert result.quality.attempts == 2
    assert "компактный, надежный" in llm.calls[1][-1]["content"]


def test_input_issues_are_reported(make_generator, mp4u: ProductInput) -> None:
    """Незакрытая скобка в описании МП4-У попадает в список на уточнение."""
    generator, _ = make_generator([to_json(make_draft())])
    result = generator.generate(mp4u)
    assert "В описании незакрытая скобка - текст мог быть обрезан" in result.quality.needs_clarification


def test_empty_spec_values_are_reported(make_generator) -> None:
    """Характеристики с пустыми значениями попадают в список на уточнение."""
    product = ProductInput(
        name="Манометр МП4-У",
        specs={"класс точности": "1,5", "Масса": ""},
        description="Корпус 160 мм, IP40, IP53, IP54, У2, Т2.",
    )
    generator, _ = make_generator([to_json(make_draft(extracted_specs=[]))])
    result = generator.generate(product)
    assert "Характеристика «Масса» передана без значения" in result.quality.needs_clarification
    assert {row.name: row.value for row in result.card.key_specs}["Масса"] == NO_DATA


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("Диаметр корпуса (мм)", "160", "160 мм"),
        ("Диапазон измерения влажности, %", "20...90; 40...90", "20...90; 40...90 %"),
        ("Диаметр корпуса", "160", "160"),
        ("Диаметр корпуса (мм)", "160 мм", "160 мм"),
    ],
)
def test_unit_moves_from_key_to_value(key: str, value: str, expected: str) -> None:
    """Единица из названия характеристики переносится в числовое значение."""
    assert value_with_unit(key, value) == expected


def test_long_description_trimmed_without_retry(make_generator, mp4u: ProductInput) -> None:
    """Слишком длинное описание обрезается кодом, повторный запрос к модели не нужен."""
    long_description = make_draft()["seo_description"] + "\n\n" + make_draft()["seo_description"]
    generator, llm = make_generator([to_json(make_draft(seo_description=long_description))])
    result = generator.generate(mp4u)
    assert len(llm.calls) == 1
    assert 800 <= result.card.seo_description_length <= 1200
    assert result.quality.warnings == []


def test_critical_value_from_description_used_in_texts(make_generator) -> None:
    """Если значение важной характеристики из описания попало в тексты, указано, куда именно."""
    product = ProductInput(
        name="Манометр МП4-У",
        specs={"класс точности": "1,5", "резьба": "M20x1,5", "диаметр корпуса": "160 мм"},
        description="С демпфером поставляется прибор с диапазоном показаний со 100 кгс/см², IP40, IP53, IP54, У2, Т2.",
    )
    extracted = [{"name": "диапазон измерений", "value": "со 100 кгс/см²", "quote": "с диапазоном показаний со 100 кгс/см²"}]
    queries = ["манометр МП4-У", "манометр МП4-У купить", "манометр МП4-У диапазон 100 кгс/см²"]
    generator, _ = make_generator([to_json(make_draft(extracted_specs=extracted, search_queries=queries))])
    notes = generator.generate(product).quality.needs_clarification
    usage = [note for note in notes if note.startswith("Значение «со 100 кгс/см²»")]
    assert usage == [
        "Значение «со 100 кгс/см²» характеристики «Диапазон измерений» использовано в текстах карточки "
        "(поисковые запросы) - если оно неверно, исправьте и их"
    ]


def test_value_usage_ignores_other_units(make_generator) -> None:
    """Совпадение числа с другой единицей (160 мм и 160 кгс/см²) не считается использованием."""
    product = ProductInput(
        name="Манометр МП4-У",
        specs={"класс точности": "1,5", "резьба": "M20x1,5", "диаметр корпуса": "160 мм"},
        description="С демпфером поставляются приборы с диапазоном показаний со 160 кгс/см², IP40, IP53, IP54, У2, Т2.",
    )
    extracted = [{"name": "диапазон измерений", "value": "со 160 кгс/см²", "quote": "с диапазоном показаний со 160 кгс/см²"}]
    generator, _ = make_generator([to_json(make_draft(extracted_specs=extracted))])
    notes = generator.generate(product).quality.needs_clarification
    assert not any(note.startswith("Значение «") for note in notes)
