# Polymarket 自动化交易系统

基于 Python 的 Polymarket 预测市场自动化交易系统，采用 DDD 分层架构设计。

## 技术栈

- **Python 3.11+** - 开发语言
- **web3.py** - 区块链交互
- **httpx** - 异步 HTTP 客户端
- **pydantic** - 数据验证
- **loguru** - 结构化日志
- **typer** - CLI 框架
- **rich** - 终端美化

## 项目结构

```
polymarket-trader/
├── src/
│   ├── domain/          # 领域层 - 实体、值对象、领域事件
│   │   ├── entities.py      # Market, Order, Position
│   │   ├── value_objects.py # Price, OrderBook
│   │   ├── events.py        # 领域事件
│   │   └── enums.py         # 枚举类型
│   ├── application/     # 应用服务层 - 业务逻辑编排
│   │   ├── trading_service.py
│   │   └── risk_service.py
│   ├── infrastructure/  # 基础设施层 - 技术实现
│   │   ├── blockchain_client.py
│   │   └── polymarket_client.py
│   └── adapter/         # 接口适配层
│       └── cli.py
├── tests/               # 测试
│   ├── unit/
│   └── integration/
├── config/              # 配置文件
├── docs/                # 文档
└── pyproject.toml       # 项目配置
```

## 快速开始

### 1. 安装依赖

```bash
cd polymarket-trader
pip install -e ".[dev]"
```

### 2. 配置环境变量

```bash
cp config/.env.example .env
# 编辑 .env 文件，添加你的配置
```

### 3. 运行 CLI

```bash
# 查看帮助
pm-trader --help

# 连接钱包
pm-trader connect --key 0x...

# 查看市场列表
pm-trader markets

# 查看余额
pm-trader balance

# 创建订单
pm-trader order <market_id> buy_yes 100 --price 0.55
```

## 风控模块

已实现的风控规则：

| 规则 | 说明 | 动作 |
|------|------|------|
| PositionLimit | 单笔仓位 ≤10%，最大持仓 5 | REJECT |
| Liquidity | 市场流动性 ≥10k USD | REJECT |
| TradingHours | UTC 06:00-22:00 | REJECT |
| StopLoss | 单笔止损 -2% | CLOSE_POSITION |
| DailyLossLimit | 日亏损 -3% | PAUSE(24h) |
| CircuitBreaker | 5分钟波动 >20% | PAUSE(30min) |

## 测试

```bash
# 运行所有测试
pytest

# 带覆盖率
pytest --cov=src --cov-report=html

# 特定测试文件
pytest tests/unit/test_domain.py -v
```

## 核心实体

### Market (市场)
- 市场基本信息 (ID, 标题, 类别)
- 价格信息 (Yes/No 价格)
- 订单簿深度
- 流动性指标

### Order (订单)
- 订单参数 (方向, 类型, 价格, 数量)
- 状态管理 (Pending → Partial → Filled)
- 成交记录
- 领域事件 (OrderFilledEvent)

### Position (持仓)
- Yes/No 代币数量
- 净敞口计算
- 成本基础
- 盈亏计算 (未实现/已实现)

## 许可证

MIT
