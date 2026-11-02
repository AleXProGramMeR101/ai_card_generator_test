"""Тесты проверок качества входных данных."""

from card_generator.input_quality import find_input_issues
from card_generator.models import ProductInput


def test_clean_product_has_no_issues() -> None:
    """У аккуратных данных замечаний нет."""
    product = ProductInput(name="Манометр", specs={"класс точности": "1,5 (по заказу 1,0)"}, description="Текст.")
    assert find_input_issues(product) == []


def test_truncated_description() -> None:
    """Описание, оборванное многоточием, отмечается."""
    product = ProductInput(name="Манометр", description="Прибор предназначен для измерения давления...")
    assert find_input_issues(product) == ["Описание во входных данных оборвано («...»): текст неполный"]


def test_unclosed_parenthesis_in_spec() -> None:
    """Незакрытая скобка в характеристике отмечается с её названием."""
    product = ProductInput(name="Манометр", specs={"Класс точности": "1,5 (по заказу 1,0"})
    assert find_input_issues(product) == ["В характеристике «Класс точности» незакрытая скобка - текст мог быть обрезан"]


def test_empty_spec_value() -> None:
    """Характеристика без значения отмечается."""
    product = ProductInput(name="Манометр", specs={"Масса": "", "класс точности": "1,5"})
    assert find_input_issues(product) == ["Характеристика «Масса» передана без значения"]
