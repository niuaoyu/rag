
from datetime import datetime
from sqlalchemy import String, func
from sqlalchemy.orm import DeclarativeBase,Mapped, mapped_column, relationship

import typing 
if typing.TYPE_CHECKING:
    from app.models.document import Document

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(unique=True, index=True,nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255),nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False,server_default=func.now())

    documents: Mapped[list["Document"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan" # delete-orphan级联删除，删除用户时，删除该用户的所有文档
        # all：包括 save-update、merge、refresh-expire、delete
        )