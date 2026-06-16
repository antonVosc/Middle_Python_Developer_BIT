import enum
import uuid
from datetime import date, datetime
from sqlalchemy import BigInteger, Date, DateTime, Enum, Float, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class FileStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


class SupplierStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


class FileRecord(Base):
    __tablename__ = "file_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[FileStatus] = mapped_column(Enum(FileStatus), default=FileStatus.PENDING)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    supplier_inn: Mapped[str | None] = mapped_column(String(12), nullable=True)
    supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    registry_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    registry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    supplier_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    report_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(default=False)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("file_records.id"), nullable=True)
    payment_lines: Mapped[list["PaymentLine"]] = relationship("PaymentLine", back_populates="file_record", cascade="all, delete-orphan")
    
    __table_args__ = (Index("ix_file_records_sha256", "sha256"), Index("ix_file_records_supplier_inn", "supplier_inn"))


class PaymentLine(Base):
    __tablename__ = "payment_lines"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    file_record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_records.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(Text)
    amount: Mapped[float] = mapped_column(Float)
    payment_date: Mapped[date] = mapped_column(Date)
    file_record: Mapped["FileRecord"] = relationship("FileRecord", back_populates="payment_lines")

    __table_args__ = (Index("ix_payment_lines_file_date", "file_record_id", "payment_date")) # Покрывает JOIN и фильтр даты в GET /results
