from datetime import datetime
from typing import Any

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    app: str
    environment: str


class UpdateSummaryResponse(BaseModel):
    id: int
    branch: str
    update_kind: str
    source_name: str | None
    before_sha: str | None
    after_sha: str
    compare_url: str | None
    changed_files: list[str]
    summary: dict[str, Any]
    created_at: datetime


class MedicineResponse(BaseModel):
    id: int
    dataset: str
    source_key: str
    code: str | None
    name: str
    dosage: str | None
    form: str | None
    packaging: str | None
    public_price: float | None
    reimbursed_price: float | None
    manufacturer: str | None
    category: str | None
    reimbursement_flag: str | None
    extra_flag: str | None
    source_path: str
    is_active: bool
    first_seen_at: datetime
    last_seen_at: datetime


class MessageResponse(BaseModel):
    message: str
