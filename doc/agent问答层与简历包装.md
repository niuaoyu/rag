# Agent 问答层与简历包装（M-agent）

> 本文档回答三个问题：①怎么把已经做过的项目变成「不像假的」简历；②怎么在一个具体业务上搭出 Agent 项目；③这套东西怎么落进本仓库。
> 配套技能目录：`skills/agent-resume-packaging/`（SKILL.md + references + 两个零依赖脚本 + 示例）。

## 1. 为什么「喂了 JD、简历、面经，AI 包装出来还是假」

| 你喂的 | 实际属于 | 能提供什么 | 不能提供什么 |
| --- | --- | --- | --- |
| 别人的简历 | 结构先验 | bullet 的组织方式 | 你的经历 |
| JD | 领域先验 | 能力词典、选词排序 | 你会不会 |
| 面经 | 追问先验 | 会被问什么 | 你做过什么 |
| **你的代码、测试、轨迹、git log** | **事实先验** | 可核验的事实 | —— |

结论：前三种先验决定「怎么说」，第四种决定「能不能说」。缺第四种时模型只能编，于是「我看着就不行」。

正确顺序：**先补事实（把项目做出来并留证）→ 再给结构先验（few-shot）→ 最后用领域先验排序选词**。

## 2. 简历包装流水线（四步，都可执行）

1. **建账本**：把真实交付物写成主张—证据账本
   ```bash
   cp skills/agent-resume-packaging/assets/claim-ledger-template.json ledger.json
   python3 skills/agent-resume-packaging/scripts/validate_claim_ledger.py ledger.json
   ```
   字段与状态规则见 `skills/agent-resume-packaging/references/claim-evidence-ledger.md`。
2. **抽支柱 + 成稿**：按 `references/bullet-few-shots-agent.md` 的结构写 bullet，每条挂 `【证据：claim-xxx】`。
3. **审计**：
   ```bash
   python3 skills/agent-resume-packaging/scripts/audit_resume.py 简历.md --ledger ledger.json
   ```
   示例（本仓库自带正反两份）：
   ```bash
   cd skills/agent-resume-packaging
   python3 scripts/audit_resume.py examples/resume-before.md --ledger assets/claim-ledger-template.json  # 8 error / 8 warning
   python3 scripts/audit_resume.py examples/resume-after.md  --ledger assets/claim-ledger-template.json  # 0 error
   ```
4. **投递前门禁**：`--mode final` 再跑一次，`【待补】`/`待确认` 必须清零（退出码 1 直接挡住）。

审计规则是确定性的：无出处指标、无口径数字、夸张百分比、不可验证结果词、强动词越界、引用未确认主张、内部私名泄漏、bullet 缺支柱名。规则实现见 `skills/agent-resume-packaging/scripts/audit_resume.py`。

## 3. 在具体业务上搭 Agent：本仓库已经落地的部分

业务闭环：**上传文档 → 入库 → 检索定位 → 生成回答 → 标注引用**。

| 步骤 | 交付物（可核验） | 对应账本证据 |
| --- | --- | --- |
| 工具化 | `app/agent/tools.py`（ToolSpec/ToolRegistry）、`app/agent/document_tools.py`（按用户绑定工具） | `tests/test_agent_tools.py` 10 条用例 |
| 编排与预算 | `app/agent/loop.py`（有限步循环、步数预算、单步调用上限、模型/工具分别降级） | `tests/test_agent_loop.py` 12 条用例 |
| 观测 | `app/agent/trace.py`（JSONL 轨迹、写盘失败不影响请求） | 轨迹文件 + 轨迹测试 |
| 接口 | `POST /api/v1/agent/ask`（`app/api/v1/agent.py`，未配置 Key 直接 503） | `tests/test_agent_api.py` 5 条用例 |
| 模型接入 | `app/agent/llm.py`（OpenAI 兼容客户端 + `ScriptedLLM` 假模型） | 假模型驱动的确定性回归 |

验证方式（本地）：
```bash
python3 -m pytest -q          # 47 passed
python3 -m pytest tests/test_agent_loop.py -q
```

## 4. 下一步扩展点（把 Agent 从「骨架」做成「有效果」）

- **M5/M6 检索升级**：`app/agent/document_tools.py` 里的 `SEARCH_BACKEND` 目前是文件名检索，切块与向量检索落地后只换实现，工具名与参数不变。
- **真实模型评测**：在 `.env` 配 `LLM_API_KEY` 后，用 10—20 条问题跑一轮，记录工具选择是否正确、是否引用到文档、是否越权，产出评测表（这是「效果」类主张的唯一来源）。
- **多步任务**：把「先检索、再按文档类型分别总结、最后生成答复」固化成 2—3 个可组合工具，步数预算随之上调并做成本对比。

## 5. 简历支柱候选（从本仓库事实出发）

1. **分层工具编排**：schema 与执行边界同源，参数按不可信输入处理。
2. **运行时预算与降级**：步数预算、单步上限、超时、错误分类降级。
3. **租户隔离的检索边界**：权限在工具构造期固定，越权与不存在同文案。
4. **可观测运行轨迹**：结构化事件、参数摘要、写盘失败不阻断主流程。
5. **可替换的模型接入层**：协议适配 + 假模型驱动的确定性回归。

每条支柱要落地成简历句时，都必须先有一条 `已确认` 的账本记录；否则写 `【待补】`。

## 6. 会考问题（自己先答一遍）

- 为什么工具层要做参数校验和超时，而不是在路由层？
- 步数预算设 6 的依据是什么？超预算返回什么？用户会不会觉得答非所问？
- 工具超时用线程 + 事件实现，超时后那个线程去哪了？会不会泄漏？
- 工具失败为什么不让请求 500？如果所有工具都失败呢？
- 轨迹里为什么参数只记摘要？完整记录有什么风险？
- 没有 API Key 时为什么返回 503 而不是 500？
- 怎么证明这个 Agent 比「直接把文档列表丢给模型」更好？（提示：评测集）
