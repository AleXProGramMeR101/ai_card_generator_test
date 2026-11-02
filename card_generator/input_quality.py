"""Проверки качества входных данных: пустые значения, оборванный текст, незакрытые скобки."""

from card_generator.models import ProductInput

TRUNCATION_ENDINGS = ("...", "…")


def find_input_issues(product: ProductInput) -> list[str]:
    """Находит в данных о товаре то, что контент-менеджеру стоит уточнить.

    Args:
        product: Товар.

    Returns:
        Пункты для раздела «Требует уточнения».
    """
    issues = [f"Характеристика «{key}» передана без значения" for key in product.empty_spec_keys()]
    description = (product.description or "").rstrip()
    if description.endswith(TRUNCATION_ENDINGS):
        issues.append("Описание во входных данных оборвано («...»): текст неполный")
    texts = {"описании": description}
    texts.update({f"характеристике «{key}»": value for key, value in product.filled_specs().items()})
    for place, text in texts.items():
        if text.count("(") > text.count(")"):
            issues.append(f"В {place} незакрытая скобка - текст мог быть обрезан")
    return issues
