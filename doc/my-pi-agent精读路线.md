# my-pi-agent 精读路线：用最少时间换到"能面试的 Agent 认知"

> 目标仓库：https://github.com/zxj-2023/my-pi-agent（实测：3 个 Python 包 + Node TUI + 评测；`src` 下 86 个 `.py`、约 16.5k 行；全仓库 315 个文件；README 自述 814 个离线用例）
> 一句话结论：**不要通读它。** 只读 6 个文件 + 3 篇文档（≈1400 行），产出是你自己仓库里的 200 行 mini-agent。

## 0. 这条路线自己的终点 A（判定）

**A =** 你能 (1) 在 3 分钟内白板讲清"一次带工具调用的请求，从入口到落盘经过哪些阶段、每个阶段的关键不变式是什么"；(2) 在 `/workspace` 里写出 200 行 mini-agent，检索工具跑通，并有你自己写的 ≥5 个测试。

**不是 A：** 读完 12 篇 core 文档、看懂 TUI、能背出七阶段流水线的名字、把仓库 clone 到本地。

**最近的测试：** `uv run python -m pytest -q tests/core/test_agent_loop_pure.py`（18 个用例，用 `FakeLLM` 替身，**不需要 API key**）——先跑通它，再谈读懂。

时间盒：**≤12h**，全部塞在 W5-W6，每天 2h。

## 1. 精读顺序（只读这些，带问题读）

| 顺序 | 文件 | 行数 | 带着什么问题读 |
|---|---|---|---|
| 1 | `src/my_agent_core/events.py` | 173 | 1 个基类 + 14 个事件（15 个 `frozen dataclass`）。为什么事件只广播事实、**不带**控制逻辑？（对比你 `app/api/v1/*` 直接 return） |
| 2 | `src/my_agent_core/tools/core.py` | 339 | `@tool` 的 JSON Schema 从哪来？工具里抛异常最后去哪了？（找 `ToolResult(ok=False)`）为什么要截断到 50KB/2000 行？ |
| 3 | `src/my_agent_core/registry.py` | 198 | `execute_tool` 与 `execute_batch` 差别？为什么强调"按 source order 广播"（因果时序）？ |
| 4 | `src/my_agent_llm/client.py` + `providers/registry.py` | 116+ | 门面为什么是这 5 个方法：`chat/stream/achat/achat_stream/astream_events`？（同步/异步 × 普通/流式） |
| 5 | `src/my_coding_agent/tools/ls.py` | 77 | 一个"完整工具"的样板：`resolve_path` + `wrap_tool_executor`(参数别名) + 截断 + 错误字符串化。← **你要照着它写自己的第一个工具** |
| 6 | `src/my_agent_core/loop.py` | 771 | 只精读三处：`_assistant_turn`(L105起)、`_execute_tools_turn`(L319起，七阶段)、`run_agent_loop`(L521起，内外双循环)。问：循环什么时候停？（`stop_reason` 有哪几种） |
| 文档 | `docs/core/01-tool-system.md`、`docs/core/03-agent-loop.md`、`docs/llm/01-llm-boundary.md` | — | 只看章节标题 + 你读代码时的疑问点，不逐字读 |
| 测试 | `tests/core/conftest.py` 里的 `FakeLLM` | 161 | **抄进你自己的项目**：这是不烧 token 就能测 Agent 的关键道具 |

**明确不读（等真需要再看，别当"准备"）**：`PROGRESS.md`(113KB)、`my-pi-tui/**`、`mcp.py`、`macros.py`、`subagents.py`、`rpc_server.py`、`session_ops.py`、`model_catalog.py`、`my-pi-eval/**`。
唯一例外：论文 benchmark 要抄评测框架的话，只读 `docs/eval/01-evaluation-harness-architecture.md`。

## 2. 六个可验证终点（按顺序做，每块 ≤1h，做完立刻做交接动作）

### E0 跑起来 + 看一次真实事件流（L0，30min）
- 动作：`git clone` → `uv sync` → `uv run python -m pytest -q tests/core/test_agent_loop_pure.py tests/core/test_tools.py`
- DoD：用例全绿；在笔记里记 1 行"我原本以为会失败的用例 + 真实结果"
- 交接：关掉终端，写出 3 个 event 名字及其触发时机（如 `ToolExecutionStart` 在何时发）

### E1 读懂一个"工具"的所有权（L1，45min）
- 动作：打开 `src/my_coding_agent/tools/ls.py`，**遮住 `resolve_path`/`truncate_output`/`wrap_tool_executor` 的实现**，只留函数签名，自己补出这三个函数
- DoD：`python -c` 跑通 `ls(".")` 与 `ls("../..")`、`ls("不存在的目录")` 三种情况；输出与 `os.listdir` 一致
- 交接：写出"为什么要 `resolve_path`"3 行；回答：如果直接 `os.listdir(用户输入)` 会有什么问题

### E2 你的第一个工具（L2，45min，写在 `/workspace`）
- 动作：新建 `app/agent/tools.py`，用你仓库已有的 pydantic，实现 `@tool` 装饰器的最小版（生成 JSON Schema）+ `ToolResult` + `ToolRegistry`（`register/get/get_schemas/execute`）
- DoD：`python -m pytest -q tests/test_tools_mini.py` 全绿（≥4 用例：正常返回 / 参数缺类型报错 / 工具抛异常变 `ok=False` / schema 字段正确）
- 交接：画一次"用户参数 → schema → 模型选择 → 执行 → 结果字符串化"的流转

### E3 LLM 边界 + 测试替身（L2，45min）
- 动作：抄 `tests/core/conftest.py` 的 `FakeLLM` 思路，写 `tests/fakes.py`：一个不联网、可预置"第一轮要调工具、第二轮给答案"的假 LLM
- DoD：`pytest` 里用 FakeLLM 断言"工具被调用了一次且消息历史顺序正确"，**全程不烧 token、不需要 API key**
- 交接：用一句话说清"为什么 Agent 测试必须先有替身"

### E4 200 行 mini ReAct 循环（L3，90min，本路线核心）
- 动作：新建 `app/agent/loop.py`，写 `async def run_mini_loop(messages, registry, llm) -> AsyncIterator[Event]`：调模型 → 有 tool_calls 就执行并把结果作为 `role="tool"` 消息追加 → 再调模型 → 无 tool_calls 就 `AgentEnd(stop_reason="end_turn")`；带最大轮数熔断
- DoD（≥5 用例，自己写）：①无工具直接结束 ②一轮工具后结束 ③工具报错不死循环 ④超过 max_turns 停止且 `stop_reason` 正确 ⑤`FakeLLM` 收到的第二次请求里含 tool 消息
- 交接：录音 3 分钟讲清"循环什么时候停"，回放找 1 个说不清的点
- 会考：为什么把循环写成 **async generator 产出事件**，而不是直接 `return` 最终字符串？（提示：流式/取消/多端复用）

### E5 接进你的 RAG 项目（L3→L4，60min）
- 动作：把"检索"注册成工具 `search_docs(query: str, top_k: int=5)`，返回 `[{doc_id, filename, score, snippet}]`（W3-W4 之后才有真检索，先用假数据也可，但**接口字段必须定型**）
- DoD：`curl` 一个 `/ask` 接口，返回 `{"answer": "...", "citations": [{"doc_id":1,"snippet":"..."}]}`；pytest 断言 citations 非空且 doc_id 属于当前用户
- 交接：回答"如果检索工具返回 100 万字符，会发生什么？框架里对应的机制是什么？"

### E6 变式压力（L5，45min）——面试前必做
- 动作：加 3 个约束：①只读工具允许并发、写工具串行 ②单工具超时 3s ③工具输出截断到 50KB/2000 行
- DoD：3 个新测试；写 5 行 trade-off（并发带来的收益 vs 因果顺序风险；超时值怎么定；截断会不会丢关键信息）
- 交接：用自己的话讲"Never-Throw 为什么对 Agent 比对普通 Web 服务更重要"

## 3. 会考问题（面试官真会问，按你的项目答；答不出=这块没做完）

1. 一次带工具调用的请求，从入口到落盘经过哪些阶段？每个阶段的关键不变式是什么？（→ E0-E4）
2. 为什么 Agent 循环写成 async generator 产出事件流，而不是 `return` 一个最终字符串？
3. 工具抛异常为什么不能向上抛，而要变成 `ToolResult(ok=False)` 喂回模型？不这样会怎样？（→ Never-Throw）
4. 工具的 JSON Schema 从哪来？手写 schema 和 pydantic 自动生成各有什么坑？
5. 工具输出为什么要截断（50KB/2000 行）？截断会不会丢信息，你怎么权衡？
6. 循环的终止条件有哪几种？模型一直调工具怎么办？（→ 熔断 / `stop_reason`）
7. 为什么"只读工具可并发、写工具要串行"？并发后"按 source order 广播结果"为什么仍然重要？
8. 上下文/会话怎么存？为什么用"只追加"？压缩（compaction）时怎么保证前缀缓存不失效？
9. （接你已有项目）`BackgroundTasks` 与 Celery 的区别？进程崩了卡在 `processing` 怎么办？幂等怎么做？
10. 你怎么知道检索是有效的？（→ 你的 20 条评测集 + 准确率数字；没有数字就是没做过）

## 4. 概念 → 你仓库文件的映射（讲项目时直接用这套话术）

| my-pi-agent 里的概念（证据位置） | 在你 `/workspace` 里的对应物 |
|---|---|
| `Tool` / `ToolResult` / `@tool`（`src/my_agent_core/tools/core.py`） | `app/agent/tools.py`：`search_docs` 返回 `[{doc_id, score, snippet}]`，失败返回 `ok=False` 而不是抛 HTTP 异常 |
| `ToolRegistry.execute_tool/execute_batch`（`src/my_agent_core/registry.py`） | `dict[str, Tool]` + `async def execute(name, args)`，只读并发、写串行 |
| `run_agent_loop`（`src/my_agent_core/loop.py:521`） | `app/agent/loop.py:run_mini_loop`（200 行版） |
| 14 个事件（`src/my_agent_core/events.py`） | 你 `/ask` 的 SSE 事件（`event: tool_start/tool_end/delta/done`），前端/测试都能消费 |
| 只追加 JSONL 会话（`src/my_agent_core/session/jsonl.py`） | 你更该用 `messages` 表 + SQLAlchemy（能讲事务/索引，比 JSONL 更好答） |
| `PermissionGate`（`src/my_coding_agent/permissions.py`） | 你已有 JWT + 文档归属校验 → 讲"工具级权限"（检索只能命中本人文档） |
| `retry.py` 退避重试（429/5xx） | `httpx` 超时 + 重试；和 `BackgroundTasks` 的失败重试连起来讲 |
| `my-pi-eval`（评测框架，`docs/eval/01-*.md`） | 你论文的 benchmark 骨架：同一套"数据集 + 指标 + 可复现命令"的思路 |

## 5. 你要自己写的验收清单（我不给实现，只给断言点）

`tests/test_mini_agent.py`（≥5 个用例）：
1. 无 tool_calls 时：只调一次 LLM，事件序列以 `AgentEnd(stop_reason="end_turn")` 结尾；
2. 一轮工具调用：`ToolExecutionStart` → `ToolExecutionEnd` 成对出现，且第二次 LLM 请求里含 `role="tool"` 消息；
3. 工具抛异常：循环不崩、`is_error=True`、且最终仍能结束；
4. 超过 `max_turns`：`stop_reason == "max_turns"`；
5. 截断：工具返回 3MB 字符串时，进入消息的内容 ≤ 50KB/2000 行且带截断提示。

> 自检：这 5 条能过 + §3 的 10 个问题能答 6 个 = 这条路线毕业。剩下的（MCP、子代理、TUI、插件）**只在面试被问到或工作需要时再学**。


