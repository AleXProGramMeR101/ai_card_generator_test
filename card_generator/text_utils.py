"""Вспомогательные функции для работы с текстом: нормализация, числа, имена файлов."""

import re

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}
DASHES = "‐‑‒–-―−"
NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)?")
PARENTHESES_PATTERN = re.compile(r"\([^)]*\)")
NON_WORD_PATTERN = re.compile(r"[^\w\s]")
SPACES_PATTERN = re.compile(r"\s+")
UNIT_IN_KEY_PATTERN = re.compile(r"\(([^()]{1,15})\)$|,\s*([^,]{1,15})$")
GENERIC_STEMS = {"рабоч", "измер", "изм", "налич", "тип", "значе"}
VALUE_WITH_UNIT_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*([^\s\d.,;:()]+)")


def normalize_text(text: str) -> str:
    """Приводит текст к виду для сравнения: нижний регистр, единые тире и пробелы.

    Args:
        text: Исходный текст.

    Returns:
        Нормализованный текст.
    """
    result = text.lower().replace("ё", "е").replace(" ", " ")
    for dash in DASHES:
        result = result.replace(dash, "-")
    return SPACES_PATTERN.sub(" ", result).strip()


def strip_unit(key: str) -> str:
    """Убирает единицу измерения из конца названия характеристики.

    Args:
        key: Название, например «Диапазон измерения влажности, %».

    Returns:
        Название без единицы, например «Диапазон измерения влажности».
    """
    return UNIT_IN_KEY_PATTERN.sub("", key.strip()).strip() or key.strip()


def normalize_key(text: str) -> str:
    """Приводит название характеристики к виду для сопоставления со схемой.

    Args:
        text: Название характеристики, например «Диаметр корпуса (мм)».

    Returns:
        Название без скобок, знаков препинания и лишних пробелов.
    """
    result = PARENTHESES_PATTERN.sub(" ", normalize_text(strip_unit(text)))
    result = NON_WORD_PATTERN.sub(" ", result).replace("_", " ")
    return SPACES_PATTERN.sub(" ", result).strip()


def normalize_number(raw: str) -> str:
    """Приводит число к единому виду: «1,50» и «1.5» становятся «1.5».

    Args:
        raw: Число в виде строки.

    Returns:
        Нормализованная запись числа.
    """
    integer, _, fraction = raw.replace(",", ".").partition(".")
    integer = integer.lstrip("0") or "0"
    fraction = fraction.rstrip("0")
    return f"{integer}.{fraction}" if fraction else integer


def extract_numbers(text: str) -> set[str]:
    """Находит все числа в тексте.

    Args:
        text: Исходный текст.

    Returns:
        Множество нормализованных чисел.
    """
    return {normalize_number(match) for match in NUMBER_PATTERN.findall(text)}


def value_with_unit_pairs(text: str) -> set[str]:
    """Находит в тексте пары «число единица», например «160 кгс/см²».

    Args:
        text: Значение характеристики или текст карточки.

    Returns:
        Множество пар в едином виде: число нормализовано, единица в нижнем регистре.
    """
    return {
        f"{normalize_number(number)} {unit}"
        for number, unit in VALUE_WITH_UNIT_PATTERN.findall(normalize_text(text))
    }


def word_stems(text: str, stem_length: int = 5) -> set[str]:
    """Грубо выделяет основы слов: первые несколько букв значимых слов.

    Args:
        text: Название характеристики.
        stem_length: Сколько первых букв считать основой.

    Returns:
        Множество основ слов длиннее двух букв.
    """
    stems = {word[:stem_length] for word in normalize_key(text).split() if len(word) > 2}
    return stems - GENERIC_STEMS


def is_similar_key(first: str, second: str) -> bool:
    """Проверяет, называют ли две строки одну и ту же характеристику разными словами.

    Args:
        first: Первое название, например «Рабочий диапазон влажности».
        second: Второе название, например «Диапазон измерения влажности, %».

    Returns:
        True, если совпадает большинство значимых основ слов.
    """
    first_stems, second_stems = word_stems(first), word_stems(second)
    if not first_stems or not second_stems:
        return False
    common = len(first_stems & second_stems)
    longest = max(len(first_stems), len(second_stems))
    return common / longest >= 0.6


def slugify(text: str, max_length: int = 60) -> str:
    """Делает из названия товара безопасное имя файла латиницей.

    Args:
        text: Название товара.
        max_length: Максимальная длина результата.

    Returns:
        Имя файла без расширения, например «mp4-u-manometr-pokazyvayuschiy».
    """
    transliterated = "".join(TRANSLIT.get(char, char) for char in text.lower())
    slug = re.sub(r"[^a-z0-9]+", "-", transliterated).strip("-")
    return slug[:max_length].rstrip("-") or "product"
