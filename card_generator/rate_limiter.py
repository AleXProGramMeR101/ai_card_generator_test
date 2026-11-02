"""Ограничение частоты запросов к модели из веб-интерфейса, чтобы не сжечь лимиты ключа."""

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable


class RateLimiter:
    """Скользящее окно: не больше limit запросов за window_seconds с одного адреса."""

    def __init__(self, limit: int, window_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:
        """Создаёт ограничитель.

        Args:
            limit: Сколько запросов разрешено за окно; 0 - без ограничения.
            window_seconds: Длина окна в секундах.
            clock: Источник времени, подменяется в тестах.
        """
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Проверяет, можно ли выполнить ещё один запрос, и учитывает его.

        Args:
            key: Идентификатор клиента, обычно IP-адрес.

        Returns:
            True, если запрос разрешён.
        """
        if self._limit <= 0:
            return True
        now = self._clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self._window:
                hits.popleft()
            if len(hits) >= self._limit:
                return False
            hits.append(now)
            return True
