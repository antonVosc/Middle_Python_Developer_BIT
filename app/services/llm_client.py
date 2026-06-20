import asyncio
import json
import logging
import time
from typing import Any
import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
from app.core.config import settings

logger = logging.getLogger(__name__)
_llm_semaphore = asyncio.Semaphore(3)
_last_release_time: float = 0.0
_MIN_INTERVAL = 60.0 / settings.llm_rpm_limit


EXTRACTION_PROMPT = """Ты — система извлечения данных из реестров платежей строительной компании.

Тебе передаётся содержимое Excel-файла в текстовом виде (колонки разделены табуляцией).

Извлеки данные и верни ТОЛЬКО валидный JSON без каких-либо пояснений, markdown-блоков и лишнего текста.

Правила:
1. ИНН поставщика — строка из 10 цифр. Может быть в одной ячейке с названием (например "ООО «МегаСтрой» ИНН 7724111220"). Извлеки только цифры.
2. Название поставщика — без кавычек-ёлочек, без слова "ИНН".
3. Номер реестра — только цифры из строки вида "Реестр платежей № 41 от 22.05.2026".
4. Дата реестра — в формате YYYY-MM-DD.
5. Строки платежей: назначение платежа, сумма (число с двумя знаками после запятой, убери пробелы-разделители тысяч и замени запятую на точку), дата (YYYY-MM-DD). Колонки могут быть в любом порядке — определяй по заголовку.
6. total_amount — сумма всех платежей, округлённая до 2 знаков.
7. Пропускай строки с "Итого", "ИТОГО", "Всего".

Формат ответа:
{
  "supplier": {"inn": "7701123451", "name": "ООО СтройМонтаж Север"},
  "registry_number": "41",
  "registry_date": "2026-05-22",
  "lines": [
    {"purpose": "...", "amount": 39135.38, "date": "2026-05-09"}
  ],
  "total_amount": 1783927.09
}

Данные из файла:
"""


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    
    return isinstance(exc, httpx.TimeoutException | httpx.NetworkError)


@retry(retry=retry_if_exception(_is_retryable), wait=wait_exponential(multiplier=2, min=4, max=60), stop=stop_after_attempt(5), reraise=True)
async def _call_llm_api(text: str) -> str:
    """Сырой HTTP вызов к LLM API. Повторный вызов при возникновении ошибок."""
    global _last_release_time

    async with _llm_semaphore:
        now = time.monotonic()
        gap = _MIN_INTERVAL - (now - _last_release_time)
        
        if gap > 0:
            await asyncio.sleep(gap)

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{settings.llm_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.llm_model,
                    "messages": [
                        {"role": "user", "content": EXTRACTION_PROMPT + text},
                    ],
                    "temperature": 0,
                    "max_tokens": 2048,
                },
            )

        _last_release_time = time.monotonic()

        if response.status_code == 429:
            logger.warning("Лимит достигнут, повтор запроса")
            
            response.raise_for_status()
        if response.status_code >= 500:
            logger.warning("Ошибка %s, повтор запроса", response.status_code)

            response.raise_for_status()

        response.raise_for_status()

        data = response.json()

        return data["choices"][0]["message"]["content"]


async def extract_registry(xlsx_text: str) -> dict[str, Any]:
    """
    Отправляет текст из xlsx в LLM и парсит JSON ответ.

    Возвращает parsed dict, который соответсвует golden schema или ValueError, если запрос не парсится.
    """
    raw = await _call_llm_api(xlsx_text)
    cleaned = raw.strip()

    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error("LLM не вернул JSON: %s", raw[:500])

        raise ValueError(f"Ответ LLM не являктся JSON: {exc}") from exc

    _validate_registry(result)

    return result


def _validate_registry(data: dict[str, Any]) -> None:
    """Простая проверка структуры"""
    required = ("supplier", "registry_number", "registry_date", "lines", "total_amount")

    for field in required:
        if field not in data:
            raise ValueError(f"Не хватает поля: {field} в ответе LLM")
    
    if "inn" not in data["supplier"] or "name" not in data["supplier"]:
        raise ValueError("Не хватает supplier.inn или supplier.name")
    
    if not isinstance(data["lines"], list) or len(data["lines"]) == 0:
        raise ValueError("Пропущены или пустые строки запроса")