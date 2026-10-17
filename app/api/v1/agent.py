# app/api/v1/agent.py
# Agent 问答入口：鉴权 -> 组装当前用户的工具集 -> 跑一轮有限步 Agent -> 返回回答 + 轨迹落盘。

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agent.document_tools import build_document_tools
from app.agent.llm import LLMClient, LLMError, OpenAICompatibleLLM
from app.agent.loop import AgentRunner
from app.agent.trace import Tracer
from app.api.current_user import get_current_user
from app.core.config import settings
from app.db import get_db
from app.models.user import User
from app.schemas.agent import AgentAskIn, AgentAskOut

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


def get_llm_client() -> LLMClient:
    """模型客户端依赖：未配置 Key 时直接 503，而不是等请求打到模型才失败。"""
    if not settings.llm_api_key:
        raise HTTPException(status_code=503, detail="未配置 LLM_API_KEY，Agent 问答暂不可用")
    return OpenAICompatibleLLM(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout=settings.llm_timeout_seconds,
    )


@router.post("/ask", response_model=AgentAskOut)
def ask(
    payload: AgentAskIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    llm: LLMClient = Depends(get_llm_client),
):
    tracer = Tracer.with_path_dir(settings.agent_trace_dir)
    runner = AgentRunner(
        llm=llm,
        tools=build_document_tools(db, current_user.id),
        max_steps=settings.agent_max_steps,
        tool_timeout=settings.agent_tool_timeout_seconds,
        tracer=tracer,
    )
    try:
        result = runner.run(payload.question)
    except LLMError as exc:
        # llm 依赖在构造阶段就可能抛 LLMError（例如 base_url 非法），统一转 502
        raise HTTPException(status_code=502, detail=str(exc))
    return AgentAskOut(
        answer=result.answer,
        steps=result.steps,
        stopped_reason=result.stopped_reason,
        run_id=result.run_id,
    )
