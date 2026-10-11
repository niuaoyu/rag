


from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.models.base import Base 

import typing
if typing.TYPE_CHECKING:
    from app.models.user import User
    from app.models.chunk import Chunk




class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(255),nullable=False)
    store_path: Mapped[str] = mapped_column(String(255),nullable=False)
    size : Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16),nullable=False,default="pending")
    created_at: Mapped[datetime] = mapped_column(nullable=False,server_default=func.now())

    # M4 新增：解析出的全文 + 失败原因。两者都可空：pending/processing 时 text 为空，只有 failed 才写 error_message
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,# 为什么要索引？全量索引SELECT * FROM documents WHERE user_id = 1查询慢 有索引是b树结构，查询快
    )
    user: Mapped["User"] = relationship(back_populates="documents")

    # 一份文档被切成 N 块；删文档时级联删块。注意向量不在这个库里，见 app/services/vector_store.py
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Chunk.ordinal",
    )