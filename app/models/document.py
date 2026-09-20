


from datetime import datetime

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.models.base import Base 

import typing
if typing.TYPE_CHECKING:
    from app.models.user import User




class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(255),nullable=False)
    store_path: Mapped[str] = mapped_column(String(255),nullable=False)
    size : Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16),nullable=False,default="pending")
    created_at: Mapped[datetime] = mapped_column(nullable=False,server_default=func.now())

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,# 为什么要索引？全量索引SELECT * FROM documents WHERE user_id = 1查询慢 有索引是b树结构，查询快
    )
    user: Mapped["User"] = relationship(back_populates="documents")