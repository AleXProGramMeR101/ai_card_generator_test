"""Тесты сохранения результатов."""

import json
from pathlib import Path

from card_generator.models import ProductInput
from card_generator.output_writer import render_markdown, save_result
from tests.conftest import make_draft, to_json


def test_markdown_has_all_sections(make_generator, mp4u: ProductInput) -> None:
    """В Markdown есть все блоки карточки и раздел для уточнений."""
    generator, _ = make_generator([to_json(make_draft())])
    markdown = render_markdown(generator.generate(mp4u))
    for heading in ["## SEO-заголовок", "## SEO-описание", "## Ключевые характеристики", "## Поисковые запросы",
                    "## Для менеджера", "## Требует уточнения"]:
        assert heading in markdown
    assert "| Диапазон измерений | данных нет | - |" in markdown
    assert "Нет данных: Диапазон измерений (важная характеристика)" in markdown


def test_files_are_saved(make_generator, mp4u: ProductInput, tmp_path: Path) -> None:
    """Результат сохраняется в JSON и Markdown с именем из названия товара."""
    generator, _ = make_generator([to_json(make_draft())])
    json_path, markdown_path = save_result(generator.generate(mp4u), tmp_path / "out")
    assert json_path.name == "mp4-u-manometr-pokazyvayuschiy.json"
    assert markdown_path.suffix == ".md"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert set(data) == {"input", "card", "quality"}
    assert data["card"]["seo_title_length"] == len(data["card"]["seo_title"])

