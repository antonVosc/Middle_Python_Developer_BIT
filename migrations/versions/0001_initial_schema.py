"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-16

"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "file_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.Enum("pending", "processing", "done", "error", name="filestatus"), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("supplier_inn", sa.String(12), nullable=True),
        sa.Column("supplier_name", sa.String(255), nullable=True),
        sa.Column("registry_number", sa.String(50), nullable=True),
        sa.Column("registry_date", sa.Date, nullable=True),
        sa.Column("total_amount", sa.Float, nullable=True),
        sa.Column("supplier_status", sa.String(50), nullable=True),
        sa.Column("report_id", sa.String(255), nullable=True),
        sa.Column("is_duplicate", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("duplicate_of_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["duplicate_of_id"], ["file_records.id"]),
    )

    op.create_index("ix_file_records_sha256", "file_records", ["sha256"])
    op.create_index("ix_file_records_supplier_inn", "file_records", ["supplier_inn"])

    op.create_table(
        "payment_lines",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("file_record_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("file_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.Text, nullable=False),
        sa.Column("amount", sa.Float, nullable=False),
        sa.Column("payment_date", sa.Date, nullable=False),
    )

    op.create_index("ix_payment_lines_file_date", "payment_lines", ["file_record_id", "payment_date"])


def downgrade() -> None:
    op.drop_index("ix_payment_lines_file_date", "payment_lines")
    op.drop_table("payment_lines")
    op.drop_index("ix_file_records_supplier_inn", "file_records")
    op.drop_index("ix_file_records_sha256", "file_records")
    op.drop_table("file_records")
    op.execute("DROP TYPE IF EXISTS filestatus")
