import uuid
from datetime import date, datetime
from pydantic import BaseModel


class PaymentLineSchema(BaseModel):
    purpose: str
    amount: float
    payment_date: date

    model_config = {"from_attributes": True}


class FileUploadResponse(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    is_duplicate: bool


class FileStatusResponse(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    error_message: str | None = None
    is_duplicate: bool
    duplicate_of_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    # if status=done
    supplier_inn: str | None = None
    supplier_name: str | None = None
    supplier_status: str | None = None
    registry_number: str | None = None
    registry_date: date | None = None
    total_amount: float | None = None
    report_id: str | None = None
    payment_lines: list[PaymentLineSchema] = []

    model_config = {"from_attributes": True}


class PaymentResultSchema(BaseModel):
    file_id: uuid.UUID
    filename: str
    supplier_inn: str
    supplier_name: str
    registry_number: str
    registry_date: date
    purpose: str
    amount: float
    payment_date: date


class StatsResponse(BaseModel):
    total_files: int
    done: int
    pending: int
    processing: int
    error: int
    cache_hits: int
    cache_hit_rate: float
    total_payment_lines: int