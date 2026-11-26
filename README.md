# A股智能分析平台

基于23个分析模块的A股智能投资决策辅助平台，集成AI大模型能力，提供全方位的市场分析、个股诊断和智能交易功能。

## 项目结构

```
gp/
├── backend/                 # 后端 FastAPI 应用
│   ├── app/
│   │   ├── api/            # API路由 (20+ endpoints)
│   │   │   ├── market.py   # 市场看板
│   │   │   ├── stock.py    # 个股诊断
│   │   │   ├── strategy.py # 智能选股
│   │   │   ├── nlp.py      # AI对话分析
│   │   │   ├── chat.py     # AI助手聊天
│   │   │   ├── ai_stock_picks.py  # AI股票推荐
│   │   │   ├── daily_reports.py   # AI每日复盘
│   │   │   ├── sector_analysis.py # 板块分析
│   │   │   ├── sim_trading.py     # 模拟交易
│   │   │   └── ...
│   │   ├── core/           # 核心配置和数据源
│   │   ├── services/       # 业务服务层
│   │   ├── models/         # SQLAlchemy数据模型
│   │   ├── schemas/        # Pydantic数据模型
│   │   └── main.py         # 应用入口
│   ├── tests/              # 测试文件
│   └── requirements.txt    # Python依赖
├── frontend/               # 前端 Vue3 应用
│   ├── src/
│   │   ├── api/            # API接口封装
│   │   ├── views/          # 页面组件 (15+ pages)
│   │   ├── components/     # 可复用组件
│   │   ├── composables/    # Vue组合式函数
│   │   ├── stores/         # Pinia状态管理
│   │   ├── router/         # 路由配置
│   │   └── main.js         # 入口文件
│   ├── package.json        # Node依赖
│   └── vite.config.js      # Vite配置
├── skills/                 # 23个分析模块
│   ├── a-share-analysis-toolkit/    # A股分析工具包
│   ├── a-share-architecture/        # 架构文档
│   ├── a-share-daily-report/        # AI每日复盘
│   ├── a-share-data-cache/          # 数据缓存
│   ├── a-share-oversold-rebound-strategy/  # 超跌反弹策略
│   ├── a-share-visualization/       # 数据可视化
│   ├── capital-flow/                # 资金流向分析
│   ├── dragon-list/                 # 龙虎榜分析
│   ├── kline-patterns/              # K线形态识别
│   ├── market-sentiment/            # 市场情绪分析
│   ├── ml-stock-picker/             # ML选股模型
│   ├── multi-factor/                # 多因子模型
│   ├── multi-strategy/              # 多策略组合
│   ├── nlp-analyzer/                # NLP分析器
│   ├── sector-rotation/             # 板块轮动分析
│   ├── strategy-combo/              # 策略组合
│   └── tech-indicators/             # 技术指标计算
├── data/                     # 数据库和缓存数据
├── news_data/                # 新闻资讯数据
├── sentiment_data/           # 情绪分析数据
├── 一键启动.bat              # Windows一键启动
├── start.ps1                 # PowerShell启动脚本
├── start-prod.ps1            # 生产环境启动
├── stop.bat / stop.ps1       # 停止服务脚本
└── README.md                 # 项目说明
```

## 快速开始

### 本地开发

```powershell
# 1. 配置环境变量（可选）
# 复制 backend/.env.example 为 backend/.env，设置 SECRET_KEY 等密钥

# 2. 一键启动
.\一键启动.bat

# 3. 访问应用
# 前端: http://localhost:5173
# 后端API文档: http://localhost:5174/docs
```

### 手动启动

```powershell
# 后端
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 5174

# 前端 (新终端)
cd frontend
npm install
npm run dev
```

### 生产启动（多worker，支持50-100并发）

```powershell
.\start-prod.ps1
# 或
.\start-prod.bat
```

## 功能模块

| 模块 | 功能描述 | 状态 |
|------|----------|------|
| 🔐 用户系统 | 注册、登录、JWT认证、管理员权限 | ✅ |
| 📊 市场看板 | 大盘指数、情绪评分、板块排行、涨跌统计、热点追踪 | ✅ |
| 🔍 个股诊断 | 技术指标、K线形态、资金流向、综合评估报告 | ✅ |
| 🎯 智能选股 | 多因子模型、ML预测、策略信号组合 | ✅ |
| 🤖 AI股票推荐 | 基于大模型的个性化股票推荐 | ✅ |
| 📝 AI每日复盘 | 自动生成每日市场总结和投资建议 | ✅ |
| 🐉 龙虎榜 | 当日数据、游资追踪、机构动向分析 | ✅ |
| 🏭 板块分析 | 行业轮动信号、产业链分析、板块对比 | ✅ |
| ⭐ 自选股 | 个性化股票池、策略生成、实时监控 | ✅ |
| 💰 AI模拟交易 | AI驱动的交易引擎、风险控制、收益统计 | ✅ |
| 📰 资讯研报 | 新闻聚合、研报解析、智能搜索 | ✅ |
| 💬 AI助手 | 自然语言对话、智能问答、SSE流式响应 | ✅ |
| ⚙️ 系统管理 | 用户管理、配额控制、LLM配置、系统监控 | ✅ |

## 技术架构

### 后端技术栈
- **框架**: Python 3.11 + FastAPI + Uvicorn
- **ORM**: SQLAlchemy 2.0 + Alembic迁移
- **认证**: JWT (python-jose) + BCrypt密码加密
- **缓存**: Redis + 本地内存缓存
- **限流**: slowapi速率限制
- **数据源**: pytdx + 东方财富直连 + 同花顺 + 腾讯财经（全部免费公开接口，无需 API Key）
- **AI集成**: OpenAI兼容接口 + SSE流式推送

### 前端技术栈
- **框架**: Vue 3 + Vite + Composition API
- **UI库**: Element Plus + ECharts图表
- **状态管理**: Pinia
- **HTTP客户端**: Axios
- **工具库**: lodash, dayjs, vueuse

### 数据分析模块
- **机器学习**: LightGBM + XGBoost + scikit-learn
- **技术指标**: TA-Lib风格指标计算
- **可视化**: matplotlib + plotly + mplfinance

## API文档

启动后端后访问 Swagger UI: http://localhost:5174/docs

主要API端点：
- `GET /api/market/dashboard` - 市场看板数据
- `POST /api/stock/diagnose` - 个股诊断分析
- `POST /api/strategy/pick` - 智能选股
- `POST /api/chat/message` - AI对话 (SSE流式)
- `GET /api/ai-stock-picks` - AI推荐列表
- `GET /api/daily-reports` - 每日复盘报告

## 环境变量配置

在 `backend/.env` 中配置：

```env
# JWT签名密钥 (必需，生成: python -c "import secrets; print(secrets.token_urlsafe(48))")
SECRET_KEY=replace-me-with-a-random-48-char-string

# LLM配置
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your_llm_key
LLM_MODEL=gpt-4

# Redis缓存 (可选)
REDIS_URL=redis://localhost:6379/0

# 数据库
DATABASE_URL=sqlite:///./data/app.db
```

## 开发指南

### 添加新的分析模块
1. 在 `skills/` 下创建新目录
2. 编写 `SKILL.md` 说明文档
3. 实现核心逻辑 Python 文件
4. 在 `backend/app/core/skill_orchestrator.py` 中注册

### 添加新的API端点
1. 在 `backend/app/api/` 下创建路由文件
2. 定义 Pydantic schema 在 `schemas/`
3. 实现业务逻辑在 `services/`
4. 在 `main.py` 中注册路由

## 免责声明

⚠️ **本平台仅供学习和研究使用，不构成任何投资建议。**

股市有风险，投资需谨慎。本平台提供的分析结果仅供参考，不应作为唯一投资决策依据。使用者应自行承担投资风险。
