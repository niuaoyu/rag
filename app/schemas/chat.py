from pydantic import BaseModel, Field


class Citation(BaseModel):
    document_id: int
    filename: str
    page: int | None = None
    content: str
    score: float | None = None


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    conversation_id: int | None = None
    use_tools: bool = True


class ChatResponse(BaseModel):
    conversation_id: int
    answer: str
    citations: list[Citation] = []
    tool_calls: list[dict] = []
