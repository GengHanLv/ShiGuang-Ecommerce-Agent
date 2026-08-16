# graph.py 状态流程图

对应文件：`src/graph.py`  
主链路：`recall_memory → classify → tools → generate → END`

## 图 1：主状态图

```mermaid
flowchart TD
    Start([用户请求进入]) --> Recall[recall_memory<br/>长期记忆向量检索]
    Recall --> Classify[classify<br/>意图分类 + 抽订单号]
    Classify --> Tools[tools<br/>按意图并行调工具]
    Tools --> Generate[generate<br/>生成回复]
    Generate --> End([结束 END])
```

## 图 2：classify

```mermaid
flowchart TD
    A[取最新用户话 msg] --> B[extract_order_id]
    B --> D{偏好陈述/询问<br/>且非查单/转人工?}
    D -->|是| E[chitchat]
    D -->|否| C[_rule_intents]
    C --> F{规则高置信?}
    F -->|是| G[_post_gate_intents]
    F -->|否| H[LLM 白名单补全]
    H --> I[与规则结果合并]
    I --> G
    G --> J[最终 intents / order_id]
    E --> J
```

## 图 3：tools / generate

```mermaid
flowchart TD
    T{intents} --> T1[order_query → query_order]
    T --> T2[knowledge → FAQ + 商品检索]
    T --> T3[transfer_human → 占位文案]
    T1 --> GATHER[asyncio.gather]
    T2 --> GATHER
    T3 --> GATHER
    GATHER --> GEN{仅转人工?}
    GEN -->|是| FIX[固定转接话术]
    GEN -->|否| LLM[工具结果 + 记忆拼进 Prompt]
    LLM --> OUT[assistant 回复]
    FIX --> OUT
```

```text
请求
  └─ recall_memory：按 user_id 检索长期记忆
       └─ classify：规则高置信则直接出门禁；否则 LLM 白名单补全后再门禁
            └─ tools：并行查订单 / FAQ·商品 / 转人工
                 └─ generate：拼 context 生成回复
                      └─ END（main 侧抽取本轮记忆写入）
```

| 字段 | 谁写入 / 使用 |
|------|----------------|
| `messages` | 入口带入；`generate` 追加 assistant |
| `memory_hits` | `recall_memory` 写出 |
| `intents` / `order_id` | `classify` 写出 |
| `tool_results` | `tools` 写出 |
| `user_id` / `session_id` | 入口带入 |
