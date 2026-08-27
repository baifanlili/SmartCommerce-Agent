# SmartCommerce-Agent

面向电商平台的企业级 Multi-Agent 智能购物能力平台。面向用户的 MVP 客户端将采用移动端优先的 Taro + React + TypeScript；核心能力可独立集成到其他 App、商城或企业应用。

当前版本为 `v0.1.0` 生产级 Agent 基线原型，包含：

- React + TypeScript + Vite 技术验证与 API 演示客户端
- FastAPI Agent API
- Supervisor → Product Agent → Recommend Agent 基础链路
- 本地商品样例数据和预算、品类筛选
- Redis 会话记忆基础设施
- 无需大模型密钥即可运行的 Mock 推荐引擎
- request_id/trace_id 请求链路标识、统一结构化错误和存活/就绪健康检查
- Docker 后端测试、Node 20 前端构建和 Mock API 压测基线
- Docker Compose 一键启动

当前阶段使用仓库内的小型样例数据，目的是让 Mock 回归、接口测试和 API 压测稳定可重复。开源商品/评价数据集不会在 `v0.1.0` 直接混入运行时，而是在 `v0.3.0` 的 Taro 用户 MVP、RAG 与长期记忆阶段正式接入。届时会先核验许可证和隐私风险，再固定数据快照，执行下载、清洗、去重、字段标准化、质量校验、脱敏和向量索引构建。原始数据和大体积索引不提交 Git，也不让生产环境直接依赖临时下载地址。

## 生产级架构路线

项目从第一版就按生产约束设计，但采用渐进式拆分：

```text
v0.1  模块化 FastAPI + Redis + Mock LLM
  ↓
v0.3  Taro 接入层 + 数据管道 + RAG + Python 长期记忆
  ↓
v0.4  LangGraph Supervisor + Intent + Planner + Router + Agent Registry
  ↓
v0.5  无状态 API 多副本 + Redis 外置状态 + Queue + Worker Pool
  ↓
v0.6  MCP Gateway + Java 用户/商品/库存/订单服务 + 高并发分布式基线
  ↓
v0.7  OpenTelemetry + Prometheus/Grafana + Evaluation + 管理员治理
  ↓
v0.8  限流熔断 + 自动扩容 + 故障演练 + 备份恢复 + 生产发布
  ↓
v1.0  完整 RBAC、租户隔离、SLO、灾备和生产运维闭环
```

API 服务不保存用户会话、记忆或任务状态，身份和数据按稳定的 `tenant_id`、`user_id`、`session_id` 关联。意图识别在代码和模块层面独立，但初期作为 Supervisor 内部节点运行；只有出现独立扩容、独立模型、故障隔离或独立发布需求时，才拆成独立服务。交易、库存和支付等强一致能力由 Java 服务最终授权和执行，Python Agent 通过受控 MCP 工具调用。`v0.6.0` 起 Java 业务层同步按高并发分布式基线建设：无状态多副本、网关负载均衡、服务发现、Redis 热点缓存、数据库连接池与读写边界、消息队列、库存并发控制、交易幂等和独立压测；`v0.8.0` 再补自动扩容、灾备和完整故障演练。

### 主 Agent 部署原则

主 Agent 在逻辑上是一个 Supervisor，统一负责意图识别、任务规划、Agent 路由和结果汇总；在物理部署上不是唯一实例，而是 `v0.5.0` 起作为无状态 Agent Orchestrator 多副本运行：

```text
客户端 → API Gateway → Agent Orchestrator-1/2/3
                         ↓
                 Redis / PostgreSQL
                 会话、工作流、幂等键
                         ↓
                  Queue + Worker Pool
                         ↓
                    MCP Gateway
                         ↓
              Java Spring Cloud 业务服务
```

主 Agent 进程不得独占保存会话、工作流、长期记忆或任务状态。LangGraph Checkpoint、会话和任务状态必须外置，任意副本都能处理同一用户的后续请求；同一会话的并发请求需要通过会话版本号、队列化或分布式锁控制顺序。Product、Review、Recommend 等子 Agent 初期作为同一 Python 服务中的模块，不为了名称强行拆成微服务；长耗时或资源密集型任务进入独立 Worker Pool，并按 Worker 类型分别扩容。只有当某个 Agent 需要独立扩容、独立模型、故障隔离、独立发布或明显不同的资源池时，才拆为独立服务。

### 必须提前锁定的边界

- Java 负责用户、商品、购物车、库存、订单和支付状态；Python 负责会话历史、长期记忆、用户偏好、画像和 Agent 运行上下文。
- Redis 只承载缓存、短期状态、幂等键和分布式协调数据；订单和库存最终事实必须落在 MySQL 等持久化存储中。
- 各 Java 服务拥有自己的数据表和写权限，即使初期共用一个 MySQL 实例，也不能跨服务随意读写业务表。
- 所有公开接口使用 `/api/v1` 版本化，并统一错误码、分页、`request_id`、`trace_id` 和 `Idempotency-Key` 约定。
- 订单使用状态机、库存预占或原子扣减、Outbox 事件表和幂等消费者；消息队列采用至少一次投递，依靠重试、死信和补偿处理最终一致性。
- 数据库变更使用 Flyway 或 Liquibase，采用“先扩展、再迁移、最后删除”的兼容发布策略。
- 商品结构化检索预留 OpenSearch/Elasticsearch 边界，数据集、处理快照和索引备份预留 S3、OSS 或 MinIO 对象存储边界。

Spring Cloud 业务层建议统一使用 Spring Cloud Gateway、Nacos、OpenFeign、Spring Cloud LoadBalancer 和 Sentinel。Gateway 负责入口路由、鉴权前置和基础限流，Nacos 负责服务发现与配置，Feign 负责服务调用，LoadBalancer 负责实例均衡，Sentinel 负责限流、熔断、隔离和降级；不在没有实际需求时同时引入多套功能重叠的熔断组件。

## 版本目标摘要

| 版本 | 目标 | 必须交付 |
|---|---|---|
| `v0.1.0` | Agent 工程基础 | FastAPI、Mock LLM、商品检索、Redis 会话、Compose、基础测试 |
| `v0.2.0` | 稳定协议和模型接入 | LLM Provider、结构化输出、统一错误码、身份协议、超时重试和降级 |
| `v0.3.0` | 用户 MVP 和知识库 | Taro、H5、商品详情、评价检索、开源数据集、RAG 和长期记忆 |
| `v0.4.0` | Agent 编排 | LangGraph、Supervisor、Intent、Planner、Router、Registry 和工具白名单 |
| `v0.5.0` | Agent 分布式运行 | API 多副本、Redis 外置状态、队列、Worker、异步任务、幂等和失败恢复 |
| `v0.6.0` | Spring Cloud 交易闭环 | Gateway、Nacos、用户/商品/库存/购物车/订单、MCP、MySQL、Redis 和 MQ |
| `v0.7.0` | 高并发与可观测 | OpenTelemetry、Prometheus/Grafana、压测、容量模型和一致性验证 |
| `v0.8.0` | 高可用和 CI/CD | 限流、熔断、自动扩容、备份恢复、灰度发布、回滚和故障演练 |
| `v1.0.0` | 生产治理闭环 | RBAC、租户隔离、审计、密钥治理、SLO、灾备、安全扫描和运维文档 |

`v0.6.0` 的 Java 服务不追求一次拆成大量微服务，首批边界为 `gateway-service`、`user-service`、`product-service`、`inventory-service`、`order-service` 和 `mcp-gateway`；购物车可作为独立模块或服务，支付先定义 `PaymentProvider` 和 Mock 实现。商品最终数据放 MySQL，热点查询放 Redis，结构化搜索预留 OpenSearch/Elasticsearch，商品知识和评价语义检索使用 Milvus 或等价向量库，数据集与索引备份使用 S3、OSS 或 MinIO。

普通商品推荐、商品详情和库存查询走同步接口；大规模商品对比、长文评价分析、数据集导入、向量构建和管理员评估走异步任务。动态 Agent 只能配置 `role`、`goal`、`prompt`、`allowed_tools`、`timeout`、`retry_policy` 和 `output_schema`，禁止运行时生成或执行 Python、Java、SQL、Shell 代码。

生产可靠性路线还包括就绪/存活探针分离、优雅下线、连接池和线程池上限、Redis Sentinel/Cluster、MySQL 主从与备份恢复、Kafka 消费组与积压监控、Testcontainers 集成测试、Python/MCP/Java 契约测试、k6/JMeter 压测、Prompt Injection 防护、敏感信息脱敏、API Key 加密轮换和管理员审计。

## 数据集接入路线

| 阶段 | 数据策略 | 目的 |
|---|---|---|
| `v0.1.0` | 小型样例商品数据，版本随代码管理 | 启动、回归和 Mock 压测可重复 |
| `v0.2.0` | 先稳定模型协议，不引入大规模数据依赖 | 避免模型适配和数据管道同时变动 |
| `v0.3.0` | 接入许可证明确的开源商品/评价数据集 | 建立可重建的 RAG 商品知识库 |
| `v0.7.0` | 将固定数据集纳入评估集和质量门禁 | 衡量意图、召回、引用和任务成功率 |
| `v0.8.0` | 对数据快照、结构化库和向量索引做备份恢复 | 验证生产数据可靠性 |

正式接入时，数据清单至少记录来源、许可证、版本或 Commit、下载时间、字段映射、清洗规则、脱敏结果和校验摘要。数据管道应支持失败重跑和从同一快照重建索引；生产使用经过审核的内部快照，而不是运行时在线下载。

面向用户的 MVP 客户端采用 Taro + React + TypeScript，支持 H5 以及多个小程序平台的跨端构建目标。当前仓库中的 Vite Web 端保留为技术验证、接口联调和桌面演示工具。当前路线建设的是通用跨端能力和构建适配，不把某个具体小程序平台的主体认证、经营资质、支付签约或正式上线运营纳入研发范围。核心 Agent 能力通过 API、SSE 或 WebSocket 提供给不同宿主应用。

## 一键启动

环境要求：安装并启动 Docker Desktop。项目本地构建、测试和运行时验收统一使用 Docker 提供的 Python 3.12、Node 20 和 Redis 环境；不要求本机额外安装 Python 或 Node.js。

在项目根目录执行：

```powershell
docker compose up --build
```

启动后访问：

- 前端工作台：http://localhost:3000
- 后端接口文档：http://localhost:8000/docs
- 后端健康检查：http://localhost:8000/health

首次启动会构建前后端镜像并下载 Redis 镜像，可能需要几分钟。

## 健康检查与错误约定

健康检查区分存活与就绪：

- `/health/live`：进程存活检查，不依赖 Redis。
- `/health/ready`：就绪检查，包含 Redis 状态；Redis 不可用时返回 `503` 和 `degraded`。
- `/health`：就绪检查的兼容别名。

所有响应都包含 `X-Request-ID` 和 `X-Trace-ID` 响应头；未携带请求头时自动生成，并同步写入结构化日志。错误响应统一为：

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "请求参数校验失败",
    "request_id": "…",
    "trace_id": "…",
    "details": []
  }
}
```

常用错误码包括 `VALIDATION_ERROR`、`BAD_REQUEST`、`NOT_FOUND`、`TOO_MANY_REQUESTS` 和 `INTERNAL_ERROR`，内部异常不会向客户端泄露细节。

## 部署路线

本地 Compose 是开发和技术验证入口，不等于最终生产拓扑。后续部署按同一份不可变镜像逐级晋级：`main` 合并后构建一次并使用 Commit SHA 或版本号标记，自动部署 `dev`，测试通过后人工批准进入 `uat`，验收通过后人工批准进入 `prod`。环境差异通过环境变量和 Secret 注入，数据库、Redis、消息队列、向量库和模型密钥不写入镜像。

| 环境 | 方式 | 重点 |
|---|---|---|
| 本地 | Docker Compose | 一键启动、接口联调、Mock 回归和基础压测 |
| `dev` | 同一镜像自动部署 | 集成验证、数据管道和观测联调 |
| `uat` | 同一镜像人工批准晋级 | 业务验收、压测和故障演练 |
| `prod` | 同一镜像人工批准发布 | 灰度/滚动发布、健康检查、告警和回滚 |

`v0.5.0` 起增加 Python Agent API 多副本、负载均衡、Worker Pool 和队列堆积验证；`v0.6.0` 起对 Java 商品、库存、订单链路做独立高并发压测和 Agent → MCP → Java 端到端混合压测；`v0.8.0` 起根据压测结果选择 Kubernetes 或云厂商容器平台，并补齐自动扩容、备份恢复、故障注入和容量模型。

## 常用命令

后台启动：

```powershell
docker compose up --build -d
```

查看日志：

```powershell
docker compose logs -f
```

查看服务状态：

```powershell
docker compose ps
```

停止服务：

```powershell
docker compose down
```

停止服务并清理本地 Redis 开发数据：

```powershell
docker compose down -v
```

## 环境变量

复制 `.env.example` 为 `.env`，可以配置端口和后续真实模型参数：

```powershell
Copy-Item .env.example .env
```

默认 `.env.example` 使用不需要密钥的 Mock 模式。本机接入 DeepSeek 时，配置 `LLM_PROVIDER=deepseek`、`LLM_API_KEY` 和 `LLM_MODEL=deepseekflash`。协议默认使用 Chat Completions；DeepSeek 的 Responses API 可以通过 `LLM_API_MODE=responses` 选择。API 请求失败会按配置重试，仍失败时自动回退到 Mock，避免购物演示整体不可用。密钥只放在本机 `.env`，不要提交到 Git。

模型配置既可以通过环境变量注入，也可以在管理员配置台中运行期调整。配置台支持 Mock/DeepSeek、Chat Completions/Responses、模型名称、Base URL、超时、重试次数、连接测试、保存草稿和启用配置；API Key 只接收和使用，读取时仅返回脱敏结果。管理员接口需要 `X-Admin-Token`，由 `ADMIN_TOKEN` 注入。当前配置草稿和启用状态仅保存在单个 API 进程内，尚未接入加密持久化、管理员账号体系、审计日志和多副本同步，因此只适合作为 v0.2 的开发验证能力。

## 本地开发

后端需要 Python 3.12：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[test]"
uvicorn smart_commerce.main:app --reload --app-dir src
```

前端需要 Node.js：

```powershell
cd frontend
npm install
npm run dev
```

本地前端开发服务器会把 `/api` 请求代理到 `http://localhost:8000`。

## 测试

后端测试（Python 3.12 测试容器）：

```powershell
docker compose --profile test run --rm api-test
```

前端构建检查（Node 20 构建容器）：

```powershell
docker compose build web
```

Compose 配置检查：

```powershell
docker compose config
```

Mock API 最小压测（10 并发、200 请求，基线写入 `benchmark/results/`）：

```powershell
docker compose --profile bench run --rm api-bench
```

完整的 `v0.1.0` 本地验收：

```powershell
docker compose up --build -d
docker compose --profile test run --rm api-test
docker compose build web
docker compose --profile bench run --rm api-bench
docker compose ps
```

验收结束后停止服务：

```powershell
docker compose down
```

CI 也会执行后端测试、前端构建、Compose 配置检查和 API/Web 镜像构建。生产镜像不包含测试依赖，`api-test` 只用于本地和 CI 验证。

压测按 API 基准、Agent 流程、记忆读写、异步任务、依赖故障和真实模型六层推进。每次记录并发数、持续时间、成功率、吞吐量、P50/P95/P99、超时率、依赖错误率、Token 消耗和资源使用率；具体 SLO 以实测基线为依据。

## 项目资料

本机个人设计文档和开发进度位于 `docs-private/`，该目录以及根目录 `AGENTS.md` 通过 `.git/info/exclude` 保持本地私有，不上传 GitHub。

公开版本规划见 [`ROADMAP.md`](ROADMAP.md)，其中记录各版本的目标、核心功能和验收边界。
