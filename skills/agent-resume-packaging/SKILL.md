---
name: agent-resume-packaging
description: 面向 Agent / 大模型应用开发岗的简历包装技能：把真实项目（代码、测试、运行轨迹、git 历史）整理成可被追问的简历要点，并用「主张—证据账本 + 反假审计脚本」把编造和无出处数字挡在投递之前。当用户要求「包装简历」「优化简历」「投 Agent 开发岗」「让简历看起来不像假的」「准备简历要点/HR 开场白」时使用；只做岗位匹配分析或模拟面试时不要使用本技能。
---

# /agent-resume-packaging：Agent 岗简历包装

把「我做过什么」翻译成「招聘方能看懂、能追问、我答得上来」的表达。本技能解决的不是措辞漂亮问题，而是**事实层太薄**的问题：事实不够时，模型只能编，编出来的东西你自己看着都假。

## 为什么反复投喂 JD/别人的简历/面经没用

| 你喂进去的东西 | 它其实属于 | 正确用途 | 错误用途 |
| --- | --- | --- | --- |
| 别人的优秀简历 | 结构先验 | 学 bullet 的组织方式 | 抄经历、抄数字、抄技术栈 |
| JD、岗位描述 | 领域先验 | 提取能力词典，决定选词和排序 | 当成自己会做的证据 |
| 面经、面试题 | 追问先验 | 检查每条 bullet 能不能被追问 | 当成经历来源 |
| 你的仓库、测试、运行轨迹 | **事实先验** | 生成 bullet 与证据 | ——（这里才是缺的） |

结论：JD、面经、别人的简历只能告诉你「怎么表达」和「会被问什么」，永远不能提供「你做过什么」。事实先验必须来自你自己的交付物。

## 三层先验怎么给（按顺序，不要跳）

1. **事实先验（必做）**：从项目仓库生成 [主张—证据账本](../references/claim-evidence-ledger.md)。
   - 输入：源码、测试文件、`pytest` 输出、运行轨迹 JSONL、git log、你与 AI 的结对对话。
   - 产物：`ledger.json`，每条主张含 `source_fact`（原始事实）、`candidate_wording`（候选措辞）、`sources`（证据位置）、`responsibility_level`（职责等级）、`verification_status`（已确认/待确认/已过期/不采用）、`interview_details`（能回答的追问）、`boundary`（个人边界）。
   - 校验：`python3 scripts/validate_claim_ledger.py ledger.json`
2. **结构先验**：用 [Agent 岗 bullet few-shot](../references/bullet-few-shots-agent.md) 对齐「问题/演进 → 机制 → 约束 → 结果」的写法。只学结构，禁止复制其中的项目名、数字、领域名词。
3. **领域先验**：按 [JD 语料到能力词典](../references/jd-corpus-to-capability-map.md) 把收集到的 JD 拆成「能力词典 + 高频追问」，用于选支柱名和排序，不允许进入事实层。

## 工作流程

1. 确认目标岗位（默认 Agent 开发/大模型应用开发）、投递渠道和已有的求职材料目录。
2. 读取事实材料：仓库路径、测试结果、运行轨迹、git log、已有简历。缺材料时先要**材料**，不要先要「更好的措辞」。
3. 建账本：为每段能写进简历的经历写 1—3 条主张，先写 `source_fact`，再写 `candidate_wording`；不能确定的一律 `待确认` 并在措辞里保留 `【待补：...】`。
4. 抽支柱：每个项目抽 4—6 个「通用工程能力」支柱名（如分层工具编排、运行时预算与降级、租户隔离的检索边界、可观测运行轨迹、可替换的模型接入层）。项目内部类名、函数名、路径不能当支柱名。
5. 成稿：按 few-shot 结构写 bullet，每条挂 `【证据：claim-xxx】`；没有实测指标就写可验证的架构结果或「收益待测」，不写百分比。
6. 审计：`python3 scripts/audit_resume.py 简历.md --ledger ledger.json`，逐条按「改法」修，直到 draft 模式 0 error。
7. 投递前：`--mode final` 再跑一次，`待确认` 内容必须清零。
8. 交付：简历要点 + 账本 + 审计报告 + 每条的面试追问清单。

## 表达边界

- 公司、职位、时间、学历保持真实；强动词（主导/负责人/Owner/从 0 到 1）只在账本 `responsibility_level` 匹配时使用。
- 没有实测数据不写百分比、延迟、用户量、成本下降；可写「接口收敛、失败隔离、预算上限、可复现测试条数」这类可验证结果。
- 团队/平台/AI 完成的部分单独标注，不冒领。
- 内部私名（私有类名、下划线字段、内部路径、事件名）不上一级 bullet，集中放进「源码证据索引」。
- 不把「我让 AI 写完了代码」写成「我主导了架构」；如实写「与 AI 结对实现并补全测试」。

## 硬性交付

| 文件 | 内容 |
| --- | --- |
| `ledger.json` | 主张—证据账本，状态只允许 已确认/待确认/已过期/不采用 |
| `简历-{岗位}.md` | 可直接粘贴进简历的要点，每条带证据标记 |
| 审计报告 | `audit_resume.py` 的文本或 `--json` 输出 |
| 追问清单 | 每条 bullet 对应的「为什么这么设计 / 怎么权衡 / 怎么验证」 |

## 质量门禁

- [ ] 每条 bullet 以 `**通用支柱名：**` 开头，支柱名不是私有类名或函数名。
- [ ] 每条 bullet 至少具备「问题或演进 + 机制 + 结果」，关键条补充约束或边界。
- [ ] 每个数字都能回指账本条目，并写明口径；无实测的写「待测」。
- [ ] 强动词有账本 `responsibility_level` 支撑，且 `interview_details` 非空。
- [ ] 最终稿不含 `【待补】`、`待确认`、`已过期`、`不采用`。
- [ ] 内部私名已抽象或下沉到源码证据索引。
- [ ] 审计脚本 draft 模式 0 error，final 模式 0 error。

## 脚本

```bash
# 账本结构校验
python3 scripts/validate_claim_ledger.py assets/claim-ledger-template.json

# 反假审计（示例：反面稿 vs 改后稿）
python3 scripts/audit_resume.py examples/resume-before.md --ledger assets/claim-ledger-template.json
python3 scripts/audit_resume.py examples/resume-after.md  --ledger assets/claim-ledger-template.json --mode final
```

两个脚本零依赖，只用 Python 标准库；有 error 时退出码为 1，可直接接进「投递前门禁」。
