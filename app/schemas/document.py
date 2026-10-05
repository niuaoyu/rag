from datetime import datetime

from pydantic import BaseModel


class UploadResponse(BaseModel):
    document_id: int
    filename: str
    status: str
    message: str


class DocumentResponse(BaseModel):
    id: int
    filename: str
    status: str
    error: str | None = None
    chunk_count: int
    created_at: datetime

    model_config = {"from_attributes": True}
