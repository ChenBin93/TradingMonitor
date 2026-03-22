# TradingMonitor

OKX 永续合约实时监控 + 持仓监控系统。

## 功能

- **实时行情** — WebSocket 订阅 OKX 永续合约，15m / 1H / 4H 三个时间框架
- **信号检测** — RSI 极值、布林带收窄、MA 汇聚、MACD 交叉、量能异动
- **AlertFilter** — 置信度打分 + 30分钟静默去重 + 显著性变化检测
- **持仓监控** — 每分钟读取 OKX 账户持仓，浮亏/浮盈预警
- **信号匹配** — 持仓方向与信号方向相反时预警
- **飞书推送** — 指标信号 + 持仓提醒，推送到飞书群

## 目录结构

```
TradingMonitor/
├── configs/
│   ├── default.yaml       # 主配置（标的数量、阈值、指标参数）
│   └── secrets.yaml       # API Key / 飞书密钥（不提交）
├── src/
│   ├── config/            # 配置加载
│   ├── core/              # 主逻辑（scanner、持仓监控）
│   ├── data/              # 数据层（OKX 适配器、WebSocket）
│   ├── signals/           # 信号检测
│   ├── notification/      # 飞书推送
│   └── utils/             # 工具（健康检查、日志）
├── scripts/
│   └── kill_scanner.sh    # 杀进程脚本
└── pyproject.toml
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
# 或
pip install -e .
```

### 2. 配置

```bash
cp configs/secrets.yaml.example configs/secrets.yaml
# 编辑 secrets.yaml，填入你的密钥
```

编辑 `configs/default.yaml`：

```yaml
data:
  top_n: 100                    # 监控标的数量
  websocket:
    enabled: true               # WebSocket 实时模式

position_alert:
  pnl_loss_pct: 5.0            # 浮亏多少%时预警
  pnl_profit_pct: 10.0         # 浮盈多少%时预警

indicators:
  rsi:
    oversold: 35               # RSI 超卖阈值
    overbot: 65                # RSI 超买阈值
```

### 3. 运行

```bash
CONFIG_PATH=configs/default.yaml python -m src.core.main
```

WebSocket 实时模式（默认，每分钟扫描）：
```bash
CONFIG_PATH=configs/default.yaml python -m src.core.main
```

批量扫描模式（手动）：
```bash
CONFIG_PATH=configs/default.yaml python -m src.core.main
# 确保 default.yaml 中 websocket.enabled: false
```

### 4. 健康检查

```bash
curl http://localhost:8080/health
```

## 配置说明

### OKX API 权限

建议创建**只读** API Key，仅需要：
- 读取账户持仓
- 读取市场数据

### 飞书机器人

1. 在[飞书开放平台](https://open.feishu.cn/)创建应用
2. 开启机器人能力
3. 添加「发送消息」权限
4. 获取 `app_id`、`app_secret`
5. 将机器人添加到群，获取 `chat_id`

## 项目约束

- **不实现**：自动交易、自动开仓/平仓
- **只做**：提醒和参考
- **API Key**：建议只给读取权限

## License

MIT
