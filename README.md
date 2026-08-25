# SmartCommerce-Agent

企业级 Multi-Agent 智能购物系统，当前处于第一阶段 Agent MVP 开发中。

当前版本包含：

- React + TypeScript 智能购物工作台
- FastAPI Agent API
- Supervisor → Product Agent → Recommend Agent 基础链路
- 本地商品样例数据和预算、品类筛选
- Redis 会话记忆基础设施
- 无需大模型密钥即可运行的 Mock 推荐引擎
- Docker Compose 一键启动

## 一键启动

环境要求：安装并启动 Docker Desktop。

在项目根目录执行：

```powershell
docker compose up --build
```

启动后访问：

- 前端工作台：http://localhost:3000
- 后端接口文档：http://localhost:8000/docs
- 后端健康检查：http://localhost:8000/health

首次启动会构建前后端镜像并下载 Redis 镜像，可能需要几分钟。

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

当前 `LLM_PROVIDER=mock` 时不需要填写模型密钥。后续接入 Qwen、DeepSeek 或 GPT 时，再配置 `LLM_PROVIDER`、`LLM_API_KEY` 和 `LLM_MODEL`。

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

后端测试：

```powershell
pytest
```

前端构建检查：

```powershell
cd frontend
npm run build
```

Compose 配置检查：

```powershell
docker compose config
```

## 项目资料

本机个人设计文档和开发进度位于 `docs-private/`，该目录以及根目录 `AGENTS.md` 通过 `.git/info/exclude` 保持本地私有，不上传 GitHub。
