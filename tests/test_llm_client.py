"""Тесты клиента LLM без обращения к сети."""

from types import SimpleNamespace

import openai
import pytest

from card_generator.config import Settings
from card_generator.llm_client import JSON_VALIDATE_FAILED, LLMClient, LLMError, parse_json_object


def make_error(error_class: type[Exception], message: str = "ошибка") -> Exception:
    """Создаёт исключение OpenAI SDK без HTTP-запроса.

    Args:
        error_class: Класс исключения.
        message: Текст ошибки.

    Returns:
        Экземпляр исключения.
    """
    error = error_class.__new__(error_class)
    Exception.__init__(error, message)
    error.message = message
    error.status_code = 500
    return error


def make_client(monkeypatch: pytest.MonkeyPatch, outcome: object, **overrides: object) -> LLMClient:
    """Создаёт клиент, у которого запрос к API подменён.

    Args:
        monkeypatch: Фикстура pytest для подмены.
        outcome: Ответ API или исключение.
        **overrides: Переопределения настроек.

    Returns:
        Клиент LLM.
    """
    client = LLMClient(Settings(_env_file=None, llm_api_key="test", **overrides))

    def fake_create(**kwargs: object) -> object:
        """Возвращает заданный ответ или выбрасывает исключение.

        Args:
            **kwargs: Параметры запроса.

        Returns:
            Ответ API.
        """
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(client._client.chat.completions, "create", fake_create)
    return client


def test_request_contains_only_enabled_options() -> None:
    """Необязательные параметры добавляются только когда включены."""
    client = LLMClient(Settings(_env_file=None, llm_reasoning_effort="", llm_json_mode=False, llm_max_tokens=0))
    request = client.build_request([{"role": "user", "content": "привет"}])
    assert set(request) == {"model", "messages", "temperature"}


def test_request_with_all_options() -> None:
    """При включённых настройках в запрос попадают JSON-режим, лимит токенов и reasoning_effort."""
    client = LLMClient(Settings(_env_file=None, llm_reasoning_effort="low", llm_json_mode=True, llm_max_tokens=500))
    request = client.build_request([])
    assert request["response_format"] == {"type": "json_object"}
    assert request["reasoning_effort"] == "low"
    assert request["max_tokens"] == 500


def test_successful_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """Текст, причина завершения и токены берутся из ответа API."""
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"a": 1}'), finish_reason="stop")],
        usage=SimpleNamespace(model_dump=lambda: {"total_tokens": 42}),
    )
    response = make_client(monkeypatch, completion).chat([])
    assert response.content == '{"a": 1}'
    assert response.finish_reason == "stop"
    assert response.usage == {"total_tokens": 42}


@pytest.mark.parametrize(
    ("error_class", "expected"),
    [
        (openai.AuthenticationError, "LLM_API_KEY"),
        (openai.NotFoundError, "LLM_MODEL"),
        (openai.RateLimitError, "лимит"),
        (openai.APITimeoutError, "LLM_TIMEOUT"),
        (openai.APIConnectionError, "Нет соединения"),
        (openai.BadRequestError, "LLM_JSON_MODE"),
    ],
)
def test_errors_are_explained(monkeypatch: pytest.MonkeyPatch, error_class: type[Exception], expected: str) -> None:
    """Ошибки провайдера превращаются в понятные подсказки."""
    client = make_client(monkeypatch, make_error(error_class))
    with pytest.raises(LLMError, match=expected):
        client.chat([])


def test_provider_json_failure_is_not_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ провайдера из-за невалидного JSON возвращается как пустой ответ для повтора."""
    client = make_client(monkeypatch, make_error(openai.BadRequestError, f"code: {JSON_VALIDATE_FAILED}"))
    response = client.chat([])
    assert response.content == ""
    assert response.finish_reason == JSON_VALIDATE_FAILED


@pytest.mark.parametrize(
    "text",
    ['{"a": 1}', '```json\n{"a": 1}\n```', 'Вот ответ:\n{"a": 1}\nГотово.'],
)
def test_parse_json_object(text: str) -> None:
    """JSON достаётся из ответа в разных обёртках."""
    assert parse_json_object(text) == {"a": 1}


@pytest.mark.parametrize("text", ["", "без json", "[1, 2]", "{битый"])
def test_parse_json_object_errors(text: str) -> None:
    """Ответ без корректного JSON-объекта даёт ValueError."""
    with pytest.raises(ValueError):
        parse_json_object(text)


@pytest.mark.parametrize("key", ["your_api_key_here", "ключ"])
def test_placeholder_key_is_rejected(key: str) -> None:
    """Незаполненный или некорректный ключ даёт понятную ошибку до запроса."""
    client = LLMClient(Settings(_env_file=None, llm_api_key=key))
    with pytest.raises(LLMError, match="LLM_API_KEY не заполнен"):
        client.chat([])
