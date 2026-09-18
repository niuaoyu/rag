
from fastapi import APIRouter, File, UploadFile, status
from sqlalchemy.orm import Session

from app.services.storage import save_file_to_disk

router = APIRouter(prefix="/api/v1/documents",tags=["documents"])

@router.post("/upload_test",status_code=200)
def upload_test(file:UploadFile = File(...)):

    target ,size = save_file_to_disk(2,file=file)

    return {"target": str(target), "size": size, "content_type": file.content_type}

