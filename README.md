# 拾光 · 电商智能客服

基于 **Vue 3 + FastAPI + LangGraph + MCP** 的电商客服 Agent 工作台，提供商品咨询、平台规则检索、订单查询与个性化服务。

[项目仓库](https://github.com/GengHanLv/ShiGuang-Ecommerce-Agent) · [架构与功能](docs/architecture.md) · [开发与部署](docs/development.md) · [检索评测](backend/evals/README.md) · [GitHub 发布指南](docs/publishing.md)

## 功能概览

- **ReAct Agent**：模型按需调用工具，支持 SSE 流式回复、任务状态查看与中断恢复。
- **知识检索**：PDF / TXT / DOCX 导入，Milvus 向量检索与 BM25 混合召回，结合型号过滤、RRF 和可选 LLM 精排。
- **订单与记忆**：查询当前用户订单，保存聊天历史、用户偏好和长期事实。
- **联网工具**：公开网页搜索、商品页面读取和真实商品图片展示，通过 MCP 扩展服务。
- **咨询成果**：购物预算、参数对比、服务期限计算，以及用户私有 PDF 导出。
- **工作台**：登录、聊天、知识库、设置页面；管理员负责知识导入和 MCP 管理。

当前订单能力为只读查询，退款、改地址、取消订单和真人客服转接尚未对接真实业务系统。仓库附带模拟订单 SQL，不附带私有知识资料、模型权重或运行数据库。

## 项目结构

```text
ShiGuang-Ecommerce-Agent/
├── backend/
│   ├── app/
│   │   ├── agent/              # LangGraph 状态图、任务与工具回执
│   │   ├── api/                # 请求模型、依赖与路由
│   │   ├── core/               # 配置、模型客户端与日志
│   │   ├── infrastructure/     # MySQL、SQLite、Redis、Milvus、嵌入
│   │   ├── memory/             # 会话、偏好与长期记忆
│   │   ├── rag/                # 文档导入、召回、排序与证据检查
│   │   ├── security/           # 账户与 Cookie 会话认证
│   │   └── tools/              # 业务、联网、MCP 与 PDF 工具
│   ├── tests/                  # 后端测试
│   ├── evals/                  # 检索评测与记忆回归
│   ├── tools/start-local.ps1   # Windows 本地启动器
│   └── mcp.servers.example.json
├── frontend/                  # Vue 3 + TypeScript + Vite
│   ├── src/                   # 页面、组件、状态与 API
│   ├── public/
│   └── package-lock.json      # 提交锁文件，使用 npm ci 安装
├── docs/                      # 架构、开发与发布说明
├── .env.example               # 后端环境变量模板
├── docker-compose.yml         # MySQL 和 Redis，不包含 Milvus
├── init_db.sql                # 建表及模拟订单
├── pyproject.toml             # Python 包与 Ruff 配置
├── requirements.txt           # 后端运行依赖
├── requirements-dev.txt       # 开发依赖
├── start-local.bat            # Windows 启动入口
└── LICENSE
```

本地 `data/` 存放模型、知识资料、身份、历史、检查点、导出文件和日志；`volumes/` 存放 MySQL 数据，`Others/` 存放私人资料及备份。这些目录均不提交 Git。

## 快速启动

以下命令以 **Windows PowerShell** 为例，从仓库根目录执行。已有本地项目可跳过克隆。

### 1. 准备环境与依赖

需要 Python 3.11+、Node.js 20.19+（20.x）或 22.12+、可用的 Milvus 服务、本地 BGE-M3 模型，以及支持原生工具调用的 OpenAI 兼容模型 API。使用下方数据库启动方式还需要 Docker Compose。

```powershell
git clone https://github.com/GengHanLv/ShiGuang-Ecommerce-Agent.git
cd ShiGuang-Ecommerce-Agent
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
npm --prefix frontend ci
```

Linux / macOS 使用 `.venv/bin/python` 替换上述 Python 路径，并按后文手动启动服务；一键启动器仅适用于 Windows。

### 2. 配置环境

首次运行复制模板；已有 `.env` 时保留现有配置：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

编辑 `.env`，至少核对以下配置：

| 配置 | 用途 |
| --- | --- |
| `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`CHAT_MODEL` | 模型服务凭据、地址与模型名 |
| `BGE_M3_MODEL_PATH`、`EMBEDDING_DIM` | 完整本地 BGE-M3 模型目录；默认 1024 维 |
| `MYSQL_*` | 订单数据库；示例 Compose 使用本机 3307 端口、数据库 ecommerce |
| `REDIS_HOST`、`REDIS_PORT` | 示例 Compose 使用本机 6380 端口 |
| `MILVUS_HOST`、`MILVUS_PORT` | 单独准备的 Milvus 实例，默认端口 19530 |
| `AUTH_ADMIN_PASSWORD` | 可选初始管理员密码；留空则首次启动随机生成 |
| `RAG_RERANKER` | `llm` 使用模型精排；`rules` 使用规则与 RRF 排序 |
| `PDF_FONT_PATH` | 可选可嵌入中文 TrueType 字体路径 |

完整配置见 [.env.example](.env.example)。数据库示例密码仅供本地开发。相对模型路径以项目根目录为基准；模型权重需要自行准备。

### 3. 启动基础服务

```powershell
docker compose up -d mysql redis
docker compose ps
```

Compose **只提供 MySQL 与 Redis**。另行启动 Milvus，并确认模型目录已准备好。`init_db.sql` 只在 MySQL 数据目录首次初始化时执行；修改 SQL 不会自动更新已有数据库。

### 4. 启动应用

安装依赖、配置环境并启动基础服务后，Windows 可运行：

```powershell
.\start-local.bat
```

启动器启动前后端并打开浏览器，日志位于 `data/logs/startup/`。它不安装依赖、不启动 Docker；已有服务会先校验再尝试复用。可使用 `.\start-local.bat -NoBrowser` 不自动打开浏览器。

也可在两个终端分别启动：

```powershell
# 终端一：项目根目录
.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001
```

```powershell
# 终端二：项目根目录
npm --prefix frontend run dev
```

- 工作台：[http://127.0.0.1:5173](http://127.0.0.1:5173)
- API 文档：[http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs)
- 健康检查：[http://127.0.0.1:8001/health](http://127.0.0.1:8001/health)

前端默认通过 `/api` 代理访问后端 8001 端口。若修改后端端口，在运行前端前设置 `$env:API_PROXY_TARGET = "http://127.0.0.1:新端口"`。

### 5. 登录并导入知识

管理员默认用户名为 `admin`。未设置初始密码时，从本机 `data/auth/bootstrap-admin.json` 获取生成的密码。修改环境变量不会重置已存在的管理员。

默认管理员业务身份 `user123` 对应 SQL 中的模拟订单；注册用户拥有独立身份。在知识库页面上传自己的 PDF、TXT 或 DOCX，扫描 PDF 需先 OCR。首次检索加载模型可能较慢。

管理员可通过 API 文档调用 `POST /knowledge/migrate` 初始化或迁移结构化集合。迁移成功后切换映射、保留原集合；完整型号标量过滤需要 v2 集合，详见[架构说明](docs/architecture.md)。

## 开发与验证

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
.venv\Scripts\python.exe -m backend.evals.memory_regression
.venv\Scripts\python.exe -m ruff check backend/app backend/tests
npm --prefix frontend test
npm --prefix frontend run build
```

检索评测需要服务、知识库与人工标注数据，参见[评测说明](backend/evals/README.md)。API 列表、扩展入口、MCP 配置和持久化要求见[开发与部署说明](docs/development.md)。

## 常见问题

| 现象 | 检查方法 |
| --- | --- |
| 页面能打开但无法对话 | 检查模型凭据、工具调用支持与后端日志 |
| 知识上传或检索失败 | 检查 Milvus、BGE-M3 路径、向量维度及文档是否包含可提取文本 |
| 查不到演示订单 | 确认 SQL 已初始化、数据库配置匹配，且登录身份为 user123 |
| 前端提示 API 连接失败 | 检查后端端口与 Vite 代理，修改代理后重启前端 |
| 中文 PDF 字体异常 | 配置可嵌入的中文 TrueType 字体，重启后端后重新导出 |
| 新克隆后没有历史或知识 | 运行数据不在仓库中，需要重新导入或恢复自己的备份 |

`npm run build` 只生成前端静态文件，不会打包 Python 后端。部署时需独立运行后端、配置 `/api` 反向代理，并持久化数据库与必要的 `data/` 子目录。HTTPS 部署设置 `AUTH_COOKIE_SECURE=true`，配置实际跨域来源，并按需关闭公开注册。

## 项目来源与许可证

当前维护仓库：[GengHanLv/ShiGuang-Ecommerce-Agent](https://github.com/GengHanLv/ShiGuang-Ecommerce-Agent)。

基于原项目 [TT959/Ecommerce-Agent](https://github.com/TT959/Ecommerce-Agent) 演进，保留 [MIT 许可证及原版权声明](LICENSE)。设计参考 ReAct 与 LangGraph。
