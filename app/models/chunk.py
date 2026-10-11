"""M5：文档切块表。

设计取舍（面试会问"为什么正文既在关系库又在向量库"）：
- 关系库（本表）是正文的**唯一真相源**，负责事务、级联删除、全文/条件查询。
- 向量库只存 {向量 + 定位信息(id/user_id/document_id/ordinal)}，不存正文。
  理由：向量库的强项是相似度检索，不是事务和一致性；正文放两边必然出现"改了没同步"。
  代价：检索后要多一次 DB 回表（N+1 风险 → 用 in_ 一次批量取回）。
"""

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

import typing
if typing.TYPE_CHECKING:
    from app.models.document import Document


class Chunk(Base):
    __tablename__ = "chunks"
    # 同一文档内序号唯一：保证"重复处理同一份文档"不会插出两套并列序号
    __table_args__ = (UniqueConstraint("document_id", "ordinal", name="uq_chunk_doc_ordinal"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)  # 第几块，从 0 开始
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)  # 由 app/core/tokenizer.py 计算
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="chunks")
