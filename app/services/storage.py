# app/services/storage.py 顶部

from pathlib import Path
import uuid

from fastapi import HTTPException, UploadFile


ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md"}
MAX_SIZE = 10 * 1024 * 1024  # 10mb
UPLOAD_DIR = Path("uploads")
CHUNK_SIZE = 64 * 1024

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
    suffix = Path(file.filename or "<unknown>").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"不支持的文件类型: {suffix}")

    # 目录准备
    user_dir = UPLOAD_DIR / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)

    # uuid重命名
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    target = user_dir / stored_name

    # 流式写入 +大小检验
    size = 0
    try:
        with target.open("wb") as f:
            while chunck:= file.file.read(CHUNK_SIZE):
                size += len(chunck)
                if size > MAX_SIZE:
                    raise HTTPException(status_code=413, detail="文件大小超过限制")
                f.write(chunck)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise  # 保持原来的 413 / 415 等状态码

    except Exception:
        target.unlink(missing_ok=True) # 但凡中断，异常，全部清空
        raise HTTPException(status_code=404, detail="异常")
    return target, size