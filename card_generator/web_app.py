"""Веб-интерфейс: страница, загрузка JSON, примеры и генерация карточек через HTTP API."""

import json
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel

from card_generator.config import PROJECT_ROOT, Settings
from card_generator.input_loader import InputError, decode_bytes, parse_products, validate_product
from card_generator.llm_client import LLMClient, LLMError
from card_generator.models import CardResult
from card_generator.output_writer import file_stem, render_markdown, review_items
from card_generator.pipeline import CardGenerator, InsufficientDataError
from card_generator.rate_limiter import RateLimiter
from card_generator.schema_registry import load_schemas

WEB_DIR = Path(__file__).resolve().parent / "web"
EXAMPLES_DIR = PROJECT_ROOT / "examples" / "input"
UPLOAD_CHUNK_SIZE = 1024 * 1024


class ExampleInfo(BaseModel):
    """Пример входного файла для кнопки на странице."""

    id: str
    title: str
    note: str
    file: str


class ParsedProduct(BaseModel):
    """Товар из загруженного файла после проверки."""

    index: int
    name: str | None
    data: dict[str, Any] | None
    error: str | None


class ParseResponse(BaseModel):
    """Результат разбора загруженного файла."""

    source: str
    products: list[ParsedProduct]


class GenerateResponse(BaseModel):
    """Карточка товара и её представления для скачивания."""

    result: CardResult
    review: list[str]
    markdown: str
    filename: str


class ServiceInfo(BaseModel):
    """Параметры сервиса для страницы."""

    model: str
    max_upload_mb: int
    max_products: int


EXAMPLES = [
    ExampleInfo(id="from_tz", title="Пример из ТЗ", note="DM 02: минимум данных", file="dm-02.json"),
    ExampleInfo(id="bad", title="МП4-У с сайта", note="данных уже больше", file="mp4-u.json"),
    ExampleInfo(id="good", title="МП3-У, полные данные", note="данные с сайта, с дополнением", file="mp3-u.json"),
]


def find_example(example_id: str) -> ExampleInfo:
    """Ищет пример по идентификатору.

    Args:
        example_id: Идентификатор примера.

    Returns:
        Описание примера.
    """
    example = next((item for item in EXAMPLES if item.id == example_id), None)
    if example is None:
        raise HTTPException(status_code=404, detail="Такого примера нет")
    return example


def build_parse_response(text: str, source: str, settings: Settings) -> ParseResponse:
    """Разбирает JSON и проверяет каждый товар.

    Args:
        text: Содержимое файла.
        source: Имя файла для сообщений.
        settings: Настройки приложения.

    Returns:
        Список товаров с данными или текстом ошибки.
    """
    try:
        raw_products = parse_products(text, source)
    except InputError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if len(raw_products) > settings.web_max_products:
        raise HTTPException(
            status_code=400,
            detail=f"В файле {len(raw_products)} товаров, за один раз обрабатывается не больше {settings.web_max_products}",
        )
    products = []
    for index, raw in enumerate(raw_products, start=1):
        raw_name = raw.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else None
        try:
            validate_product(raw, settings.max_product_chars)
        except InputError as error:
            products.append(ParsedProduct(index=index, name=name, data=None, error=str(error)))
        else:
            products.append(ParsedProduct(index=index, name=name, data=raw, error=None))
    return ParseResponse(source=source, products=products)


async def read_upload(file: UploadFile, max_bytes: int) -> bytes:
    """Читает загруженный файл, проверяя расширение и размер.

    Args:
        file: Загруженный файл.
        max_bytes: Предельный размер в байтах.

    Returns:
        Содержимое файла.
    """
    if not (file.filename or "").lower().endswith(".json"):
        raise HTTPException(status_code=415, detail="Принимаются только файлы .json")
    chunks, total = [], 0
    while chunk := await file.read(UPLOAD_CHUNK_SIZE):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail=f"Файл больше {max_bytes // (1024 * 1024)} МБ")
        chunks.append(chunk)
    return b"".join(chunks)


def client_address(request: Request) -> str:
    """Возвращает адрес клиента для журнала и ограничения частоты.

    Args:
        request: HTTP-запрос.

    Returns:
        IP-адрес или «unknown».
    """
    return request.client.host if request.client else "unknown"


def create_app(settings: Settings, generator: CardGenerator | None = None) -> FastAPI:
    """Создаёт веб-приложение.

    Args:
        settings: Настройки приложения.
        generator: Готовый генератор карточек; None - создать по настройкам.

    Returns:
        Приложение FastAPI.
    """
    if generator is None:
        generator = CardGenerator(
            llm=LLMClient(settings),
            schemas=load_schemas(settings.schemas_dir),
            schemas_dir=settings.schemas_dir,
            repair_attempts=settings.repair_attempts,
        )
    limiter = RateLimiter(settings.web_rate_limit_per_minute)
    max_bytes = settings.web_max_upload_mb * 1024 * 1024
    app = FastAPI(title="Генератор карточек товаров КИП", version="1.0")
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        """Отдаёт страницу интерфейса.

        Returns:
            HTML-страница.
        """
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/api/info")
    def info() -> ServiceInfo:
        """Сообщает странице модель и ограничения сервиса.

        Returns:
            Параметры сервиса.
        """
        return ServiceInfo(
            model=settings.llm_model,
            max_upload_mb=settings.web_max_upload_mb,
            max_products=settings.web_max_products,
        )

    @app.get("/api/examples")
    def examples() -> list[ExampleInfo]:
        """Возвращает список примеров.

        Returns:
            Примеры входных файлов.
        """
        return EXAMPLES

    @app.get("/api/examples/{example_id}")
    def example(example_id: str) -> ParseResponse:
        """Разбирает пример так же, как загруженный файл.

        Args:
            example_id: Идентификатор примера.

        Returns:
            Результат разбора.
        """
        info_item = find_example(example_id)
        text = decode_bytes((EXAMPLES_DIR / info_item.file).read_bytes())
        return build_parse_response(text, info_item.file, settings)

    @app.get("/api/examples/{example_id}/file")
    def example_file(example_id: str) -> FileResponse:
        """Отдаёт исходный JSON примера для просмотра и скачивания.

        Args:
            example_id: Идентификатор примера.

        Returns:
            JSON-файл примера.
        """
        info_item = find_example(example_id)
        return FileResponse(EXAMPLES_DIR / info_item.file, media_type="application/json", filename=info_item.file)

    @app.post("/api/upload")
    async def upload(request: Request, file: UploadFile = File(...)) -> ParseResponse:
        """Принимает JSON-файл и проверяет товары в нём.

        Args:
            request: HTTP-запрос.
            file: Загруженный файл.

        Returns:
            Результат разбора.
        """
        data = await read_upload(file, max_bytes)
        logger.info("Загружен файл «{}» ({:.1f} КБ) с адреса {}", file.filename, len(data) / 1024, client_address(request))
        response = build_parse_response(decode_bytes(data), file.filename or "file.json", settings)
        logger.info("Файл «{}»: товаров - {}", file.filename, len(response.products))
        return response

    @app.post("/api/generate")
    def generate(request: Request, product: dict[str, Any] = Body(...)) -> GenerateResponse:
        """Генерирует карточку для одного товара.

        Args:
            request: HTTP-запрос.
            product: Данные товара в формате входного JSON.

        Returns:
            Карточка и Markdown для скачивания.
        """
        address = client_address(request)
        if not limiter.allow(address):
            raise HTTPException(status_code=429, detail="Слишком много запросов, подождите минуту")
        try:
            validated = validate_product(product, settings.max_product_chars)
        except InputError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        logger.info("Генерация карточки «{}» по запросу с адреса {}", validated.name, address)
        logger.debug("Входные данные: {}", json.dumps(product, ensure_ascii=False))
        try:
            result = generator.generate(validated)
        except InsufficientDataError as error:
            raise HTTPException(status_code=400, detail=f"{error}. Добавьте: {', '.join(error.missing)}") from error
        except LLMError as error:
            logger.error("Ошибка модели для «{}»: {}", validated.name, error)
            raise HTTPException(status_code=502, detail=str(error)) from error
        return GenerateResponse(
            result=result,
            review=review_items(result),
            markdown=render_markdown(result),
            filename=file_stem(result),
        )

    return app
