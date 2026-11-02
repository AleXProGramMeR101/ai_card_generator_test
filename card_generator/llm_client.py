"""Клиент LLM через OpenAI-совместимый API: Groq, OpenAI, Ollama, vLLM, LM Studio и другие."""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import openai
from loguru import logger

from card_generator.config import Settings

CODE_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*|\s*```$")
JSON_VALIDATE_FAILED = "json_validate_failed"
PLACEHOLDER_KEY = "your_api_key_here"


class LLMError(Exception):
    """Ошибка обращения к LLM, после которой продолжать нельзя."""


@dataclass
class LLMResponse:
    """Ответ модели."""

    content: str
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


class ChatModel(Protocol):
    """Интерфейс модели, который нужен генератору карточек."""

    model: str

    def chat(self, messages: list[dict[str, str]]) -> LLMResponse:
        """Отправляет сообщения модели.

        Args:
            messages: История сообщений в формате OpenAI.

        Returns:
            Ответ модели.
        """


class LLMClient:
    """Клиент для любого провайдера с OpenAI-совместимым API."""

    def __init__(self, settings: Settings) -> None:
        """Создаёт клиент по настройкам.

        Args:
            settings: Настройки приложения.
        """
        self._settings = settings
        self.model = settings.llm_model
        self._client = openai.OpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or "not-needed",
            timeout=settings.llm_timeout,
            max_retries=settings.llm_max_retries,
        )

    def build_request(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        """Собирает параметры запроса, добавляя только поддерживаемые настройки.

        Args:
            messages: История сообщений.

        Returns:
            Параметры для chat.completions.create.
        """
        request: dict[str, Any] = {
            "model": self._settings.llm_model,
            "messages": messages,
            "temperature": self._settings.llm_temperature,
        }
        if self._settings.llm_max_tokens > 0:
            request["max_tokens"] = self._settings.llm_max_tokens
        if self._settings.llm_json_mode:
            request["response_format"] = {"type": "json_object"}
        if self._settings.llm_reasoning_effort:
            request["reasoning_effort"] = self._settings.llm_reasoning_effort
        return request

    def chat(self, messages: list[dict[str, str]]) -> LLMResponse:
        """Отправляет запрос модели и переводит ошибки провайдера в понятные сообщения.

        Args:
            messages: История сообщений.

        Returns:
            Ответ модели.
        """
        if not self._settings.llm_api_key.isascii() or self._settings.llm_api_key == PLACEHOLDER_KEY:
            raise LLMError("LLM_API_KEY не заполнен: впишите настоящий ключ в файл .env")
        request = self.build_request(messages)
        started = time.perf_counter()
        try:
            completion = self._client.chat.completions.create(**request)
        except openai.BadRequestError as error:
            if JSON_VALIDATE_FAILED in str(error):
                logger.warning("Провайдер отклонил невалидный JSON от модели, будет повторная попытка")
                return LLMResponse(content="", finish_reason=JSON_VALIDATE_FAILED)
            raise LLMError(self._describe_error(error)) from error
        except openai.OpenAIError as error:
            raise LLMError(self._describe_error(error)) from error
        elapsed = time.perf_counter() - started
        choice = completion.choices[0] if completion.choices else None
        content = (choice.message.content or "") if choice else ""
        usage = completion.usage.model_dump() if completion.usage else {}
        finish_reason = choice.finish_reason if choice else None
        logger.info(
            "Ответ модели за {:.1f} c, токены: {}, завершение: {}",
            elapsed,
            usage.get("total_tokens", "?"),
            finish_reason,
        )
        logger.debug("Сырой ответ модели: {}", content)
        return LLMResponse(content=content, finish_reason=finish_reason, usage=usage)

    def _describe_error(self, error: openai.OpenAIError) -> str:
        """Формирует понятное описание ошибки провайдера.

        Args:
            error: Исключение из OpenAI SDK.

        Returns:
            Сообщение для пользователя.
        """
        details = getattr(error, "message", None) or str(error)
        if isinstance(error, openai.AuthenticationError):
            return "Провайдер не принял ключ: проверьте LLM_API_KEY в файле .env"
        if isinstance(error, openai.PermissionDeniedError):
            return (
                f"Доступ запрещён провайдером (403): {details}. Ключ при этом может быть исправен: "
                "чаще всего провайдер блокирует запросы из вашего региона - используйте VPN, сервер за рубежом, "
                "другого провайдера или локальную модель"
            )
        if isinstance(error, openai.NotFoundError):
            return f"Не найдены модель или адрес API: проверьте LLM_MODEL={self.model} и LLM_BASE_URL={self._settings.llm_base_url}"
        if isinstance(error, openai.RateLimitError):
            return "Превышен лимит запросов или токенов у провайдера, попробуйте через минуту"
        if isinstance(error, openai.BadRequestError):
            return f"Провайдер отклонил запрос: {details}. Если модель не поддерживает параметр, отключите LLM_JSON_MODE или LLM_REASONING_EFFORT"
        if isinstance(error, openai.APITimeoutError):
            return f"Модель не ответила за {self._settings.llm_timeout:.0f} c: увеличьте LLM_TIMEOUT"
        if isinstance(error, openai.APIConnectionError):
            return f"Нет соединения с {self._settings.llm_base_url}: проверьте адрес и интернет"
        if isinstance(error, openai.APIStatusError):
            return f"Ошибка провайдера (код {error.status_code}): {details}"
        return f"Ошибка обращения к модели: {details}"


def parse_json_object(text: str) -> dict[str, Any]:
    """Достаёт JSON-объект из ответа модели, даже если он обёрнут в ```json или окружён текстом.

    Args:
        text: Текст ответа модели.

    Returns:
        Разобранный JSON-объект.
    """
    cleaned = CODE_FENCE_PATTERN.sub("", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("в ответе нет JSON-объекта") from None
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as error:
            raise ValueError(f"некорректный JSON: {error.msg}") from error
    if not isinstance(data, dict):
        raise ValueError("ответ должен быть JSON-объектом")
    return data
