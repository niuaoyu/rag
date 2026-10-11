from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    document_ids: list[int] | None = Field(
        default=None, description="只在这些文档里检索；不传=全部已处理完成的文档"
    )


class CitationOut(BaseModel):
    index: int
    chunk_id: int
    document_id: int
    filename: str
    ordinal: int
    score: float
    snippet: str


class AskResponse(BaseModel):
    question: str
    answer: str | None
    mode: str  # llm | retrieval_only | no_context
    citations: list[CitationOut]
    retrieved_count: int
    latency_ms: int
    note: str | None = None
