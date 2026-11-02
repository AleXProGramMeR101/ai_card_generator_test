"""Тесты веб-интерфейса без обращения к модели."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from card_generator.config import Settings
from card_generator.pipeline import CardGenerator
from card_generator.rate_limiter import RateLimiter
from card_generator.schema_registry import CategorySchema
from card_generator.web_app import create_app
from tests.conftest import FakeLLM, make_draft, to_json


@pytest.fixture
def make_client(schemas: list[CategorySchema], tmp_path: Path):
    """Фабрика тестового клиента с подменённой моделью.

    Returns:
        Функция, создающая клиент по списку ответов модели и настройкам.
    """

    def factory(responses: list[str] | None = None, **overrides: object) -> TestClient:
        """Создаёт тестовый клиент.

        Args:
            responses: Ответы модели по порядку.
            **overrides: Переопределения настроек.

        Returns:
            Клиент для запросов к приложению.
        """
        settings = Settings(_env_file=None, llm_model="fake-model", log_dir=tmp_path / "logs", **overrides)
        generator = CardGenerator(FakeLLM(responses or []), schemas, tmp_path / "schemas", 1)
        return TestClient(create_app(settings, generator))

    return factory


def test_index_page(make_client) -> None:
    """Главная страница и статика отдаются."""
    client = make_client()
    page = client.get("/")
    assert page.status_code == 200
    assert "Перетащите JSON-файл сюда" in page.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_info(make_client) -> None:
    """Страница получает модель и ограничения."""
    assert make_client(web_max_upload_mb=7).get("/api/info").json() == {
        "model": "fake-model",
        "max_upload_mb": 7,
        "max_products": 10,
    }


def test_examples_list_and_load(make_client) -> None:
    """Все три примера перечислены и разбираются без ошибок."""
    client = make_client()
    examples = client.get("/api/examples").json()
    assert [item["id"] for item in examples] == ["from_tz", "bad", "good"]
    for item in examples:
        parsed = client.get(f"/api/examples/{item['id']}").json()
        assert parsed["source"] == item["file"]
        assert [product["error"] for product in parsed["products"]] == [None]
        assert client.get(f"/api/examples/{item['id']}/file").status_code == 200


def test_unknown_example(make_client) -> None:
    """Несуществующий пример - 404."""
    assert make_client().get("/api/examples/nope").status_code == 404


def test_upload_accepts_json(make_client) -> None:
    """Корректный JSON-файл разбирается, ошибки товаров показываются по отдельности."""
    content = json.dumps([{"name": "Манометр", "description": "Текст"}, {"name": ""}], ensure_ascii=False)
    response = make_client().post("/api/upload", files={"file": ("products.json", content.encode(), "application/json")})
    assert response.status_code == 200
    products = response.json()["products"]
    assert products[0]["error"] is None and products[0]["name"] == "Манометр"
    assert "name: поле не может быть пустым" in products[1]["error"]


@pytest.mark.parametrize("filename", ["products.txt", "products.json.exe", "products"])
def test_upload_rejects_other_formats(make_client, filename: str) -> None:
    """Файлы не .json отклоняются."""
    response = make_client().post("/api/upload", files={"file": (filename, b"{}", "text/plain")})
    assert response.status_code == 415
    assert response.json()["detail"] == "Принимаются только файлы .json"


def test_upload_rejects_large_file(make_client) -> None:
    """Файл больше предела отклоняется."""
    big = b"[" + b" " * (1024 * 1024 + 10) + b"]"
    response = make_client(web_max_upload_mb=1).post("/api/upload", files={"file": ("big.json", big, "application/json")})
    assert response.status_code == 413


def test_upload_broken_json(make_client) -> None:
    """Битый JSON - понятная ошибка с позицией."""
    response = make_client().post("/api/upload", files={"file": ("bad.json", b'{"name": "x"', "application/json")})
    assert response.status_code == 400
    assert "некорректный JSON" in response.json()["detail"]


def test_upload_too_many_products(make_client) -> None:
    """Слишком много товаров в одном файле - ошибка с пределом."""
    content = json.dumps([{"name": f"Товар {index}"} for index in range(3)]).encode()
    response = make_client(web_max_products=2).post("/api/upload", files={"file": ("many.json", content, "application/json")})
    assert response.status_code == 400
    assert "не больше 2" in response.json()["detail"]


def test_generate(make_client, mp4u_raw: dict) -> None:
    """Генерация возвращает карточку, список на уточнение и Markdown для скачивания."""
    response = make_client([to_json(make_draft())]).post("/api/generate", json=mp4u_raw)
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["card"]["seo_title"].startswith("Манометр показывающий МП4-У")
    assert body["filename"] == "mp4-u-manometr-pokazyvayuschiy"
    assert body["markdown"].startswith("# МП4-У")
    assert "csv" not in body
    assert "Нет данных: Диапазон измерений (важная характеристика)" in body["review"]


def test_generate_invalid_product(make_client) -> None:
    """Некорректный товар отклоняется до вызова модели."""
    response = make_client().post("/api/generate", json={"name": ""})
    assert response.status_code == 400


def test_generate_insufficient_data(make_client) -> None:
    """Товар без данных - понятная ошибка, модель не вызывается."""
    response = make_client().post("/api/generate", json={"name": "Манометр ДМ 02"})
    assert response.status_code == 400
    assert "Недостаточно данных" in response.json()["detail"]


def test_generate_model_failure(make_client, mp4u_raw: dict) -> None:
    """Если модель так и не вернула JSON, ответ - 502 с причиной."""
    response = make_client(["не json", "снова не json"]).post("/api/generate", json=mp4u_raw)
    assert response.status_code == 502
    assert "корректный JSON" in response.json()["detail"]


def test_generate_rate_limit(make_client, mp4u_raw: dict) -> None:
    """После исчерпания лимита запросов - 429."""
    client = make_client([to_json(make_draft())], web_rate_limit_per_minute=1)
    assert client.post("/api/generate", json=mp4u_raw).status_code == 200
    assert client.post("/api/generate", json=mp4u_raw).status_code == 429


def test_rate_limiter_window() -> None:
    """Скользящее окно освобождает место по прошествии времени."""
    now = [0.0]
    limiter = RateLimiter(2, window_seconds=60, clock=lambda: now[0])
    assert limiter.allow("a") and limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.allow("b")
    now[0] = 61
    assert limiter.allow("a")
    assert RateLimiter(0).allow("a")
