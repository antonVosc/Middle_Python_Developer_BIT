"""
Основные тесты (Docker, Redis и LLM не требуются - все вызовы внешних сервисов имитируются):
  1. Парсер Excel корректно извлекает текст из корректного файла xlsx
  2. Парсер генерирует ValueError при обработке повреждённых байтов файла
  3. SHA-256 является детерминированным и устойчивым к коллизиям
  4. Загрузка повреждённого файла не приводит к сбою сервиса (возвращает 202 или 422, никогда 500)
  5. Дедупликация: загрузка идентичных байтов дважды → во втором ответе is_duplicate=True
  6. Извлечение LLM разбивает корректный JSON-ответ на правильные поля
  7. Клиент LLM удаляет блоки кода Markdown перед разбором JSON
  8. Клиент LLM генерирует исключение ValueError при получении ответа LLM, не представляющего собой JSON
  9. GET /files/{unknown} → 404
  10. GET /stats → правильная структура с нулевыми значениями при пустой БД
  11. GET /results → пустой список при пустой БД
"""

import io
import json
import uuid
from unittest.mock import AsyncMock, patch
import openpyxl
import pytest
from app.services.excel_parser import compute_sha256, xlsx_to_text


def make_xlsx_bytes(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Реестр"

    for row in rows:
        ws.append(row)
    
    buf = io.BytesIO()
    wb.save(buf)

    return buf.getvalue()


SAMPLE_ROWS = [
    ["Реестр платежей № 99 от 01.06.2026", None, None, None],
    ["Поставщик: ООО «Тест»", "ИНН 1234567890", None, None],
    [None, None, None, None],
    ["№", "Назначение платежа", "Сумма, руб", "Дата платежа"],
    [1, "Тестовая оплата", 100000.00, "01.06.2026"],
    [2, "Ещё одна оплата", 50000.00, "02.06.2026"],
]

GOLDEN_EXTRACT = {
    "supplier": {"inn": "1234567890", "name": "ООО Тест"},
    "registry_number": "99",
    "registry_date": "2026-06-01",
    "lines": [
        {"purpose": "Тестовая оплата", "amount": 100000.00, "date": "2026-06-01"},
        {"purpose": "Ещё одна оплата", "amount": 50000.00, "date": "2026-06-02"},
    ],
    "total_amount": 150000.00,
}


def test_xlsx_to_text_parses_cells():
    text = xlsx_to_text(make_xlsx_bytes(SAMPLE_ROWS))
    assert "Реестр платежей № 99" in text
    assert "ИНН 1234567890" in text
    assert "Тестовая оплата" in text
    assert "100000" in text  # можно 100000.0


def test_xlsx_to_text_raises_on_corrupt_file():
    with pytest.raises(ValueError, match="Cannot read xlsx"):
        xlsx_to_text(b"this is not xlsx file")


def test_compute_sha256_deterministic():
    data = b"hello world"

    assert compute_sha256(data) == compute_sha256(data)
    assert len(compute_sha256(data)) == 64


def test_compute_sha256_different_inputs_differ():
    assert compute_sha256(b"aaa") != compute_sha256(b"bbb")


@pytest.mark.asyncio
async def test_broken_file_does_not_crash_api(client):
    resp = await client.post(
        "/files",
        files=[("files", ("broken.xlsx", b"PK\x03\x04 garbage", "application/octet-stream"))],
    )

    assert resp.status_code in (202, 422), f"Статус: {resp.status_code}"


@pytest.mark.asyncio
async def test_duplicate_file_is_flagged(client):
    xlsx_bytes = make_xlsx_bytes(SAMPLE_ROWS)

    resp1 = await client.post(
        "/files",
        files=[("files", ("reg1.xlsx", xlsx_bytes, "application/octet-stream"))],
    )
    
    assert resp1.status_code == 202
    assert resp1.json()[0]["is_duplicate"] is False

    resp2 = await client.post(
        "/files",
        files=[("files", ("reg1_copy.xlsx", xlsx_bytes, "application/octet-stream"))],
    )

    assert resp2.status_code == 202
    assert resp2.json()[0]["is_duplicate"] is True


@pytest.mark.asyncio
async def test_llm_extract_parses_valid_json():
    from app.services.llm_client import extract_registry

    with patch("app.services.llm_client._call_llm_api", new_callable=AsyncMock) as m:
        m.return_value = json.dumps(GOLDEN_EXTRACT)

        result = await extract_registry("fake xlsx text")

    assert result["supplier"]["inn"] == "1234567890"
    assert result["registry_number"] == "99"
    assert result["registry_date"] == "2026-06-01"
    assert len(result["lines"]) == 2
    assert result["total_amount"] == 150000.00


@pytest.mark.asyncio
async def test_llm_extract_strips_markdown_fences():
    from app.services.llm_client import extract_registry

    fenced = "```json\n" + json.dumps(GOLDEN_EXTRACT) + "\n```"
    with patch("app.services.llm_client._call_llm_api", new_callable=AsyncMock) as m:
        m.return_value = fenced
        result = await extract_registry("fake text")

    assert result["supplier"]["inn"] == "1234567890"


@pytest.mark.asyncio
async def test_llm_extract_raises_on_non_json_response():
    from app.services.llm_client import extract_registry

    with patch("app.services.llm_client._call_llm_api", new_callable=AsyncMock) as m:
        m.return_value = "Невозможно обработать файл."
        with pytest.raises(ValueError, match="not valid JSON"):
            await extract_registry("some text")


@pytest.mark.asyncio
async def test_get_unknown_file_returns_404(client):
    resp = await client.get(f"/files/{uuid.uuid4()}")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_stats_returns_correct_shape(client):
    resp = await client.get("/stats")
    assert resp.status_code == 200

    data = resp.json()
    
    for key in ("total_files", "done", "pending", "processing", "error", "cache_hits", "cache_hit_rate", "total_payment_lines"):
        assert key in data, f"Нету ключа: {key}"
    
    assert data["total_files"] == 0
    assert data["cache_hit_rate"] == 0.0


@pytest.mark.asyncio
async def test_results_empty_on_fresh_db(client):
    resp = await client.get("/results")
    
    assert resp.status_code == 200
    assert resp.json() == []