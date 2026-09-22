
from typing import List

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.orm import Session

from app.api.current_user import get_current_user
from app.db import get_db
from app.models.document import Document
from app.models.user import User
from app.schemas.document import DocumentOut
from app.services.document import get_document_by_user_id
from app.services.storage import save_file_to_disk, save_upload

router = APIRouter(prefix="/api/v1/documents",tags=["documents"])

@router.post("",status_code=201,response_model=DocumentOut)
def upload(file:UploadFile = File(...), db: Session = Depends(get_db),current_user:User = Depends(get_current_user)):
    return save_upload(current_user.id,file=file,db=db)

@router.get("", response_model=list[DocumentOut])
def list_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(Document)
        .filter(Document.user_id == current_user.id)
        .order_by(Document.id.desc())
        .all()
    )

@router.get("/{doc_id}",response_model=DocumentOut)
def get_document(doc_id:int,db:Session=Depends(get_db),user:User = Depends(get_current_user)):
    return get_document_by_user_id(doc_id=doc_id,db=db,user=user)