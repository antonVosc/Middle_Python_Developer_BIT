"""
Маршруты API:
  POST /files          — загрузка одного или нескольких файлов в формате .xlsx (асинхронная обработка)
  GET  /files/{id}     — статус и результат для отдельного файла
  GET  /results        — поиск платежных строк с использованием фильтров
  GET  /stats          — статистика очереди и кэша
"""

import logging
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.api.schemas import FileStatusResponse, FileUploadResponse, PaymentResultSchema, StatsResponse
from app.core.config import settings
from app.core.database import get_db
from app.models.file_record import FileRecord, FileStatus, PaymentLine
from app.services.excel_parser import compute_sha256

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/files", response_model=list[FileUploadResponse], status_code=202)
async def upload_files(files: list[UploadFile] = File(...), db: AsyncSession = Depends(get_db)):
    from app.workers.tasks import process_file

    results: list[FileUploadResponse] = []
    upload_path = Path(settings.upload_dir)
    upload_path.mkdir(parents=True, exist_ok=True)

    for upload in files:
        if not upload.filename or not upload.filename.endswith(".xlsx"):
            raise HTTPException(status_code=422, detail=f"Разрешены только .xlsx файлы, получил: {upload.filename}")
        
        data = await upload.read()
        sha256 = compute_sha256(data)

        existing = await db.scalar(select(FileRecord).where(FileRecord.sha256 == sha256).where(FileRecord.is_duplicate == False).order_by(FileRecord.created_at).limit(1))
        
        if existing is not None:
            dup_record = FileRecord(
                filename=upload.filename,
                sha256=sha256,
                status=existing.status,
                is_duplicate=True,
                duplicate_of_id=existing.id,
                supplier_inn=existing.supplier_inn,
                supplier_name=existing.supplier_name,
                registry_number=existing.registry_number,
                registry_date=existing.registry_date,
                total_amount=existing.total_amount,
                supplier_status=existing.supplier_status,
                report_id=existing.report_id,
            )
            db.add(dup_record)

            await db.commit()
            await db.refresh(dup_record)

            logger.info("Повтор файла %s → %s", upload.filename, existing.id)
            results.append(
                FileUploadResponse(
                    id=dup_record.id,
                    filename=dup_record.filename,
                    status=dup_record.status.value,
                    is_duplicate=True,
                )
            )

            continue

        file_on_disk = upload_path / sha256
        
        if not file_on_disk.exists():
            file_on_disk.write_bytes(data)

        record = FileRecord(filename=upload.filename, sha256=sha256, status=FileStatus.PENDING, is_duplicate=False)
        db.add(record)

        await db.commit()
        await db.refresh(record)

        # Отправка в очередь рабочих процессов (неблокирующий режим)
        process_file.apply_async(args=[str(record.id)], queue="docflow")

        logger.info("На очереди файла %s (id=%s)", upload.filename, record.id)
        results.append(
            FileUploadResponse(
                id=record.id,
                filename=record.filename,
                status=record.status.value,
                is_duplicate=False,
            )
        )
    
    return results


@router.get("/files/{file_id}", response_model=FileStatusResponse)
async def get_file_status(file_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Возвращает статус и результат одного файла."""
    record = await db.scalar(select(FileRecord).where(FileRecord.id == file_id).options(selectinload(FileRecord.payment_lines)))

    if record is None:
        raise HTTPException(status_code=404, detail="Файл не найден")
    
    return FileStatusResponse.model_validate(record)

@router.get("/results", response_model=list[PaymentResultSchema])
async def get_results(
    supplier_inn: str | None = Query(None, description="Фильтр по ИНН поставшика"),
    date_from: str | None = Query(None, description="Фильтр по дате выплаты >= (ГГГГ-ММ-ДД)"),
    date_to: str | None = Query(None, description="Фильтр по дате выплаты <= (ГГГГ-ММ-ДД)"),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Поиск строк платежей во всех обработанных файлах.

    Используется составной индекс по (file_record_id, payment_date) + индекс по supplier_inn для быстрой
    фильтрации среди сотен тысяч строк.
    """
    # Создает запрос с JOIN, чтобы можно было фильтровать по supplier_inn в таблице file_records
    stmt = (
        select(
            PaymentLine.file_record_id,
            FileRecord.filename,
            FileRecord.supplier_inn,
            FileRecord.supplier_name,
            FileRecord.registry_number,
            FileRecord.registry_date,
            PaymentLine.purpose,
            PaymentLine.amount,
            PaymentLine.payment_date,
        )
        .join(FileRecord, PaymentLine.file_record_id == FileRecord.id)
        .where(FileRecord.status == FileStatus.DONE)
        .where(FileRecord.is_duplicate == False)
    )

    if supplier_inn:
        stmt = stmt.where(FileRecord.supplier_inn == supplier_inn)
    
    if date_from:
        stmt = stmt.where(PaymentLine.payment_date >= date_from)
    
    if date_to:
        stmt = stmt.where(PaymentLine.payment_date <= date_to)

    stmt = stmt.order_by(PaymentLine.payment_date.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).all()

    return [
        PaymentResultSchema(
            file_id=row.file_record_id,
            filename=row.filename,
            supplier_inn=row.supplier_inn,
            supplier_name=row.supplier_name,
            registry_number=row.registry_number,
            registry_date=row.registry_date,
            purpose=row.purpose,
            amount=row.amount,
            payment_date=row.payment_date,
        )
        for row in rows
    ]

@router.get("/stats", response_model=StatsResponse)
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Возвращает статистику очереди обработки и коэффициент попадания в кэш."""
    status_counts = (
        await db.execute(
            select(FileRecord.status, func.count(FileRecord.id))
            .where(FileRecord.is_duplicate == False)
            .group_by(FileRecord.status)
        )
    ).all()

    counts = {row[0]: row[1] for row in status_counts}
    total = sum(counts.values())

    cache_hits = await db.scalar(
        select(func.count(FileRecord.id)).where(FileRecord.is_duplicate == True)
    ) or 0

    total_lines = await db.scalar(select(func.count(PaymentLine.id))) or 0
    all_requests = total + cache_hits
    hit_rate = cache_hits / all_requests if all_requests > 0 else 0.0
    
    return StatsResponse(
        total_files=total,
        done=counts.get(FileStatus.DONE, 0),
        pending=counts.get(FileStatus.PENDING, 0),
        processing=counts.get(FileStatus.PROCESSING, 0),
        error=counts.get(FileStatus.ERROR, 0),
        cache_hits=cache_hits,
        cache_hit_rate=round(hit_rate, 3),
        total_payment_lines=total_lines,
    )