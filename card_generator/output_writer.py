"""Представление результата для контент-менеджера: JSON и Markdown."""

import json
from pathlib import Path

from card_generator.models import CardResult
from card_generator.text_utils import slugify

SOURCE_LABELS = {"specs": "характеристики", "description": "описание", "none": "-"}
STATUS_LABELS = {"ok": "готово к публикации после вычитки", "needs_review": "требует проверки"}


def review_items(result: CardResult) -> list[str]:
    """Собирает всё, что контент-менеджеру нужно проверить или уточнить.

    Args:
        result: Результат генерации.

    Returns:
        Пункты списка «Требует уточнения».
    """
    quality = result.quality
    items = [
        f"Нет данных: {item.name}" + (" (важная характеристика)" if item.critical else "")
        for item in quality.missing_fields
    ]
    items += quality.needs_clarification
    items += [f"Проверка не пройдена: {item}" for item in quality.warnings]
    items += [f"Отброшено: {item}" for item in quality.dropped_specs]
    return items


def render_markdown(result: CardResult) -> str:
    """Оформляет карточку в Markdown, удобный для копирования.

    Args:
        result: Результат генерации.

    Returns:
        Текст в формате Markdown.
    """
    card, quality = result.card, result.quality
    lines = [
        f"# {result.input.get('name', card.seo_title)}",
        "",
        f"> Черновик · статус: **{STATUS_LABELS[quality.status]}** · заполненность характеристик: "
        f"{quality.completeness:.0%} · модель: {quality.model} · попыток: {quality.attempts}",
        "",
        f"## SEO-заголовок ({card.seo_title_length} симв.)",
        "",
        card.seo_title,
        "",
        f"## SEO-описание ({card.seo_description_length} симв.)",
        "",
        card.seo_description,
        "",
        "## Ключевые характеристики",
        "",
        "| Характеристика | Значение | Источник |",
        "|---|---|---|",
    ]
    for row in card.key_specs:
        value = row.value.replace("|", "\\|")
        lines.append(f"| {row.name} | {value} | {SOURCE_LABELS[row.source]} |")
    lines += ["", "## Поисковые запросы", ""]
    lines += [f"- {query}" for query in card.search_queries]
    lines += ["", "## Для менеджера", "", "**Кому подходит:**", ""]
    lines += [f"- {item}" for item in card.manager_note.suitable_for]
    lines += ["", "**Какие задачи решает:**", ""]
    lines += [f"- {item}" for item in card.manager_note.solves]
    review = review_items(result)
    if review:
        lines += ["", "## Требует уточнения", ""]
        lines += [f"- {item}" for item in review]
    return "\n".join(lines) + "\n"


def file_stem(result: CardResult) -> str:
    """Возвращает имя файла результата без расширения.

    Args:
        result: Результат генерации.

    Returns:
        Имя латиницей, построенное из названия товара.
    """
    return slugify(str(result.input.get("name", "product")))


def save_result(result: CardResult, output_dir: Path) -> tuple[Path, Path]:
    """Сохраняет результат в два файла: JSON и Markdown.

    Args:
        result: Результат генерации.
        output_dir: Каталог для результатов.

    Returns:
        Пути к JSON- и Markdown-файлам.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = file_stem(result)
    json_path = output_dir / f"{stem}.json"
    markdown_path = output_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(result.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(result), encoding="utf-8")
    return json_path, markdown_path
