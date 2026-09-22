# app/services/storage.py 顶部

from pathlib import Path
import uuid

from fastapi import Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import get_db


ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md"}
MAX_SIZE = 10 * 1024 * 1024  # 10mb
# UPLOAD_DIR = Path("uploads")

CHUNK_SIZE = 64 * 1024

def validate_file_upload(file: UploadFile) -> str:
    suffix = Path(file.filename or "<unknown>").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"不支持的文件类型: {suffix}")
    return suffix

def write_stream(file: UploadFile, target: Path) -> int:
    """
    Writes the content of an UploadFile to a target path in chunks.

    Args:
        file (UploadFile): The uploaded file.
        target (Path): The target path where the file will be saved.

    Returns:
        int: The total size of the written file in bytes.
    """
    # 「流式」的核心价值,不能写之前就知道大小，因为靠file.size，Content-Length请求头都不可靠
    # 所以要边写边算大小（不能一下子写完，file.file.read() 如果1g？直接吃1g内存），超过限制就抛异常
    size = 0
    try:
        with target.open("wb") as f:
            while chunk := file.file.read(CHUNK_SIZE): 
                size += len(chunk)
                if size > MAX_SIZE:
                    raise HTTPException(status_code=413, detail="文件大小超过限制")
                f.write(chunk)
        return size
    
    except HTTPException:
        target.unlink(missing_ok=True)
        raise  # 保持原来的 413 / 415 等状态码

    except Exception:
        target.unlink(missing_ok=True) # 但凡中断，异常，全部清空
        raise HTTPException(status_code=404, detail="异常")

def save_file_to_disk(user_id:int,file:UploadFile) -> tuple[Path,int]:
    """
    Saves an uploaded file to the disk.

    Args:
        user_id (int): The ID of the user who uploaded the file.
        file (UploadFile): The uploaded file.

    Returns:
        tuple[Path, int]: A tuple containing the path to the saved file and its size.
    """
    # 扩展名检查
    suffix = validate_file_upload(file)

    # 目录准备
    user_dir = settings.upload_dir / str(user_id)   # 所有用到 UPLOAD_DIR 的地方都换
    user_dir.mkdir(parents=True, exist_ok=True)

    # uuid重命名
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    target = user_dir / stored_name

    # 流式写入 +大小检验
    size = write_stream(file, target)

    return target, size

# 新版本，添加导入documents表数据
def save_upload(user_id:int,file:UploadFile,db: Session = Depends(get_db)):
    target,size = save_file_to_disk(user_id,file)
    from app.models.document import Document
    doc = Document(
        filename=file.filename,
        store_path=str(target),
        size=size,
        status="pending",
        user_id=user_id
    )
    try:
        db.add(doc)
        db.commit()
        db.refresh(doc)
    except Exception as e:
        target.unlink(missing_ok=True)   # ← 回滚文件
        raise
    return doc