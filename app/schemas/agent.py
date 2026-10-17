
from pydantic import BaseModel, Field


class AgentAskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class AgentAskOut(BaseModel):
    answer: str
    steps: int
    stopped_reason: str
    run_id: str
