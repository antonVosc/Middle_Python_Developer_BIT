"""
Celery task: загрузка Excel файла
"""

import asyncio
import logging
import uuid
from datetime import date
from pathlib import Path
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.file_record import FileRecord, FileStatus, PaymentLine
from app.services.excel_parser import xlsx_to_text
from app.services.external_api import get_supplier, post_report
from app.services.llm_client import extract_registry
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()

    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="app.workers.tasks.process_file", bind=True, max_retries=3, default_retry_delay=10)
def process_file(self, file_record_id: str) -> dict:
    return _run_async(_process_file_async(file_record_id))


async def _process_file_async(file_record_id: str) -> dict:
    record_uuid = uuid.UUID(file_record_id)

    async with AsyncSessionLocal() as session:
        record = await session.get(FileRecord, record_uuid)

        if record is None:
            logger.error("FileRecord %s не найден", file_record_id)
        
            return {"status": "error", "reason": "not found"}
        
        record.status = FileStatus.PROCESSING
        
        await session.commit()

        try:
            file_path = Path(settings.upload_dir) / record.sha256

            if not file_path.exists():
                raise FileNotFoundError(f"Файл не найден на диске: {file_path}")
            
            file_bytes = file_path.read_bytes()
            xlsx_text = xlsx_to_text(file_bytes)

            # для LLM
            extracted = await extract_registry(xlsx_text)
            registry_date = date.fromisoformat(extracted["registry_date"])

            record.supplier_inn = extracted["supplier"]["inn"]
            record.supplier_name = extracted["supplier"]["name"]
            record.registry_number = extracted["registry_number"]
            record.registry_date = registry_date
            record.total_amount = float(extracted["total_amount"])
            
            for line_data in extracted["lines"]:
                line = PaymentLine(
                    file_record_id=record.id,
                    purpose=line_data["purpose"],
                    amount=float(line_data["amount"]),
                    payment_date=date.fromisoformat(line_data["date"]),
                )

                session.add(line)

            await session.flush()

            # Проверка поставщика через внешний API
            try:
                supplier_info = await get_supplier(record.supplier_inn)
                record.supplier_status = supplier_info.get("status", "unknown")
            except Exception as exc:
                logger.warning("Невозможно проверить поставщика %s: %s", record.supplier_inn, exc)
                record.supplier_status = "unknown"

            # Репорт для внешнего API
            try:
                report_id = await post_report(
                    file_hash=record.sha256,
                    supplier_inn=record.supplier_inn,
                    total_amount=record.total_amount,
                    lines_count=len(extracted["lines"]),
                )

                record.report_id = report_id
            except Exception as exc:
                logger.warning("Невозможно отправить репорт для %s: %s", file_record_id, exc)
            
            record.status = FileStatus.DONE
            
            await session.commit()

            logger.info(
                "Фвйл %s обработан: %s строк, всего %.2f",
                file_record_id,
                len(extracted["lines"]),
                record.total_amount,
            )

            return {"status": "done", "file_id": file_record_id}
        except Exception as exc:
            logger.exception("Невозможно прочесть файл %s: %s", file_record_id, exc)
            record.status = FileStatus.ERROR
            record.error_message = str(exc)[:1000]
            await session.commit()
            
            return {"status": "error", "reason": str(exc)}