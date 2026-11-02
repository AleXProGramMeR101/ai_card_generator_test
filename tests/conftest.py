"""Общие фикстуры тестов: подменённая модель, примеры товаров и ответов."""

import json
from pathlib import Path
from typing import Any

import pytest

from card_generator.config import PROJECT_ROOT
from card_generator.llm_client import LLMResponse
from card_generator.models import ProductInput
from card_generator.pipeline import CardGenerator
from card_generator.schema_registry import CategorySchema, load_schemas

DESCRIPTION_TEXT = (
    "Показывающий манометр МП4-У применяют для контроля избыточного давления неагрессивных жидкостей, "
    "пара и газа, включая кислород и ацетилен при соответствующем исполнении. Прибор рассчитан на среды, "
    "которые не кристаллизуются и не агрессивны к медным сплавам.\n\n"
    "Корпус диаметром 160 мм выпускается из стали, алюминиевого сплава или ударопрочного полистирола. "
    "Штуцер бывает радиальным или осевым, фланец задний, передний или отсутствует, поэтому прибор легко "
    "подобрать под щит или трубопровод.\n\n"
    "Базовый класс точности 1,5, по заказу доступен более точный вариант. Степень защиты корпуса IP40, "
    "по заказу IP53 или IP54. Климатическое исполнение У2 и Т2 подходит для работы под навесом и в "
    "тропическом климате.\n\n"
    "К заказу доступны обезжиривание рабочей полости, атомное исполнение, демпфер, пломбировка и "
    "свидетельство о поверке. Конкретную шкалу и вариант исполнения согласуют при оформлении заказа."
)


class FakeLLM:
    """Подменённая модель: возвращает заранее заданные ответы и запоминает запросы."""

    def __init__(self, responses: list[str | LLMResponse], model: str = "fake-model") -> None:
        """Создаёт подменённую модель.

        Args:
            responses: Ответы по порядку вызовов.
            model: Название модели для отчёта.
        """
        self.model = model
        self._responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, messages: list[dict[str, str]]) -> LLMResponse:
        """Возвращает следующий заранее заданный ответ.

        Args:
            messages: История сообщений.

        Returns:
            Ответ модели.
        """
        self.calls.append(list(messages))
        response = self._responses.pop(0)
        return response if isinstance(response, LLMResponse) else LLMResponse(content=response, finish_reason="stop")


def make_draft(**overrides: Any) -> dict[str, Any]:
    """Собирает корректный ответ модели для МП4-У.

    Args:
        **overrides: Поля, которые нужно заменить.

    Returns:
        Ответ модели в виде словаря.
    """
    draft = {
        "category": "манометр показывающий",
        "suggested_fields": [],
        "extracted_specs": [
            {
                "name": "измеряемая среда",
                "value": "жидкости, пар и газ, в том числе кислород и ацетилен",
                "quote": "жидкостей, пара и газа, в том числе кислорода, ацетилена",
            }
        ],
        "seo_title": "Манометр показывающий МП4-У, корпус 160 мм, класс точности 1,5",
        "seo_description": DESCRIPTION_TEXT,
        "search_queries": [
            "манометр МП4-У",
            "манометр МП4-У купить",
            "манометр показывающий 160 мм класс точности 1,5",
        ],
        "manager_note": {
            "suitable_for": ["Объекты атомной энергетики (атомное исполнение)", "Кислородные и ацетиленовые линии"],
            "solves": ["Контроль избыточного давления жидкостей, пара и газа", "Допродажа: поверка, демпфер"],
        },
        "clarifications": [],
    }
    draft.update(overrides)
    return draft


def to_json(data: dict[str, Any]) -> str:
    """Сериализует ответ модели в JSON.

    Args:
        data: Ответ в виде словаря.

    Returns:
        JSON-строка.
    """
    return json.dumps(data, ensure_ascii=False)


@pytest.fixture
def mp4u_raw() -> dict[str, Any]:
    """Данные МП4-У из примеров.

    Returns:
        Товар в виде словаря.
    """
    return json.loads((PROJECT_ROOT / "examples" / "input" / "mp4-u.json").read_text(encoding="utf-8"))


@pytest.fixture
def mp4u(mp4u_raw: dict[str, Any]) -> ProductInput:
    """Проверенный товар МП4-У.

    Returns:
        Товар.
    """
    return ProductInput.model_validate(mp4u_raw)


@pytest.fixture
def schemas() -> list[CategorySchema]:
    """Схемы категорий из каталога проекта.

    Returns:
        Список схем.
    """
    return load_schemas(PROJECT_ROOT / "schemas")


@pytest.fixture
def schemas_dir(tmp_path: Path) -> Path:
    """Временный каталог для сохранения предложенных схем.

    Returns:
        Путь к каталогу.
    """
    return tmp_path / "schemas"


@pytest.fixture
def make_generator(schemas: list[CategorySchema], schemas_dir: Path):
    """Фабрика генератора с подменённой моделью.

    Returns:
        Функция, создающая генератор и подменённую модель по списку ответов.
    """

    def factory(responses: list[str | LLMResponse], repair_attempts: int = 1) -> tuple[CardGenerator, FakeLLM]:
        """Создаёт генератор с подменённой моделью.

        Args:
            responses: Ответы модели по порядку.
            repair_attempts: Число попыток исправления.

        Returns:
            Генератор и подменённая модель.
        """
        llm = FakeLLM(responses)
        return CardGenerator(llm, schemas, schemas_dir, repair_attempts), llm

    return factory
