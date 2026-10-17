# app/agent/trace.py
# 运行轨迹：一次 Agent 运行 = 一串结构化事件。
# 线上它是排障/复盘用的观测数据；求职场景里它就是「这个项目真实跑过」的证据源。

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class Tracer:
    """内存事件列表 + 可选 JSONL 落盘。

    写盘失败（磁盘满、目录不可写）不应该让一次问答直接 500，
    因此只累加 write_errors 计数，事件仍然留在内存里可被接口返回。
    """

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    path: Path | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    write_errors: int = 0

    @classmethod
    def with_path_dir(cls, path_dir: Path | str, *, run_id: str | None = None) -> "Tracer":
        run_id = run_id or uuid.uuid4().hex
        return cls(run_id=run_id, path=Path(path_dir) / f"{run_id}.jsonl")

    def record(self, kind: str, **payload: Any) -> dict[str, Any]:
        event = {"run_id": self.run_id, "kind": kind, "at": _now_iso(), **payload}
        self.events.append(event)
        self._append_to_file(event)
        return event

    def _append_to_file(self, event: dict[str, Any]) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            self.write_errors += 1

    def of_kind(self, kind: str) -> list[dict[str, Any]]:
        return [event for event in self.events if event["kind"] == kind]

    @property
    def summary(self) -> dict[str, Any]:
        tool_calls = self.of_kind("tool_call")
        return {
            "run_id": self.run_id,
            "steps": len(self.of_kind("llm_response")),
            "tool_calls": len(tool_calls),
            "tool_errors": sum(1 for event in tool_calls if not event.get("ok")),
            "write_errors": self.write_errors,
        }
