"""
Внешний АПИ клиент.

Эндпоинты:
  GET  /api/v1/suppliers/{inn}   → {ИНН, имя, статус}
  POST /api/v1/reports           → {file_hash, supplier_inn, total_amount, lines_count}
                                   response 201 {report_id}

Устойчивость: повторяет попытку на 429/5хх с экспоненциальным отклонением.
"""

import logging
from typing import Any
import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
from app.core.config import settings

logger = logging.getLogger(__name__)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    
    return isinstance(exc, httpx.TimeoutException | httpx.NetworkError)


def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.external_api_base_url,
        headers={
            "X-Api-Key": settings.external_api_key,
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )


@retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    stop=stop_after_attempt(6),
    reraise=True,
)
async def get_supplier(inn: str) -> dict[str, Any]:
    """
    Достает поставшика из внешнего АПИ.
    Возвращает словарь с ключами ИНН, имя, статус.
    """
    async with _make_client() as client:
        response = await client.get(f"/api/v1/suppliers/{inn}")

        if response.status_code == 429:
            logger.warning("Внешний API rate лимитирован на GET /suppliers/%s", inn)
        
        response.raise_for_status()

        return response.json()


@retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    stop=stop_after_attempt(6),
    reraise=True,
)
async def post_report(*, file_hash: str, supplier_inn: str, total_amount: float, lines_count: int) -> str:
    """
    Посылает репорт во внеший АПИ.
    Возвращает report_id.
    """
    async with _make_client() as client:
        response = await client.post(
            "/api/v1/reports",
            json={
                "file_hash": file_hash,
                "supplier_inn": supplier_inn,
                "total_amount": total_amount,
                "lines_count": lines_count,
            },
        )

        if response.status_code == 429:
            logger.warning("Внешний API rate лимитирован на POST /reports")
        
        response.raise_for_status()
        data = response.json()
        
        return str(data.get("report_id", ""))