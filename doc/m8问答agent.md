# 模块 M8 接口契约：带引用的问答

## 1. 目标
用检索到的块生成**可溯源**的答案：回答里的 `[1][2]` 能对回 `chunk_id / 文件名 / 块序号 / 相似度`。

## 2. 目录增量
```
app/services/llm.py       # OpenAICompatLLM：httpx 直接打 /chat/completions（含 SSE 流式）
app/services/rag.py       # 三种 mode、提示词、引用组装
app/api/v1/chat.py        # POST /chat/ask（JSON）、POST /chat/ask/stream（SSE）
app/schemas/chat.py
```

## 3. 三种 mode（防自欺的核心）
| mode | 触发条件 | answer | 意义 |
| --- | --- | --- | --- |
| `llm` | 配了 key 且调用成功 | 模型输出 | 真回答 |
| `retrieval_only` | 没配 key / 模型报错 | `null` | **只给检索结果，绝不拿模板文本冒充 AI 回答** |
| `no_context` | 没检索到内容 | `null` | **不调模型**（幻觉的最大来源是"没资料也硬答"） |

为什么坚持这条：demo 时"看起来有答案"最省事，但面试一句"这段回答是模型生成的吗"就会崩。
宁可接口返回 `null` + `note` 说明原因。

## 4. 提示词约束
```
1. 只能用【资料】中的内容回答，不得引入资料之外的事实
2. 引用时在句末标注编号 [1]、[1][3]
3. 资料不足以回答时，直接回答"根据已有资料无法回答该问题"
4. 简体中文，简洁，不要复述资料原文超过 2 句
```
上下文按 `[i] 来源：文件名（第 n 块）\n正文` 拼装，编号与 `citations` 数组一一对应。

## 5. 流式（SSE）
先推 `event: citations`（来源清单），再逐段推 `data: {"delta": "..."}`，最后 `data: [DONE]`。
为什么先推 citations：检索先于生成，顺序天然如此；否则用户读到一半才知道要翻哪个文档。
**踩坑记录**：数据库 session 只能在进入生成器**之前**使用，生成器里只碰已取回的内存数据 ——
否则会出现"响应还在流、依赖注入的 session 已被关闭"的经典报错。

## 6. DoD
- [x] 没资料 → `no_context`，不调模型
- [x] 没 key → `retrieval_only`，`answer=null` 且带 `note`
- [x] 配了 key（测试用假模型）→ `mode=llm`，答案与 citations 同时返回
- [x] 提示词里真的带上检索资料（假模型里断言 `【资料】` 存在，防止"检索结果没进 prompt"这种静默 bug）
- [x] SSE 顺序：citations → 增量 → `[DONE]`；未配 key 时 503；无资料时 404
- [x] LLM 客户端用 `httpx.MockTransport` 覆盖：正常解析 / HTTP 错误 / 返回格式异常 / SSE 解析 / keepalive 容错

## 7. 会考问题
1. 为什么不用厂商 SDK？（→ 只用一个 POST，引 SDK 带来版本锁定；自己写还能用 MockTransport 全覆盖测试。什么条件下该换回 SDK：要接非 OpenAI 兼容协议时）
2. 模型答错但引用看着对，怎么发现？（→ 引用只保证"来源存在"，不保证"模型没用错"；要做引用一致性检查/人工抽样）
3. 怎么控制 token 成本？top-k、块大小、历史轮数分别怎么影响？
4. 流式下如何做错误处理？（→ 已经出字节就不能改状态码，只能用 `event: error` 事件告知）
5. 为什么 `answer=null` 不直接 503？（→ 检索结果本身有价值，降级可用优于整体不可用）

## 8. 实测（2026-10-11，本沙箱）
| 项 | 值 |
| --- | --- |
| 当前配置 | `llm_configured=false` → `mode=retrieval_only`（**真实模型回答尚未在本环境验证**） |
| 检索+引用组装耗时 | 服务端 `latency_ms = 2ms` |
| 流式 | 用假模型验证了 SSE 顺序；**真模型流式未验证** |

> UNKNOWN：真模型下的答案质量、引用正确率、首字延迟（TTFT）、token 成本 —— 需要 key 才能测。
> 拿到 key 后要补的数字：10 道题里答案有依据的比例、平均 TTFT、单次问答 token 消耗。
