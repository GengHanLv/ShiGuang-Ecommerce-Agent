# 电商智能客服 Agent

## 简介

面向电商售后场景的智能客服系统：基于 LangGraph 做多意图路由与工具并行，基于 Milvus 做 FAQ/商品知识检索与用户长期记忆，基于 MySQL 做订单实时查询，基于 Redis 做会话持久化与 RAG 缓存，对外提供 FastAPI（JSON / SSE 流式）接口。

## 功能特性

- 多意图并行：单轮支持「查订单 + 问退货政策」；`asyncio.gather` 并行调用工具
- 意图识别：规则高置信命中；未命中或部分命中时由 LLM 在白名单内补全，再经后置门禁检验
- RAG 知识问答：Milvus 稠密/轻量混合检索 + 阈值过滤 + Prompt 约束（未写明的规格/功能禁止编造）
- 长期记忆：按 `user_id` 写入 preference/fact；同主题替换、可更新/删除；检索后按情境注入 Prompt
- 订单查询：异步 SQLAlchemy 参数化查库，支持订单号槽位抽取
- 人工转接：关键词规则识别 + 固定话术，避免模型误转
- 会话记忆：Redis 持久化（TTL + 最近 N 轮截断），不可用时内存降级
- 流式输出：`/chat/stream` SSE 推送 token；主链路异常时降级话术引导转人工
- 知识入库：`/upload` 支持 PDF / TXT / DOCX 解析、分块、向量化写入 Milvus
- 离线评测：意图多标签命中率 / F1 + LLM-as-Judge；另有记忆规则回归脚本

## 技术栈

| 层级 | 技术 |
|------|------|
| Agent 编排 | LangGraph / LangChain / OpenAI 兼容 API |
| 对话模型 | 默认 `gpt-4o-mini`（`CHAT_MODEL`） |
| 向量 | 本地 BGE-M3（1024 维） |
| API | FastAPI + Uvicorn |
| 向量库 | Milvus |
| 业务库 | MySQL 8 + SQLAlchemy（async） |
| 缓存/会话 | Redis |
| 日志 | loguru |

## 系统架构

```text
Client
  │  X-API-Key
  ▼
FastAPI (/chat, /chat/stream, /upload, /health)
  │
  ▼
LangGraph: recall_memory → classify → tools → generate
  │              ├─ Milvus: user_memory（按 user_id 长期记忆）
  │              ├─ MySQL: query_order
  │              ├─ Milvus: FAQ / product RAG (+ Redis cache)
  │              └─ transfer: rule + fixed reply
  ▼
Redis: session history (TTL, last N turns)
  + 回复后抽取记忆写回 user_memory（失败不影响主回复）
```

意图分类（`classify`）：

```text
规则词典 + 偏好规则
  ├─ 高置信命中 → 后置门禁 → 最终意图
  └─ 未命中 / 部分命中 → LLM（仅白名单意图）→ 后置门禁 → 最终意图
```

## 目录结构

```text
├── docker-compose.yml   # MySQL + Redis（MySQL 映射 3307）
├── init_db.sql          # 演示订单数据
├── .env.example         # 环境变量模板
├── .gitignore
├── requirements.txt
├── logger.py
└── src/
    ├── main.py                   # FastAPI 入口（鉴权 / 降级）
    ├── graph.py                  # LangGraph 状态图
    ├── memory_signals.py         # 意图/偏好/查单信号词与判定
    ├── tools.py                  # 订单查询
    ├── rag_tool.py               # RAG 检索 + 缓存
    ├── redis_client.py           # Redis 连接（会话/RAG 共用）
    ├── memory.py                 # 短期会话管理
    ├── long_term_memory.py       # 用户长期记忆（检索/抽取/同主题替换）
    ├── memory_regression_cases.py # 记忆/意图规则回归
    ├── document_loader.py        # 文档入库
    ├── insert_data.py            # 初始化 FAQ/商品向量
    ├── embeddings.py             # 本地 BGE-M3 向量化
    ├── init_milvus.py            # Milvus 封装
    ├── evaluation.py             # 离线评测
    ├── debug_rag.py              # RAG 检索冒烟
    ├── graph_flow.md             # 状态图流程说明
    ├── database.py
    └── config.py
```

## 运行步骤

### 1. 环境要求

- Python 3.10+
- Docker（用于 MySQL / Redis；也可改 `.env` 使用本机 MySQL）
- 独立运行的 Milvus（默认 `127.0.0.1:19530`；本仓库 compose 未包含 Milvus）
- OpenAI 兼容 API Key
- 本地 BGE-M3 模型路径（`BGE_M3_MODEL_PATH`）

### 2. 安装依赖

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

macOS / Linux：

```bash
source venv/bin/activate
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，至少填写：

- `OPENAI_API_KEY` / `OPENAI_BASE_URL`
- `CHAT_MODEL`（可选，默认 `gpt-4o-mini`）
- `BGE_M3_MODEL_PATH`（本地模型目录，维度 `EMBEDDING_DIM=1024`）
- `MYSQL_PORT=3307`（与 `docker-compose.yml` 端口映射一致；本机 MySQL 常用 `3306`）
- `API_KEY`（调用接口时的 `X-API-Key`）

### 4. 启动基础设施

```bash
docker compose up -d
```

启动后：

- MySQL：`localhost:3307`（库名 `ecommerce`，演示用户 `user123`，compose 默认密码见 `docker-compose.yml`）
- Redis：`localhost:6379`

若容器名冲突：

```bash
docker start ecommerce-mysql ecommerce-redis
```

Milvus 需本机 `19530` 端口可用。

### 5. 初始化知识库

对话模型默认 `gpt-4o-mini`；向量使用本地 **BGE-M3**

```bash
cd src
python insert_data.py --reset
```

首次或空库可直接 `python insert_data.py`。

检索冒烟：

```bash
python debug_rag.py
```

### 6. 启动 API

```bash
cd src
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

- Swagger：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/health

## API 说明

请求头（`/health` 除外）：

```http
X-API-Key: <你的 API_KEY>
```

鉴权失败返回 **401**。`/chat`、`/chat/stream` 主链路异常时返回降级话术（引导稍后重试或转人工）；长期记忆写入失败不影响主回复。

### POST /chat

```json
{
  "user_id": "user123",
  "message": "订单号1到哪了？",
  "session_id": "demo-001"
}
```

返回字段：`reply`、`session_id`、`intents`、`memory_hits`。

### POST /chat/stream

SSE 流式输出，事件类型：`token` / `done` / `error`。

### POST /upload

表单字段：

- `file`：PDF / TXT / DOCX
- `collection`：`faq` 或 `product_knowledge`

## 长期记忆（用户级 RAG）

- 集合：`user_memory`（按 `user_id` 隔离）
- 类型：主要写入 `preference` / `fact`
- 流程：每轮先向量检索；有命中且非「正在陈述新偏好/删改」时注入 Prompt，结合订单/FAQ 情境化回答
- 写入：回复后抽取；同主题（如收货时段 / 电话通知 / 快递公司）变更时先删旧再写新；支持取消类删除
- 跨 `session_id` 仍可按同一 `user_id` 召回；订单状态仍以 MySQL 为准
- 记忆在**本轮回复之后**写入，验证请下一轮再问

## 推荐测试用例

| 场景 | message | 期望 |
|------|---------|------|
| FAQ | 怎么退货？ | intents 含 `knowledge` |
| 订单 | 查一下我的订单 | 返回 `user123` 订单状态 |
| 订单号 | 订单号1到哪了？ | `order_query`，非转人工 |
| 改收货信息 | 刚下单，收货手机号填错了，能换绑吗 | `order_query`，查单后说明 |
| 多意图 | 我有个订单要退款 | `order_query` + `knowledge` |
| 转人工 | 我要转人工 | 固定转接话术 |
| 偏好写入 | 记住我以后都晚上收货 | 确认偏好；日志有长期记忆写入 |
| 偏好并存 | 再发「快递到了请打电话通知我」 | 时段与电话偏好并存 |
| 情境用记忆 | 什么时候能收到我的订单？ | 订单事实 + 相关偏好备注 |
| 同主题更新 | 以后改成白天收货 | 替换收货时段，不误删电话偏好 |
| 负例 | 以后快递到了打电话，防止漏看订单信息 | 记偏好，**不**误查单 |
| 知识防幻觉 | 新品手机支持无线充电吗？（资料未写） | 说明无法确认，不编造「不支持」 |

## 离线评测与回归

规则回归（不依赖 LLM/Milvus）：

```bash
cd src
python memory_regression_cases.py
```

意图 + 回答质量：

```bash
cd src
python evaluation.py
```

端到端回答质量（真跑 Agent，较慢）：

```bash
python -c "import asyncio; from evaluation import evaluate_answer_quality; asyncio.run(evaluate_answer_quality(use_agent=True))"
```

输出意图子集命中率、平均 F1，以及 LLM-as-Judge 分数（`use_agent=False` 为参考答案冒烟，`True` 为真实 Agent）。
