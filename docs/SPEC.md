# Opportunity Screening System - 架构设计文档

> 版本: v1.0  
> 日期: 2026-03-21  
> 状态: 设计完成  
> 系统类型: OKX永续合约机会预警系统

---

## 1. 背景与目标

### 1.1 项目现状

当前系统（代号"实验009"）是一个功能性原型：
- 单脚本为主，所有模块堆在根目录
- 核心逻辑完整（扫描、指标、信号、预警）
- 缺少生产级基础设施（测试、配置管理、监控）

### 1.2 设计目标

1. **可迭代** - 支持参数调整、回测验证、信号扩展
2. **可维护** - 清晰的分层架构，模块职责明确
3. **可观测** - 日志、健康检查、性能指标
4. **可部署** - 支持容器化、环境隔离
5. **可测试** - 单元测试覆盖核心逻辑

### 1.3 非目标

- 不改变核心交易逻辑（Stage1/Stage2信号规则保持不变）
- 不引入回测引擎（作为独立模块，后续迭代）
- 不实现自动交易（仅作为预警系统）

### 1.4 扩展性预留

系统设计时预留了多交易所、多市场扩展能力：

```
当前实现:
└── OKX 永续合约 (USDT本位)

预留扩展:
├── Binance (合约/现货)
├── A股 (实时行情API)
├── 美股 (Alpha Vantage / Yahoo Finance)
└── 其他交易所...
```

**扩展性设计要点**：
- `ExchangeAdapter` 接口：统一不同交易所的数据格式
- `MarketDataSource` 抽象：支持不同市场数据源
- 配置化切换：通过配置文件选择数据源
- 当前仅实现 OKX，其余预留接口

---

## 2. 项目结构

```
opportunity_screening/
├── src/                          # 源代码包
│   ├── __init__.py
│   ├── config/                   # 配置层
│   │   ├── __init__.py
│   │   ├── settings.py           # Pydantic Settings（环境变量）
│   │   ├── indicators.py         # 指标参数
│   │   ├── scanner.py            # 扫描参数
│   │   └── alert.py              # 预警参数
│   ├── data/                     # 数据层
│   │   ├── __init__.py
│   │   ├── websocket.py          # WebSocket实时数据（新增）
│   │   ├── exchange.py           # REST API获取（兜底）
│   │   ├── cache.py              # 内存缓存管理
│   │   ├── history.py            # 历史数据存储+统计
│   │   └── storage.py            # 数据库操作
│   ├── signals/                  # 信号层
│   │   ├── __init__.py
│   │   ├── registry.py           # 信号注册表（新增）
│   │   ├── stage1.py             # Stage1监测
│   │   ├── stage2.py             # Stage2入场
│   │   └── indicators.py         # 指标计算
│   ├── alerts/                   # 预警层
│   │   ├── __init__.py
│   │   ├── manager.py            # 预警管理
│   │   ├── scoring.py            # 置信度评分引擎（新增）
│   │   ├── push_controller.py    # 推送控制器（新增）
│   │   ├── deduplication.py      # 去重逻辑（持久化）
│   │   └── formatters.py         # 格式化
│   ├── notification/             # 通知层
│   │   ├── __init__.py
│   │   ├── feishu.py             # 飞书客户端
│   │   └── commands.py           # 命令解析
│   ├── core/                     # 核心调度
│   │   ├── __init__.py
│   │   ├── scanner.py            # 主扫描循环
│   │   └── lifecycle.py          # 生命周期管理
│   └── utils/                    # 工具层
│       ├── __init__.py
│       ├── logging.py            # 日志配置+轮转
│       └── health.py             # 健康检查
├── tests/                        # 测试套件
│   ├── __init__.py
│   ├── conftest.py              # pytest配置
│   ├── unit/                     # 单元测试
│   │   ├── test_indicators.py
│   │   ├── test_signals.py
│   │   └── test_dedup.py
│   └── integration/              # 集成测试
│       └── test_scan.py
├── scripts/                      # 运维脚本
│   ├── run.py                   # 入口点
│   ├── init_db.py               # 数据库初始化
│   └── backfill_history.py      # 历史数据补全（可选，后台执行）
├── configs/                     # 配置文件
│   ├── default.yaml            # 默认配置
│   ├── production.yaml         # 生产配置
│   ├── signals.yaml            # 信号定义配置
│   └── push.yaml              # 推送策略配置（新增）
├── data/                        # 数据目录
│   └── screening.db
├── logs/                        # 日志目录
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
└── README.md
```

---

## 3. 模块设计

### 3.1 配置层 (config/)

**设计原则**：
- 使用 Pydantic Settings 替代硬编码类
- 支持环境变量覆盖（便于容器化部署）
- 参数分组清晰，便于调优

#### settings.py - 主配置

```python
class Settings(BaseSettings):
    """主配置类，从环境变量加载"""
    
    # 数据源
    exchange: str = 'okx'
    top_n: int = 200
    timeframes: list[str] = ['15m', '1h', '4h']
    
    # 扫描
    scan_interval: int = 300
    historical_bars: int = 100
    
    # 飞书
    feishu_app_id: str = ''
    feishu_app_secret: str = ''
    feishu_chat_id: str = ''
    feishu_enabled: bool = True
    
    # 数据库
    db_path: str = 'data/screening.db'
    
    # 日志
    log_level: str = 'INFO'
    log_rotation: str = 'daily'
    log_retention_days: int = 30
    
    class Config:
        env_file = '.env'
        env_prefix = 'SCREENER_'
```

#### indicators.py - 指标参数

```python
class IndicatorParams(BaseModel):
    """指标计算参数"""
    roc_periods: dict[str, int] = {'15m': 5, '1h': 10, '4h': 20}
    rsi_period: int = 14
    adx_period: int = 14
    bb_period: int = 20
    bb_std: int = 2
    atr_period: int = 14
    volume_ma_period: int = 20
    ma_short: int = 5
    ma_mid: int = 20
    ma_long: int = 60
```

#### scanner.py - 扫描参数

```python
class ScannerParams(BaseModel):
    """扫描相关参数"""
    bb_width_pct_threshold: int = 20
    ma_converge_threshold: float = 0.5
    volume_contraction: float = 0.5
    consolidation_bars: int = 20
    volume_spike: float = 5.0
```

#### alert.py - 预警参数

```python
class AlertParams(BaseModel):
    """预警相关参数"""
    dedup_window_minutes: int = 30
    dedup_volatile_minutes: int = 60
    long_top_n: int = 20
    short_top_n: int = 10
```

### 3.2 数据层 (data/)

#### exchange.py - REST API获取（兜底）

**职责**：作为WebSocket的兜底方案，处理初始化和异常恢复

**关键设计**：
- 封装ccxt调用
- 启动时拉取全量历史数据
- WebSocket断连时临时切换
- 每日定时全量校准

```python
class ExchangeClient:
    def __init__(self, exchange_id: str = 'okx'):
        self.exchange = ccxt.okx()
    
    def fetch_top_symbols(self, n: int) -> list[tuple[str, float]]:
        """获取成交量前N永续合约"""
        
    def fetch_candles(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        """获取K线数据，返回标准DataFrame"""
        
    def fetch_all_timeframes(self, symbol: str, limit: int) -> dict[str, pd.DataFrame]:
        """并发获取所有timeframe"""
```

#### websocket.py - WebSocket实时数据（新增）

**设计背景**：
当前系统每5分钟拉取全量K线数据（600次API调用），耗时60-80秒。改用WebSocket后：
- 主扫描耗时从100秒降至5秒
- 数据实时性从5分钟提升至秒级
- API调用量降低99%

**职责**：
- 建立并维护OKX WebSocket连接
- 订阅K线频道，实时接收数据推送
- 更新本地缓存（内存 + 数据库）
- 处理断连重连

**OKX WebSocket API**：

```
端点: wss://ws.okx.com:8443/ws/v5/public

订阅格式:
{
    "op": "subscribe",
    "args": ["candles15m.BTC-USDT-SWAP", "candles1h.BTC-USDT-SWAP"]
}

推送格式:
{
    "arg": {"channel": "candles15m", "instId": "BTC-USDT-SWAP"},
    "data": [
        ["1709121600", "67450.5", "67500.2", "67400.0", "67480.5", "1234.5"],
        #  [timestamp,   open,      high,      low,      close,     volume]
    ]
}
```

**核心设计**：

```python
import json
import threading
import time
import websocket

class WebSocketManager:
    """OKX WebSocket K线数据管理器"""
    
    def __init__(self, symbols: list[str], timeframes: list[str]):
        self.symbols = symbols
        self.timeframes = timeframes
        self.ws = None
        self.running = False
        self.reconnect_delay = 5  # 重连延迟（秒）
        self.max_reconnect_delay = 60  # 最大重连延迟
        
        # 数据缓存: {symbol: {timeframe: [candles]}}
        self._cache = {}
        self._cache_lock = threading.Lock()
        
        # 回调函数
        self.on_candle_update = None  # K线更新回调
        
    def start(self):
        """启动WebSocket连接"""
        self.running = True
        self._connect_thread = threading.Thread(target=self._run, daemon=True)
        self._connect_thread.start()
        
    def stop(self):
        """停止WebSocket连接"""
        self.running = False
        if self.ws:
            self.ws.close()
            
    def _connect(self):
        """建立WebSocket连接"""
        self.ws = websocket.WebSocketApp(
            "wss://ws.okx.com:8443/ws/v5/public",
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open,
        )
        
    def _run(self):
        """WebSocket运行循环"""
        while self.running:
            try:
                self._connect()
                self.ws.run_forever(ping_interval=30)
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
            if self.running:
                time.sleep(self.reconnect_delay)
                self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)
                
    def _on_open(self, ws):
        """连接建立后订阅频道"""
        logger.info("WebSocket connected, subscribing...")
        
        # 转换symbol格式: BTC/USDT:USDT → BTC-USDT-SWAP
        subs = []
         for sym in self.symbols:
            for tf in self.timeframes:
                tf_code = self._timeframe_to_code(tf)
                inst_id = self._symbol_to_inst_id(sym)
                subs.append(f"{tf_code}.{inst_id}")
        
        ws.send(json.dumps({
            "op": "subscribe",
            "args": subs
        }))
        logger.info(f"Subscribed to {len(subs)} channels")
        
    def _on_message(self, ws, message):
        """处理推送消息"""
        try:
            data = json.loads(message)
            
            # 处理K线推送
            if 'arg' in data and 'candles' in data.get('arg', {}).get('channel', ''):
                self._handle_candle(data)
                
            # 处理心跳响应
            elif data.get('event') == 'pong':
                pass
                
        except Exception as e:
            logger.error(f"Error parsing message: {e}")
            
    def _handle_candle(self, data):
        """处理K线数据推送"""
        channel = data['arg']['channel']  # e.g. "candles15m"
        inst_id = data['arg']['instId']    # e.g. "BTC-USDT-SWAP"
        
        # 转换格式
        symbol = self._inst_id_to_symbol(inst_id)
        timeframe = self._code_to_timeframe(channel)
        
        if 'data' not in data or not data['data']:
            return
            
        candle_data = data['data'][0]
        # candle_data: [ts, o, h, l, c, vol]
        
        candle = {
            'timestamp': datetime.fromtimestamp(int(candle_data[0])),
            'open': float(candle_data[1]),
            'high': float(candle_data[2]),
            'low': float(candle_data[3]),
            'close': float(candle_data[4]),
            'volume': float(candle_data[5]),
        }
        
        # 更新缓存
        self._update_cache(symbol, timeframe, candle)
        
        # 触发回调
        if self.on_candle_update:
            self.on_candle_update(symbol, timeframe, candle)
            
    def _update_cache(self, symbol: str, timeframe: str, candle: dict):
        """更新内存缓存"""
        with self._cache_lock:
            if symbol not in self._cache:
                self._cache[symbol] = {}
            if timeframe not in self._cache[symbol]:
                self._cache[symbol][timeframe] = []
                
            candles = self._cache[symbol][timeframe]
            
            # 检查是否更新现有K线或追加新K线
            if candles:
                last = candles[-1]
                if candle['timestamp'] == last['timestamp']:
                    # 更新现有K线
                    candles[-1] = candle
                elif candle['timestamp'] > last['timestamp']:
                    # 追加新K线
                    candles.append(candle)
                    # 保持缓存大小
                    max_candles = {'15m': 300, '1h': 300, '4h': 300}
                    if len(candles) > max_candles.get(timeframe, 300):
                        candles.pop(0)
            else:
                candles.append(candle)
                
    def get_cache(self, symbol: str, timeframe: str) -> list[dict]:
        """获取缓存数据"""
        with self._cache_lock:
            return self._cache.get(symbol, {}).get(timeframe, [])
            
    def _timeframe_to_code(self, tf: str) -> str:
        """15m → candles15m"""
        tf_map = {'15m': '15m', '1h': '1h', '4h': '4h'}
        return f"candles{tf_map.get(tf, tf)}"
        
    def _code_to_timeframe(self, code: str) -> str:
        """candles15m → 15m"""
        if '15m' in code:
            return '15m'
        elif '1h' in code:
            return '1h'
        elif '4h' in code:
            return '4h'
        return code
        
    def _symbol_to_inst_id(self, symbol: str) -> str:
        """BTC/USDT:USDT → BTC-USDT-SWAP"""
        return symbol.replace('/', '-').replace(':USDT', '-SWAP')
        
    def _inst_id_to_symbol(self, inst_id: str) -> str:
        """BTC-USDT-SWAP → BTC/USDT:USDT"""
        return inst_id.replace('-', '/') + ':USDT'
```

**缓存更新机制**：

```
┌─────────────────────────────────────────────────────────────────────┐
│  WebSocket推送                                                    │
│  每根新K线完成后推送一次 (15m周期约15分钟一次)                     │
│                                                                      │
│  示例: BTC/USDT 15m K线                                            │
│  - 0:00 完成 → 推送 [0:00-0:15] 这根K线                           │
│  - 0:15 完成 → 推送 [0:15-0:30] 这根K线                           │
│  - ...                                                             │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  _update_cache()                                                  │
│                                                                      │
│  情况1: 新K线 (timestamp > last timestamp)                        │
│  → 追加到缓存末尾                                                  │
│  → DB异步写入                                                      │
│                                                                      │
│  情况2: 同根K线在变化 (timestamp == last timestamp)                │
│  → 更新缓存最后一根                                                │
│  → 实时更新指标                                                    │
│                                                                      │
│  情况3: 漏接                                                          │
│  → 下一轮REST拉取补充                                              │
└─────────────────────────────────────────────────────────────────────┘
```

**断连重连策略**：

```
┌─────────────────────────────────────────────────────────────────────┐
│  断连检测                                                          │
│  - WebSocket on_close/on_error 触发                               │
│  - 心跳 ping 超时                                                  │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  指数退避重连                                                      │
│  5s → 10s → 20s → 40s → 60s (最大)                                │
│                                                                      │
│  重连成功 → 重新订阅 → 继续                                        │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  兜底: REST轮询                                                    │
│  断连期间: 临时切换到每5分钟REST拉取                               │
│  重连恢复: 切回WebSocket                                          │
└─────────────────────────────────────────────────────────────────────┘
```

#### cache.py - 缓存管理

**职责**：管理K线缓存，解决 candle_cache 不清理的问题

```python
class CacheManager:
    """K线缓存管理器"""
    
    def __init__(self, storage: 'Storage'):
        self.storage = storage
    
    def get(self, symbol: str, timeframe: str, limit: int) -> list | None:
        """获取缓存，验证新鲜度"""
        
    def set(self, symbol: str, timeframe: str, candles: list):
        """保存缓存"""
        
    def cleanup(self, retention_days: int = 7):
        """清理过期缓存（修复：新增此功能）"""
        
    def get_stats(self) -> dict:
        """返回缓存统计"""
```

**清理策略**：
- K线缓存默认保留7天
- 可配置 `CACHE_RETENTION_DAYS`
- 每周日凌晨执行全量清理

#### history.py - 历史数据存储与统计（新增）

**设计背景**：
当前系统仅存储最近300根K线，无法进行历史统计。历史数据对于机会识别至关重要：
- 波动率分位判断当前市场状态（压缩or扩张）
- 历史最大涨跌幅判断极端行情概率
- 成交量分布判断异常活跃度
- ATR历史分位校准止损参数

**职责**：
- 管理各标的长期历史K线存储（1-2年）
- 定期计算并更新统计指标
- 提供统计查询接口供信号层使用

**核心设计**：

```python
class HistoryManager:
    """历史数据管理器"""
    
    def __init__(self, storage: 'Storage', exchange: 'ExchangeClient'):
        self.storage = storage
        self.exchange = exchange
    
    # ==================== 数据获取 ====================
    
    def fetch_historical_candles(
        self, 
        symbol: str, 
        timeframe: str = '4h',
        days: int = 730  # 默认2年
    ) -> pd.DataFrame:
        """
        获取历史K线数据
        - 使用OKX API获取足够历史的K线
        - 增量更新：已有数据则跳过
        """
        
    def fetch_all_symbols_history(
        self, 
        symbols: list[str],
        timeframe: str = '4h',
        days: int = 730
    ):
        """并发获取所有标的的历史数据"""
        
    # ==================== 统计计算 ====================
    
    def compute_volatility_stats(
        self, 
        df: pd.DataFrame,
        periods: list[int] = [14, 30, 90]
    ) -> dict:
        """
        计算波动率统计
        Returns:
            {
                'atr': {
                    'current': 0.005,
                    'p10': 0.002,
                    'p25': 0.003,
                    'p50': 0.005,
                    'p75': 0.008,
                    'p90': 0.012,
                    'percentile': 50  # 当前处于历史分位
                },
                'bb_width': {...},
                'price_std': {...},
            }
        """
        
    def compute_return_stats(
        self, 
        df: pd.DataFrame,
        periods: list[int] = [1, 7, 30]
    ) -> dict:
        """
        计算收益率统计
        Returns:
            {
                'roc_1d': {
                    'current': 2.5,
                    'mean': 0.3,
                    'std': 5.2,
                    'max_up': 25.0,
                    'max_down': -30.0,
                    'p10': -8.0,
                    'p25': -3.0,
                    'p50': 0.5,
                    'p75': 4.0,
                    'p90': 10.0,
                },
                ...
            }
        """
        
    def compute_volume_stats(
        self, 
        df: pd.DataFrame
    ) -> dict:
        """
        计算成交量统计
        Returns:
            {
                'current_ratio': 1.5,  # 当前成交量/均量
                'mean': 1000000,
                'p10': 500000,
                'p25': 750000,
                'p50': 1000000,
                'p75': 1500000,
                'p90': 2000000,
            }
        """
        
    def compute_regime_stats(
        self, 
        df: pd.DataFrame,
        adx_period: int = 14
    ) -> dict:
        """
        计算市场状态统计
        - 趋势/震荡时间占比
        - ADX分布
        - 典型波动率周期长度
        """
        
    def compute_all_stats(
        self, 
        symbol: str,
        timeframe: str = '4h'
    ) -> dict:
        """计算完整统计指标"""
        
    # ==================== 存储与查询 ====================
    
    def save_stats(
        self, 
        symbol: str, 
        stats: dict,
        timeframe: str = '4h'
    ):
        """保存统计结果到数据库"""
        
    def get_stats(self, symbol: str) -> dict | None:
        """获取最新统计"""
        
    def get_stats_history(
        self, 
        symbol: str, 
        days: int = 90
    ) -> list[dict]:
        """获取历史统计记录"""
        
    # ==================== 调度 ====================
    
    def needs_refresh(self, symbol: str) -> bool:
        """检查是否需要刷新统计"""
        
    def refresh_all_stats(
        self, 
        symbols: list[str],
        force: bool = False
    ):
        """刷新所有标的统计"""
```

**统计指标详解**：

| 统计类型 | 指标 | 用途 |
|---------|------|------|
| **波动率** | ATR分位 | 当前ATR处于历史什么位置 |
| | BB Width分位 | 布林带开口状态 |
| | 价格标准差分位 | 波动率极值判断 |
| **收益率** | 历史最大涨幅 | 极端行情参考 |
| | 历史最大跌幅 | 极端行情参考 |
| | ROC分布 | 当前动量历史位置 |
| **成交量** | 成交量分位 | 异常放量检测 |
| | 缩量分位 | 蓄力信号 |
| **状态** | 趋势/震荡占比 | 当前市场环境判断 |
| | ADX分布 | 趋势强度历史分布 |

**更新策略**：

```python
class HistoryScheduler:
    """历史数据调度器"""
    
    def __init__(self, history_manager: HistoryManager):
        self.history = history_manager
        self.refresh_interval = timedelta(days=7)  # 每周刷新
        self.last_refresh: dict[str, datetime] = {}
        
    def should_refresh(self, symbol: str) -> bool:
        """判断是否需要刷新"""
        if symbol not in self.last_refresh:
            return True
        return datetime.now() - self.last_refresh[symbol] > self.refresh_interval
        
    def schedule_refresh(self, symbols: list[str]):
        """调度刷新任务（后台执行，不影响主扫描）"""
        for symbol in symbols:
            if self.should_refresh(symbol):
                # 后台线程执行
                Thread(target=self._refresh_one, args=(symbol,)).start()
```

### 历史数据异步解耦设计（重要）

**核心原则**：主监控系统不依赖历史数据，独立运行

```
┌─────────────────────────────────────────────────────────────────────┐
│  主监控线程 (每5分钟)                                                │
│                                                                      │
│  启动条件: 无需等待历史数据                                          │
│  运行逻辑:                                                          │
│  ├── 读取实时K线数据 (WebSocket)                                    │
│  ├── 计算实时指标                                                    │
│  ├── 生成预警信号                                                    │
│  └── 推送通知                                                        │
│                                                                      │
│  历史分位:                                                          │
│  ├── 有 → 使用                                                      │
│  ├── 无 → 跳过历史分位相关判断                                       │
│  └── 不等待                                                         │
└─────────────────────────────────────────────────────────────────────┘
                           ↕ 独立运行，互不阻塞
┌─────────────────────────────────────────────────────────────────────┐
│  后台任务 (独立运行)                                                │
│                                                                      │
│  1. 历史数据下载                                                    │
│     ├── 启动时检查各标的是否有历史数据                               │
│     ├── 没有 → 后台开始下载                                         │
│     ├── 有 → 跳过                                                  │
│     └── 主系统不需要等待                                            │
│                                                                      │
│  2. 历史统计计算                                                    │
│     ├── 依赖历史数据下载完成                                         │
│     ├── 计算完成后更新 symbol_stats                                  │
│     └── 主系统查询 symbol_stats时自然使用最新数据                     │
│                                                                      │
│  3. 定期刷新 (每周)                                                 │
│     └── 独立线程，不影响主监控                                       │
└─────────────────────────────────────────────────────────────────────┘
```

**数据就绪标志**：

```python
class HistoryManager:
    """历史数据管理器"""
    
    def is_data_ready(self, symbol: str) -> bool:
        """检查标的的历史数据是否就绪"""
        # 检查条件：
        # 1. history_candles 表有足够数据
        # 2. symbol_stats 表有最新统计
        pass
        
    def get_stats_if_ready(self, symbol: str) -> dict | None:
        """获取历史统计（有就返回，没有返回None）"""
        if self.is_data_ready(symbol):
            return self.get_stats(symbol)
        return None
```

**主扫描中的使用**：

```python
def run_scan():
    for symbol in symbols:
        # 实时指标（必须有）
        df = get_realtime_data(symbol)  # WebSocket数据
        
        # 历史统计（可选）
        history_stats = history_manager.get_stats_if_ready(symbol)
        
        if history_stats:
            # 使用历史分位增强判断
            signal = generate_signal(df, history_stats)
        else:
            # 无历史数据，使用基本判断
            signal = generate_signal(df, None)
```

**启动流程**：

```
┌─────────────────────────────────────────────────────────────────────┐
│  系统启动                                                          │
│                                                                      │
│  1. 初始化组件                                                      │
│     ├── WebSocket 连接                                               │
│     ├── 内存缓存                                                    │
│     └── 飞书连接                                                    │
│                                                                      │
│  2. 启动主监控线程 (立即开始)                                        │
│     └── 每5分钟扫描，不等待历史数据                                   │
│                                                                      │
│  3. 启动后台任务                                                   │
│     ├── 历史数据下载线程 (持续运行)                                  │
│     │   └── 逐标的检查+下载，不阻塞                                  │
│     ├── 历史统计计算 (数据就绪后)                                    │
│     │   └── 依赖下载完成                                           │
│     └── 定期刷新 (每周)                                             │
│         └── 独立运行                                               │
│                                                                      │
│  状态:                                                              │
│  ├── 系统: 就绪 (主监控可运行)                                      │
│  ├── 历史: 下载中 / 已就绪                                          │
│  └── 报警: 历史分位未就绪 (仅首次启动时短暂)                         │
└─────────────────────────────────────────────────────────────────────┘
```

**下载任务队列**：

```python
class HistoryDownloader:
    """历史数据下载器"""
    
    def __init__(self, max_workers: int = 3):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.pending = Queue()  # 待下载队列
        self.completed = set()  # 已完成
        
    def start(self, symbols: list[str]):
        """启动下载任务"""
        for symbol in symbols:
            if not self.history_manager.is_data_ready(symbol):
                self.pending.put(symbol)
                
        # 启动工作线程
        for _ in range(self.max_workers):
            self.executor.submit(self._worker)
            
    def _worker(self):
        """工作线程"""
        while True:
            try:
                symbol = self.pending.get(timeout=1)
                self._download_and_compute(symbol)
                self.completed.add(symbol)
                self.pending.task_done()
            except Empty:
                break
                
    def _download_and_compute(self, symbol: str):
        """下载并计算单个标的"""
        # 1. 下载历史K线
        self.history_manager.fetch_historical_candles(symbol)
        
        # 2. 计算统计
        self.history_manager.compute_and_save_stats(symbol)
```

**数据库Schema扩展**：

```sql
-- 历史K线存储（长期，1-2年）
CREATE TABLE history_candles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timeframe TEXT,              -- 主要用4h
    timestamp DATETIME,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    UNIQUE(symbol, timeframe, timestamp)
);

-- 统计指标快照（每周更新一次）
CREATE TABLE symbol_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timeframe TEXT,
    computed_at DATETIME,
    
    -- 波动率统计 (JSON)
    volatility_stats TEXT,       -- {"atr_p50": 0.005, "atr_p90": 0.012, ...}
    
    -- 收益率统计 (JSON)
    return_stats TEXT,          -- {"max_up_1d": 25.0, "max_down_1d": -30.0, ...}
    
    -- 成交量统计 (JSON)
    volume_stats TEXT,          -- {"p50": 1000000, "current_ratio": 1.5, ...}
    
    -- 市场状态统计 (JSON)
    regime_stats TEXT,          -- {"trend_ratio": 0.65, "avg_adx": 25.0, ...}
    
    UNIQUE(symbol, timeframe, computed_at)
);

-- 索引
CREATE INDEX idx_history_symbol_tf ON history_candles(symbol, timeframe, timestamp);
CREATE INDEX idx_stats_symbol_computed ON symbol_stats(symbol, computed_at DESC);
```

#### storage.py - 数据库操作

**职责**：封装所有数据库操作

**新增表**：

```sql
-- 历史K线（长期存储，1-2年）
CREATE TABLE history_candles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timeframe TEXT,              -- 主要存4h
    timestamp DATETIME,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    UNIQUE(symbol, timeframe, timestamp)
);

-- 统计指标快照（每周更新）
CREATE TABLE symbol_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timeframe TEXT,
    computed_at DATETIME,
    volatility_stats TEXT,       -- JSON: ATR/BB Width分位
    return_stats TEXT,           -- JSON: 最大涨跌幅/Roc分布
    volume_stats TEXT,           -- JSON: 成交量分位
    regime_stats TEXT,           -- JSON: 趋势/震荡占比
    UNIQUE(symbol, timeframe, computed_at)
);

-- 信号注册表（可扩展）
CREATE TABLE signal_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_type TEXT UNIQUE,
    description TEXT,
    enabled INTEGER DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 推送记录（去重持久化）
CREATE TABLE notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    stage TEXT,
    signal_type TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, stage, timestamp)
);

-- 系统状态（健康检查）
CREATE TABLE system_status (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 3.3 信号层 (signals/)

#### registry.py - 信号注册表（核心扩展点）

**职责**：
- 管理所有信号类型的注册和发现
- 支持动态添加/移除信号类型
- 配置化的信号参数
- 信号组合逻辑

```python
@dataclass
class SignalDefinition:
    """信号定义"""
    name: str                           # 信号名称 (e.g. 'bb_width_squeeze')
    display_name: str                   # 显示名称 (e.g. '波动率压缩')
    description: str                    # 描述
    category: str                       # 分类: 'trend' | 'range' | 'momentum' | 'volume' | 'custom'
    direction: str                       # 方向: 'long' | 'short' | 'neutral'
    
    # 触发条件（配置化）
    conditions: list['SignalCondition']   # AND/OR 条件列表
    
    # 历史分位配置（可选）
    history_conditions: list['HistoryCondition'] | None = None
    
    # 严重程度计算
    severity_rules: list['SeverityRule'] | None = None
    
    # 是否启用
    enabled: bool = True


@dataclass
class SignalCondition:
    """信号条件"""
    indicator: str          # 指标名 (e.g. 'bb_width_pct')
    operator: str          # 比较符: '<' | '>' | '<=' | '>=' | '==' | 'between'
    value: float           # 阈值
    value2: float | None = None  # between时的高值
    timeframe: str | None = None  # 指定timeframe，不指定则用当前


@dataclass
class HistoryCondition:
    """历史分位条件"""
    indicator: str          # 指标名 (e.g. 'bb_width')
    percentile: float       # 分位阈值 (e.g. 20 表示20%分位)
    direction: str = 'below'  # 'below' | 'above'


@dataclass  
class SeverityRule:
    """严重程度规则"""
    condition: str          # 条件表达式 (e.g. "bb_width_pct <= 10")
    severity: str           # 'high' | 'medium' | 'low'


class SignalRegistry:
    """信号注册表"""
    
    def __init__(self):
        self._signals: dict[str, SignalDefinition] = {}
        self._handlers: dict[str, Callable] = {}
        
    def register_signal(self, definition: SignalDefinition):
        """注册信号"""
        self._signals[definition.name] = definition
        
    def register_handler(self, signal_name: str, handler: Callable):
        """注册信号处理器"""
        self._handlers[signal_name] = handler
        
    def get_signal(self, name: str) -> SignalDefinition | None:
        """获取信号定义"""
        return self._signals.get(name)
        
    def get_enabled_signals(self, category: str | None = None) -> list[SignalDefinition]:
        """获取启用的信号列表"""
        signals = [s for s in self._signals.values() if s.enabled]
        if category:
            signals = [s for s in signals if s.category == category]
        return signals
        
    def load_from_config(self, config: dict):
        """从配置加载信号定义"""
        for name, cfg in config.items():
            definition = SignalDefinition(
                name=name,
                display_name=cfg.get('display_name', name),
                description=cfg.get('description', ''),
                category=cfg.get('category', 'custom'),
                direction=cfg.get('direction', 'neutral'),
                conditions=[SignalCondition(**c) for c in cfg.get('conditions', [])],
                history_conditions=[HistoryCondition(**h) for h in cfg.get('history_conditions', [])],
                severity_rules=[SeverityRule(**s) for s in cfg.get('severity_rules', [])],
                enabled=cfg.get('enabled', True),
            )
            self.register_signal(definition)
```

**配置文件示例**：

```yaml
# signals.yaml

signals:
  bb_width_squeeze:
    display_name: 波动率压缩
    description: 布林带收口，预示突破
    category: trend
    direction: neutral
    conditions:
      - indicator: bb_width_pct
        operator: '<='
        value: 20
    history_conditions:
      - indicator: bb_width
        percentile: 20
        direction: below
    severity_rules:
      - condition: "bb_width_pct <= 10"
        severity: high
      - condition: "bb_width_pct <= 20"
        severity: medium

  rsi_extreme:
    display_name: RSI极值
    description: RSI超买超卖
    category: range
    direction: neutral
    conditions:
      - indicator: rsi
        operator: '<='
        value: 35
    severity_rules:
      - condition: "rsi <= 25"
        severity: high
      - condition: "rsi <= 35"
        severity: medium

  volume_spike:
    display_name: 成交量爆发
    description: 成交量异常放大
    category: volume
    direction: neutral
    conditions:
      - indicator: volume_ratio
        operator: '>='
        value: 5.0
    history_conditions:
      - indicator: volume
        percentile: 90
        direction: above
    severity_rules:
      - condition: "volume_ratio >= 10"
        severity: high
      - condition: "volume_ratio >= 5"
        severity: medium

  # 自定义信号示例
  custom_breakout:
    display_name: 自定义突破
    description: 多指标组合突破
    category: trend
    direction: long
    conditions:
      - indicator: close
        operator: '>'
        value: 0  # 占位，实际用表达式
      - indicator: adx
        operator: '>='
        value: 25
      - indicator: volume_ratio
        operator: '>='
        value: 2.0
    enabled: false  # 默认关闭，可手动启用
```

**信号评估引擎**：

```python
class SignalEvaluator:
    """信号评估引擎"""
    
    def __init__(self, registry: SignalRegistry):
        self.registry = registry
        
    def evaluate(self, state: SymbolState, history_stats: dict | None) -> list[SignalResult]:
        """评估所有信号"""
        results = []
        
        for signal_def in self.registry.get_enabled_signals():
            result = self._evaluate_signal(signal_def, state, history_stats)
            if result:
                results.append(result)
                
        return results
        
    def _evaluate_signal(
        self, 
        signal_def: SignalDefinition, 
        state: SymbolState,
        history_stats: dict | None
    ) -> SignalResult | None:
        """评估单个信号"""
        # 1. 检查实时条件
        for cond in signal_def.conditions:
            if not self._check_condition(cond, state):
                return None
                
        # 2. 检查历史条件（如果有）
        if signal_def.history_conditions and history_stats:
            for h_cond in signal_def.history_conditions:
                if not self._check_history_condition(h_cond, history_stats):
                    return None
                    
        # 3. 计算严重程度
        severity = self._calc_severity(signal_def.severity_rules, state)
        
        return SignalResult(
            signal_type=signal_def.name,
            display_name=signal_def.display_name,
            direction=signal_def.direction,
            severity=severity,
            indicators=self._extract_indicators(state),
            history_context=self._extract_history_context(history_stats),
        )
        
    def _check_condition(self, cond: SignalCondition, state: SymbolState) -> bool:
        """检查单个条件"""
        # 获取指标值
        value = state.get_indicator(cond.indicator, cond.timeframe)
        if value is None:
            return False
            
        # 比较
        if cond.operator == '<':
            return value < cond.value
        elif cond.operator == '>':
            return value > cond.value
        elif cond.operator == '<=':
            return value <= cond.value
        elif cond.operator == '>=':
            return value >= cond.value
        elif cond.operator == 'between':
            return cond.value <= value <= (cond.value2 or cond.value)
            
        return False
```

#### stage1.py - Stage1监测

**职责**：使用信号注册表检测预警信号

```python
class Stage1Monitor:
    """Stage1 预警监测"""
    
    def __init__(
        self, 
        registry: SignalRegistry,
        evaluator: SignalEvaluator
    ):
        self.registry = registry
        self.evaluator = evaluator
        
    def scan(self, symbols_data: dict) -> dict:
        """扫描所有标的"""
        all_alerts = []
        states_by_symbol = {}
        
        for symbol, states in symbols_data.items():
            alerts = self._scan_symbol(symbol, states)
            all_alerts.extend(alerts)
            states_by_symbol[symbol] = states
            
        return {
            'all': all_alerts,
            'long': self._filter_direction(all_alerts, 'long'),
            'short': self._filter_direction(all_alerts, 'short'),
            'states': states_by_symbol,
        }
        
    def _scan_symbol(
        self, 
        symbol: str, 
        states: dict[str, SymbolState]
    ) -> list[Stage1Alert]:
        """扫描单个标的"""
        alerts = []
        
        for timeframe, state in states.items():
            # 获取该标的的历史统计
            history_stats = self._get_history_stats(symbol)
            
            # 评估所有信号
            signal_results = self.evaluator.evaluate(state, history_stats)
            
            for result in signal_results:
                alerts.append(Stage1Alert(
                    symbol=symbol,
                    timeframe=timeframe,
                    signal_type=result.signal_type,
                    display_name=result.display_name,
                    regime=state.regime,
                    direction=result.direction,
                    severity=result.severity,
                    indicators=result.indicators,
                    history_context=result.history_context,
                ))
                
        return alerts
```

**历史分位在信号中的应用**：

| 场景 | 历史统计作用 | 配置方式 |
|------|------------|---------|
| 波动率压缩预警 | BB Width处于历史20%分位 → 突破概率增加 | `history_conditions[percentile=20, below]` |
| ATR分位校准 | 当前ATR处于90%分位 → 扩大止损 | 条件判断 + 阈值调整 |
| 极端行情过滤 | ROC超过历史95%分位 → 谨慎入场 | `history_conditions[percentile=95, above]` |
| 成交量异常 | 成交量>历史90%分位 → 主力异动信号 | `history_conditions[percentile=90, above]` |

#### stage2.py - Stage2入场

**职责**：趋势/震荡双策略入场确认

**重构点**：
- 从 entry_signal.py 重命名
- 输出结构化 EntrySignal 对象

```python
@dataclass
class EntrySignal:
    symbol: str
    signal_type: str  # 'trend_breakout_long' | 'trend_breakout_short' | 'range_reversion_long' | 'range_reversion_short'
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    indicators: dict
```

#### indicators.py - 指标计算

**职责**：技术指标向量化计算

**保持不变**，仅移动到 signals/ 目录

**与历史统计集成**：

```python
def compute_all_indicators(df, params, history_stats: dict | None = None):
    """
    扩展指标计算，支持历史分位
    """
    result = _compute_base_indicators(df, params)
    
    if history_stats:
        # 添加历史分位信息
        result['atr_percentile'] = history_stats.get('atr', {}).get('percentile')
        result['volume_percentile'] = history_stats.get('volume', {}).get('percentile')
        result['max_drawdown_historical'] = history_stats.get('return', {}).get('max_down')
        
    return result
```

### 3.4 预警层 (alerts/)

#### 问题：当前设计的局限

```
┌─────────────────────────────────────────────────────────────────────┐
│  当前：时间驱动 + 强制排序推送                                       │
│                                                                      │
│  每5分钟扫描 → 固定排序 → Top N推送                                │
│                                                                      │
│  问题:                                                               │
│  ├── 5分钟可能没有真正机会，但仍然推送                               │
│  ├── 强制推送Top N，不考虑机会是否真正可信                           │
│  ├── 推送频率固定，不灵活                                           │
│  └── 没有置信度概念，无法筛选真正值得关注的信号                      │
└─────────────────────────────────────────────────────────────────────┘
```

#### 新设计：置信度驱动 + 事件推送

```
┌─────────────────────────────────────────────────────────────────────┐
│  新的推送逻辑                                                       │
│                                                                      │
│  WebSocket实时数据 → 持续评分 → 置信度判断 → 触发推送               │
│                                                                      │
│  核心变化:                                                          │
│  ├── 不再固定每5分钟推送                                            │
│  ├── 有高置信度机会才推送                                          │
│  ├── 扫描频率更短（分钟级）                                         │
│  └── 推送是事件驱动，不是时间驱动                                   │
└─────────────────────────────────────────────────────────────────────┘
```

#### scoring.py - 置信度评分引擎（新增）

**核心概念**：
- 每个信号有一个置信度分数 (0-100)
- 超过阈值才推送
- **趋势和震荡使用不同的评分维度和权重**

```
┌─────────────────────────────────────────────────────────────────────┐
│  评分设计原则                                                       │
│                                                                      │
│  趋势市场 (regime='trend'):                                         │
│  ├── ADX > 25 表示趋势市场                                          │
│  ├── 评分重点: 趋势质量、多周期共振、突破确认                         │
│  └── 适合信号: 突破、动量、成交量爆发                                 │
│                                                                      │
│  震荡市场 (regime='range'):                                         │
│  ├── ADX < 25 表示震荡市场                                          │
│  ├── 评分重点: RSI极值、均值回归、历史分位                            │
│  └── 适合信号: 超买超卖、价格回归                                     │
└─────────────────────────────────────────────────────────────────────┘
```

```python
@dataclass
class ConfidenceScore:
    """置信度评分"""
    regime: str                      # 'trend' | 'range'
    total: float                    # 总分 0-100
    breakdown: dict[str, float]     # 各维度得分
    factors: dict[str, any]         # 评分因子详情
    
    @property
    def is_push_worthy(self) -> bool:
        return self.total >= self.push_threshold


class ConfidenceScorer:
    """置信度评分引擎"""
    
    # 趋势市场评分维度权重
    TREND_WEIGHTS = {
        'trend_quality': 0.25,         # ADX趋势强度 ⭐
        'timeframe_alignment': 0.25,   # 多周期共振 ⭐
        'breakout_confidence': 0.20,   # 突破确认 ⭐
        'volume_confirmation': 0.15,  # 成交量确认
        'history_context': 0.10,      # 历史分位
        'severity': 0.05,             # 严重程度
    }
    
    # 震荡市场评分维度权重
    RANGE_WEIGHTS = {
        'extreme_level': 0.30,         # 极值程度 ⭐
        'reversion_probability': 0.25, # 回归概率 ⭐
        'history_context': 0.20,      # 历史分位 ⭐
        'volume_confirmation': 0.15,  # 成交量确认
        'timeframe_alignment': 0.05,  # 多周期共振
        'severity': 0.05,             # 严重程度
    }
    
    def __init__(self, history_manager: 'HistoryManager'):
        self.history = history_manager
    
    def score(self, alert: Stage1Alert, state: SymbolState) -> ConfidenceScore:
        """
        计算信号置信度
        根据市场状态(regime)选择不同评分逻辑
        """
        # 判断市场状态
        regime = self._detect_regime(state)
        
        if regime == 'trend':
            return self._score_trend(alert, state)
        else:
            return self._score_range(alert, state)
    
    def _detect_regime(self, state: SymbolState) -> str:
        """判断市场状态"""
        adx = state.d.get('adx') or 20
        if adx >= 25:
            return 'trend'
        else:
            return 'range'
    
    # ==================== 趋势市场评分 ====================
    
    def _score_trend(self, alert: Stage1Alert, state: SymbolState) -> ConfidenceScore:
        """趋势市场评分"""
        factors = {}
        
        # 1. 趋势质量 (0-100) ⭐ 最重要
        factors['trend_quality'] = self._calc_adx_score(state)
        
        # 2. 多周期共振 (0-100) ⭐ 最重要
        factors['timeframe_alignment'] = self._calc_timeframe_alignment(alert, state)
        
        # 3. 突破确认 (0-100) ⭐ 趋势特有
        factors['breakout_confidence'] = self._calc_breakout_confidence(alert, state)
        
        # 4. 成交量确认 (0-100)
        factors['volume_confirmation'] = self._calc_volume_confirmation(state)
        
        # 5. 历史分位 (0-100)
        factors['history_context'] = self._calc_history_context(alert, state)
        
        # 6. 严重程度 (0-100)
        factors['severity'] = self._calc_severity_score(alert)
        
        # 加权计算
        total = sum(
            self.TREND_WEIGHTS[dim] * score 
            for dim, score in factors.items()
        )
        
        return ConfidenceScore(
            regime='trend',
            total=round(total, 1),
            breakdown={k: round(v, 1) for k, v in factors.items()},
            factors=self._extract_factors(alert, state),
            push_threshold=70.0
        )
    
    def _calc_adx_score(self, state: SymbolState) -> float:
        """
        ADX趋势强度评分
        - ADX > 40: 100分 (强趋势)
        - ADX > 30: 80分 (中强趋势)
        - ADX > 25: 60分 (确认趋势)
        - ADX < 25: 40分 (趋势不强)
        """
        adx = state.d.get('adx') or 20
        if adx >= 40:
            return 100.0
        elif adx >= 30:
            return 80.0
        elif adx >= 25:
            return 60.0
        else:
            return 40.0
    
    def _calc_breakout_confidence(self, alert: Stage1Alert, state: SymbolState) -> float:
        """
        突破确认评分（趋势特有）
        检查:
        - 价格是否突破关键位
        - +DI vs -DI 方向确认
        - ROC动量强度
        """
        score = 50  # 基础分
        
        plus_di = state.d.get('plus_di') or 0
        minus_di = state.d.get('minus_di') or 0
        
        # DI方向确认
        if alert.direction == 'long' and plus_di > minus_di:
            score += 20
        elif alert.direction == 'short' and minus_di > plus_di:
            score += 20
        
        # ROC动量
        roc = abs(state.d.get('roc') or 0)
        if roc > 1.0:
            score += 15
        elif roc > 0.5:
            score += 10
        
        return min(100, score)
    
    # ==================== 震荡市场评分 ====================
    
    def _score_range(self, alert: Stage1Alert, state: SymbolState) -> ConfidenceScore:
        """震荡市场评分"""
        factors = {}
        
        # 1. 极值程度 (0-100) ⭐ 最重要
        factors['extreme_level'] = self._calc_extreme_level(alert, state)
        
        # 2. 回归概率 (0-100) ⭐ 震荡特有
        factors['reversion_probability'] = self._calc_reversion_probability(alert, state)
        
        # 3. 历史分位 (0-100) ⭐ 历史极端位置
        factors['history_context'] = self._calc_history_context(alert, state)
        
        # 4. 成交量确认 (0-100)
        factors['volume_confirmation'] = self._calc_volume_confirmation(state)
        
        # 5. 多周期共振 (0-100)
        factors['timeframe_alignment'] = self._calc_timeframe_alignment(alert, state)
        
        # 6. 严重程度 (0-100)
        factors['severity'] = self._calc_severity_score(alert)
        
        # 加权计算
        total = sum(
            self.RANGE_WEIGHTS[dim] * score 
            for dim, score in factors.items()
        )
        
        return ConfidenceScore(
            regime='range',
            total=round(total, 1),
            breakdown={k: round(v, 1) for k, v in factors.items()},
            factors=self._extract_factors(alert, state),
            push_threshold=70.0
        )
    
    def _calc_extreme_level(self, alert: Stage1Alert, state: SymbolState) -> float:
        """
        极值程度评分（震荡特有）
        RSI极值越明显，分越高
        """
        rsi = state.d.get('rsi') or 50
        
        # 超卖 (做多信号)
        if rsi <= 25:
            return 100.0
        elif rsi <= 30:
            return 80.0
        elif rsi <= 35:
            return 60.0
        
        # 超买 (做空信号)
        elif rsi >= 75:
            return 100.0
        elif rsi >= 70:
            return 80.0
        elif rsi >= 65:
            return 60.0
        
        return 50.0
    
    def _calc_reversion_probability(self, alert: Stage1Alert, state: SymbolState) -> float:
        """
        回归概率评分（震荡特有）
        检查:
        - 价格是否在BB极端位置
        - ADX低（确认震荡）
        - 是否有回归空间
        """
        score = 50  # 基础分
        
        adx = state.d.get('adx') or 20
        bb_width_pct = state.d.get('bb_width_pct') or 50
        
        # ADX低确认震荡
        if adx < 15:
            score += 20
        elif adx < 20:
            score += 10
        
        # BB宽度小（压缩后更有爆发力）
        if bb_width_pct < 10:
            score += 20
        elif bb_width_pct < 20:
            score += 10
        
        return min(100, score)
    
    # ==================== 通用评分方法 ====================
    
    def _calc_history_context(self, alert: Stage1Alert, state: SymbolState) -> float:
        """
        历史分位评分
        处于历史极端位置，分越高
        """
        history_stats = self.history.get_stats_if_ready(alert.symbol)
        if not history_stats:
            return 50.0  # 无历史数据
        
        # 根据信号类型获取对应分位
        signal_type = alert.signal_type
        
        if 'volume' in signal_type:
            pct = history_stats.get('volume', {}).get('percentile', 50)
        elif 'bb' in signal_type or 'squeeze' in signal_type:
            pct = history_stats.get('bb_width', {}).get('percentile', 50)
        elif 'rsi' in signal_type:
            pct = history_stats.get('rsi', {}).get('percentile', 50)
        elif 'atr' in signal_type or 'volatility' in signal_type:
            pct = history_stats.get('atr', {}).get('percentile', 50)
        else:
            pct = 50
        
        # 分位越低越极端，分越高
        # 10%分位 → 100分, 50%分位 → 50分
        return max(0, 110 - pct)
    
    def _calc_timeframe_alignment(self, alert: Stage1Alert, state: SymbolState) -> float:
        """
        多周期共振评分
        多周期同时确认，分越高
        """
        # 这个需要访问其他timeframe的数据
        # 简化版本：当前周期基础分
        return 50.0
    
    def _calc_volume_confirmation(self, state: SymbolState) -> float:
        """
        成交量确认评分
        """
        vol_ratio = state.d.get('volume_ratio') or 1.0
        
        if vol_ratio >= 5:
            return 100.0
        elif vol_ratio >= 3:
            return 80.0
        elif vol_ratio >= 1.5:
            return 60.0
        elif vol_ratio >= 1.0:
            return 50.0
        else:
            return 30.0
    
    def _calc_severity_score(self, alert: Stage1Alert) -> float:
        """严重程度评分"""
        severity_map = {'high': 100, 'medium': 60, 'low': 30}
        return severity_map.get(alert.severity, 50)
```
        return min(100, 40 + confirmations * 20)
    
    def _calc_history_context(self, alert: Stage1Alert, state: SymbolState) -> float:
        """
        历史分位：当前状态在历史上的极端程度
        - 处于历史10%分位以下: 100分
        - 处于历史20%分位以下: 80分
        - 处于历史30%分位以下: 60分
        - 处于历史50%分位: 50分
        - 无历史数据: 50分（默认）
        """
        history_stats = self.history.get_stats_if_ready(alert.symbol)
        if not history_stats:
            return 50.0
            
        # 根据信号类型获取对应的历史分位
        signal_type = alert.signal_type
        
        if 'volume' in signal_type:
            pct = history_stats.get('volume', {}).get('percentile', 50)
        elif 'bb' in signal_type or 'squeeze' in signal_type:
            pct = history_stats.get('bb_width', {}).get('percentile', 50)
        elif 'rsi' in signal_type:
            pct = history_stats.get('rsi', {}).get('percentile', 50)
        elif 'atr' in signal_type or 'volatility' in signal_type:
            pct = history_stats.get('atr', {}).get('percentile', 50)
        else:
            pct = 50
        
        # 转换为分数：分位越低越极端，分越高
        # 10%分位 → 100分, 50%分位 → 50分
        return max(0, 110 - pct)
    
    def _calc_timeframe_alignment(self, alert: Stage1Alert, state: SymbolState) -> float:
        """
        多周期共振：多周期同时出现相同信号
        - 仅当前周期: 30分
        - 2个周期共振: 70分
        - 3个周期共振: 100分
        """
        # 检查各周期是否都满足相似条件
        # 这个需要根据实际信号类型调整
        aligned_count = 1  # 当前
        # ... 检查其他周期
        
        return 30 + aligned_count * 35
    
    def _calc_volume_confirmation(self, alert: Stage1Alert, state: SymbolState) -> float:
        """
        成交量确认：成交量是否支持信号
        - 极度放量 (>5x): 100分
        - 明显放量 (>3x): 80分
        - 温和放量 (>1.5x): 60分
        - 正常量: 50分
        - 缩量: 30分
        """
        vol_ratio = state.d.get('volume_ratio') or 1.0
        
        if vol_ratio >= 5:
            return 100.0
        elif vol_ratio >= 3:
            return 80.0
        elif vol_ratio >= 1.5:
            return 60.0
        elif vol_ratio >= 1.0:
            return 50.0
        else:
            return 30.0
    
    def _calc_trend_quality(self, alert: Stage1Alert, state: SymbolState) -> float:
        """
        趋势质量：ADX强度
        - ADX > 40: 100分
        - ADX > 30: 80分
        - ADX > 20: 60分
        - ADX < 20: 40分
        """
        adx = state.d.get('adx') or 20
        
        if adx >= 40:
            return 100.0
        elif adx >= 30:
            return 80.0
        elif adx >= 20:
            return 60.0
        else:
            return 40.0
    
    def _calc_severity_score(self, alert: Stage1Alert) -> float:
        """严重程度映射"""
        severity_map = {'high': 100, 'medium': 60, 'low': 30}
        return severity_map.get(alert.severity, 50)
```

#### manager.py - 预警管理

**职责**：
- 收集信号
- 计算置信度
- 触发推送（事件驱动）

```python
class AlertManager:
    def __init__(
        self,
        scorer: ConfidenceScorer,
        dedup_store: 'DeduplicationStore',
        formatter: 'AlertFormatter',
        notifier: 'FeishuNotifier'
    ):
        self.scorer = scorer
        self.dedup = dedup_store
        self.formatter = formatter
        self.notifier = notifier
        
        # 置信度阈值（可配置）
        self.push_threshold = 70.0
        self.stage2_threshold = 60.0  # Stage2阈值可稍低
        
        # 追踪当前置信度（用于变化检测）
        self._current_scores: dict[str, float] = {}
        
    def process_signal(
        self, 
        alert: Stage1Alert, 
        state: SymbolState
    ) -> bool:
        """
        处理单个信号（事件驱动）
        返回: 是否推送了预警
        """
        # 1. 计算置信度
        score = self.scorer.score(alert, state)
        
        # 2. 检查是否应该推送
        if not self._should_push(alert, score):
            return False
            
        # 3. 检查去重
        if not self.dedup.should_notify(alert):
            return False
            
        # 4. 格式化并推送
        message = self.formatter.format_alert(alert, score)
        self.notifier.send(message)
        
        # 5. 记录推送
        self.dedup.mark_notified(alert)
        
        return True
    
    def _should_push(self, alert: Stage1Alert, score: ConfidenceScore) -> bool:
        """
        判断是否应该推送
        """
        # 检查是否首次出现高置信度
        key = f"{alert.symbol}:{alert.signal_type}"
        prev_score = self._current_scores.get(key, 0)
        
        # 首次达到阈值
        if score.total >= self.push_threshold and prev_score < self.push_threshold:
            self._current_scores[key] = score.total
            return True
            
        # 或者置信度大幅提升（从低到高）
        if score.total >= self.push_threshold and (score.total - prev_score) >= 20:
            self._current_scores[key] = score.total
            return True
            
        # 更新当前分数（即使没推送）
        self._current_scores[key] = score.total
        
        return False
```

#### push_controller.py - 推送控制器（新增）

**核心：改变推送逻辑从"时间驱动"到"事件驱动"**

```python
class PushController:
    """
    推送控制器
    
    策略：
    1. WebSocket数据持续更新内存缓存
    2. 每1分钟检查一次所有标的
    3. 只推送高置信度机会
    4. 不强制推送，等待真正的机会
    """
    
    def __init__(
        self,
        alert_manager: AlertManager,
        scan_interval: int = 60  # 1分钟检查一次
    ):
        self.alert_manager = alert_manager
        self.scan_interval = scan_interval
        
    def start(self, ws_manager: 'WebSocketManager'):
        """启动推送控制器"""
        self.ws_manager = ws_manager
        
        # 启动检查线程
        self._running = True
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()
        
    def stop(self):
        """停止"""
        self._running = False
        
    def _run(self):
        """检查循环"""
        while self._running:
            try:
                self._check_opportunities()
            except Exception as e:
                logger.error(f"Error checking opportunities: {e}")
            time.sleep(self.scan_interval)
            
    def _check_opportunities(self):
        """检查所有标的的机会"""
        for symbol in self._symbols:
            for timeframe in self._timeframes:
                # 从WebSocket缓存获取最新数据
                candles = self.ws_manager.get_cache(symbol, timeframe)
                if not candles:
                    continue
                    
                df = self._candles_to_df(candles)
                state = self._compute_state(df, symbol, timeframe)
                
                # 获取该标的历史统计
                history_stats = self.history_manager.get_stats_if_ready(symbol)
                
                # 评估所有信号
                for signal_def in self.registry.get_enabled_signals():
                    if self._check_signal(signal_def, state):
                        alert = self._create_alert(signal_def, state, history_stats)
                        self.alert_manager.process_signal(alert, state)
```

#### 推送策略对比

```
┌─────────────────────────────────────────────────────────────────────┐
│  旧策略：时间驱动                                                   │
│                                                                      │
│  while True:                                                       │
│      每5分钟:                                                      │
│          扫描 → 排序 → 推送Top N                                  │
│                                                                      │
│  问题: 5分钟内没有机会也推送，推送质量不稳定                        │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  新策略：置信度驱动 + 事件推送                                      │
│                                                                      │
│  # WebSocket线程持续更新数据                                        │
│  ws_manager.on_candle_update = update_cache                         │
│                                                                      │
│  # 推送控制器每分钟检查                                             │
│  while True:                                                       │
│      每1分钟:                                                      │
│          for 每个标的:                                             │
│              计算置信度                                            │
│              if 置信度 > 阈值:                                     │
│                  推送                                              │
│              else:                                                │
│                  不推送，继续监控                                   │
│                                                                      │
│  优势: 只有真正有机会才推送，推送质量高                              │
└─────────────────────────────────────────────────────────────────────┘
```

#### 置信度配置

```yaml
# configs/push.yaml

push:
  # 推送阈值（区分市场状态）
  threshold:
    # 趋势市场
    trend:
      stage1: 70    # Stage1推送阈值
      stage2: 60    # Stage2推送阈值
    # 震荡市场  
    range:
      stage1: 65    # 震荡市场阈值可稍低（机会更频繁）
      stage2: 55
    
  # 趋势市场评分权重
  weights:
    trend:
      trend_quality: 0.25         # ADX趋势强度
      timeframe_alignment: 0.25    # 多周期共振
      breakout_confidence: 0.20    # 突破确认
      volume_confirmation: 0.15    # 成交量确认
      history_context: 0.10       # 历史分位
      severity: 0.05              # 严重程度
      
    # 震荡市场评分权重
    range:
      extreme_level: 0.30          # RSI极值程度
      reversion_probability: 0.25   # 回归概率
      history_context: 0.20         # 历史分位
      volume_confirmation: 0.15     # 成交量确认
      timeframe_alignment: 0.05    # 多周期共振
      severity: 0.05              # 严重程度
  
  # 推送频率控制
  rate_limit:
    per_symbol_minutes: 30    # 同一标的至少30分钟推送一次
    per_scan_max: 5           # 每次检查最多推送5条
    
  # 扫描频率
  scan_interval_seconds: 60     # 每1分钟检查一次
```

#### 趋势 vs 震荡评分对比

```
┌─────────────────────────────────────────────────────────────────────┐
│  趋势市场 (ADX >= 25)                                               │
│                                                                      │
│  核心信号: 突破、动量、成交量爆发                                     │
│                                                                      │
│  评分维度:                                                          │
│  ├── 趋势质量 (25%)    ← ADX强度，最重要                            │
│  ├── 多周期共振 (25%)  ← 15m+1H+4H同时确认                         │
│  ├── 突破确认 (20%)    ← 价格突破+DI方向                            │
│  ├── 成交量确认 (15%)  ← 放量支持                                  │
│  ├── 历史分位 (10%)    ← 波动率位置                                │
│  └── 严重程度 (5%)     ← 高/中/低                                  │
│                                                                      │
│  推送条件:                                                          │
│  - 置信度 >= 70                                                    │
│  - ADX >= 25（确认趋势）                                           │
│  - 多周期共振                                                       │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  震荡市场 (ADX < 25)                                               │
│                                                                      │
│  核心信号: RSI极值、均值回归、价格偏离                                │
│                                                                      │
│  评分维度:                                                          │
│  ├── 极值程度 (30%)    ← RSI越极端越高                             │
│  ├── 回归概率 (25%)    ← BB位置+ADX低                              │
│  ├── 历史分位 (20%)    ← 历史极端位置更重要                          │
│  ├── 成交量确认 (15%)  ← 缩量回归更可靠                             │
│  ├── 多周期共振 (5%)   ← 次要                                      │
│  └── 严重程度 (5%)     ← 高/中/低                                  │
│                                                                      │
│  推送条件:                                                          │
│  - 置信度 >= 65（稍低，因为震荡机会更频繁）                         │
│  - ADX < 25（确认震荡）                                            │
│  - RSI处于极值区间 (<35 或 >65)                                    │
└─────────────────────────────────────────────────────────────────────┘
```

#### 推送示例

```
📈 趋势预警 (置信度 82/100)
🔴 [BTC/USDT:USDT] | 趋势 | 做多 | 成交量爆发
  趋势质量: 95 (ADX=42，强趋势)
  多周期共振: 85 (15m+1H共振)
  突破确认: 80 (+DI > -DI，ROC=1.2%)
  成交量: 90 (3.5x均量)
  → 市场状态: 趋势

📉 震荡预警 (置信度 75/100)
🟡 [ETH/USDT:USDT] | 震荡 | 做多 | RSI极值
  极值程度: 95 (RSI=23，极度超卖)
  回归概率: 80 (BB低位+ADX=18)
  历史分位: 85 (RSI历史5%分位)
  成交量: 60 (缩量回归)
  → 市场状态: 震荡
```

#### deduplication.py - 去重逻辑（持久化）

**职责**：解决进程重启后去重状态丢失的问题

```python
class DeduplicationStore:
    """去重状态持久化存储"""
    
    def __init__(self, storage: 'Storage'):
        self.storage = storage
    
    def was_recently_notified(
        self, 
        symbol: str, 
        stage: str | None = None,
        window_minutes: int = 30
    ) -> bool:
        """
        检查symbol是否在最近window_minutes内已推送
        - 查询数据库notification_log表
        - 进程重启后仍然有效
        """
        
    def mark_notified(
        self, 
        symbol: str, 
        stage: str, 
        signal_type: str
    ):
        """记录推送"""
        
    def cleanup_old_records(self, retention_days: int = 7):
        """清理过期记录"""
```

**设计决策**：
- 去重key：`symbol`（仅symbol，不含stage/regime）
- 窗口：30分钟（可配置）
- 持久化到数据库 `notification_log` 表

#### formatters.py - 格式化

**职责**：将Alert对象格式化为飞书消息

```python
class AlertFormatter:
    def format_stage1(self, alert: Stage1Alert) -> str:
        """格式化Stage1预警"""
        
    def format_stage2(self, signal: EntrySignal) -> str:
        """格式化Stage2入场"""
        
    def format_summary(self, stage1: list, stage2: list) -> str:
        """格式化合并摘要"""
```

### 3.5 通知层 (notification/)

#### feishu.py - 飞书客户端

**职责**：
- 长连接推送
- Webhook推送（备用）
- 静默时段控制

```python
class FeishuNotifier:
    def __init__(self, settings: 'Settings'):
        self.settings = settings
        self.client = self._init_client()
    
    def send(self, message: str):
        """发送消息"""
        
    def _send_via_api(self, message: str):
        """长连接API发送"""
        
    def _send_via_webhook(self, message: str):
        """Webhook发送"""
        
    def in_silent_hours(self) -> bool:
        """检查是否在静默时段"""
```

#### commands.py - 命令解析

**职责**：解析飞书命令并返回响应

```python
COMMAND_HANDLERS = {
    '状态': handle_status,
    '扫描': handle_scan,
    '预警': handle_recent_alerts,
    '排名': handle_ranking,
    '查看': handle_symbol_detail,
    '帮助': handle_help,
}

def parse_command(text: str) -> tuple[str, dict]:
    """解析命令，返回 (command, args)"""
```

### 3.6 核心调度 (core/)

#### scanner.py - 主扫描循环（WebSocket架构）

**职责**：
- 初始化所有组件
- 启动WebSocket实时数据流
- 控制扫描循环
- 处理信号
- 优雅退出

```python
class Scanner:
    def __init__(self, settings: 'Settings'):
        self.settings = settings
        self.exchange = ExchangeClient()
        self.storage = Storage(settings.db_path)
        self.cache = CacheManager(self.storage)
        self.ws_manager = None  # WebSocket管理器
        
        # 历史数据
        self.history = HistoryManager(self.storage, self.exchange)
        self.history_scheduler = HistoryScheduler(self.history)
        
        # 信号和预警
        self.signals = SignalRegistry()
        self.alerts = AlertManager(...)
        self.feishu = FeishuNotifier(settings)
        
        # 系统状态
        self._symbols = []
        
    def start(self):
        """启动系统"""
        # 1. 获取标的列表
        self._symbols, _ = self.exchange.fetch_top_symbols(n=self.settings.top_n)
        
        # 2. 启动WebSocket（实时数据）
        self.ws_manager = WebSocketManager(
            symbols=self._symbols,
            timeframes=self.settings.timeframes
        )
        self.ws_manager.on_candle_update = self._on_candle_update
        self.ws_manager.start()
        
        # 3. 预加载实时缓存（启动WebSocket后立即可用）
        self._preload_realtime_cache()
        
        # 4. 启动后台任务
        self._start_background_tasks()
        
    def _preload_realtime_cache(self):
        """预加载实时K线到内存（从DB恢复）"""
        for sym in self._symbols:
            for tf in self.settings.timeframes:
                # 从DB加载到内存（恢复WebSocket断连期间的数据）
                cached = self.storage.get_candles(sym, tf, limit=300)
                if cached:
                    self.ws_manager._cache[sym] = self.ws_manager._cache.get(sym, {})
                    self.ws_manager._cache[sym][tf] = cached
                    
    def _start_background_tasks(self):
        """启动后台任务（与主监控独立）"""
        # 历史数据下载（持续运行，有数据则跳过）
        Thread(target=self._history_download_loop, daemon=True, name='HistoryDownload').start()
        
        # 历史统计计算（依赖下载完成，独立运行）
        Thread(target=self._history_stats_loop, daemon=True, name='HistoryStats').start()
        
        # 兜底校准（每小时REST全量拉取）
        Thread(target=self._backup_sync_loop, daemon=True, name='BackupSync').start()
        
    def _history_download_loop(self):
        """历史数据下载循环（持续运行）"""
        while not self._shutdown:
            for symbol in self._symbols:
                if self._shutdown:
                    break
                if not self.history_manager.is_data_ready(symbol):
                    try:
                        self.history_manager.fetch_and_save_history(symbol)
                        logger.info(f"History downloaded for {symbol}")
                    except Exception as e:
                        logger.warning(f"Failed to download {symbol}: {e}")
            # 检查完成后再等待一段时间
            time.sleep(3600)  # 每小时检查一次
            
    def _history_stats_loop(self):
        """历史统计计算循环"""
        while not self._shutdown:
            time.sleep(3600)  # 每小时检查一次
            for symbol in self._symbols:
                if self._shutdown:
                    break
                if self.history_manager.needs_stats_update(symbol):
                    try:
                        self.history_manager.compute_and_save_stats(symbol)
                        logger.info(f"Stats computed for {symbol}")
                    except Exception as e:
                        logger.warning(f"Failed to compute stats for {symbol}: {e}")
        
    def _on_candle_update(self, symbol: str, timeframe: str, candle: dict):
        """WebSocket K线更新回调"""
        # 更新数据库（异步）
        self.storage.append_candle(symbol, timeframe, candle)
        
    def run_once(self):
        """执行一次扫描（从内存读取数据，无API等待）"""
        # 1. 获取标的列表（已有）
        # 2. 从WebSocket缓存读取数据（毫秒级）
        data_by_symbol = {}
        for sym in self._symbols:
            data_by_symbol[sym] = {}
            for tf in self.settings.timeframes:
                candles = self.ws_manager.get_cache(sym, tf)
                if candles:
                    df = self._candles_to_df(candles)
                    data_by_symbol[sym][tf] = df
                    
        # 3. 加载历史统计（从symbol_stats表）
        history_stats = self.history.get_all_stats()
        
        # 4. 计算指标（含历史分位）
        # 5. 生成信号
        # 6. 处理预警
        # 7. 保存快照
        # → 全部在内存中完成，无API等待
        
    def run_loop(self):
        """无限循环扫描（每5分钟）"""
        while not self._shutdown:
            time.sleep(self.settings.scan_interval)
            self.run_once()
            
    def _history_refresh_loop(self):
        """历史统计刷新循环（每周）"""
        while not self._shutdown:
            time.sleep(7 * 24 * 3600)  # 每周
            self.history_scheduler.refresh_all_stats(self._symbols)
            
    def _backup_sync_loop(self):
        """兜底同步循环（每小时）"""
        while not self._shutdown:
            time.sleep(3600)  # 每小时
            self._full_sync()
            
    def _full_sync(self):
        """全量同步（兜底）"""
        # 通过REST API全量拉取，确保数据一致性
        logger.info("Running full sync via REST API...")
        
    def shutdown(self):
        """优雅退出"""
        self._shutdown = True
        if self.ws_manager:
            self.ws_manager.stop()
```

**架构对比**：

```
┌─────────────────────────────────────────────────────────────────────┐
│  旧架构（轮询）                                                     │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  每5分钟:                                                     │ │
│  │  1. fetch_top_symbols()          ~10秒                        │ │
│  │  2. fetch_all_symbols_data()    ~80秒  ← 最大瓶颈            │ │
│  │  3. 计算指标                    ~5秒                          │ │
│  │  4. 生成信号                    ~1秒                          │ │
│  │  ────────────────────────────────────────────────────────────  │ │
│  │  总计: ~100秒                                              │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
├─────────────────────────────────────────────────────────────────────┤
│  新架构（WebSocket）                                                │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  启动时 (一次性):                                              │ │
│  │  1. 建立WebSocket连接          ~1秒                           │ │
│  │  2. 订阅600个K线频道          ~1秒                           │ │
│  │  3. 预加载历史数据到内存       ~30秒                         │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  WebSocket线程 (持续运行):                                     │ │
│  │  - 接收K线推送 → 更新内存缓存 → 异步写DB                      │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  主扫描 (每5分钟):                                             │ │
│  │  1. 从内存读取数据             ~0.1秒  ← 直接读缓存            │ │
│  │  2. 计算指标                   ~5秒                           │ │
│  │  3. 生成信号                   ~1秒                           │ │
│  │  ────────────────────────────────────────────────────────────  │ │
│  │  总计: ~6秒 (无API等待)                                       │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  后台任务 (每小时/每周):                                       │ │
│  │  - 兜底全量同步 (REST)                                        │ │
│  │  - 历史统计刷新                                                │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

**性能提升**：

| 指标 | 旧架构 | 新架构 | 提升 |
|------|--------|--------|------|
| 主扫描耗时 | ~100秒 | ~6秒 | **17x** |
| 数据实时性 | 5分钟 | 秒级 | **300x** |
| API调用量 | 600次/扫描 | ~0次/扫描 | **600x** |

#### lifecycle.py - 生命周期管理

**职责**：系统生命周期管理

```python
class LifecycleManager:
    def on_startup(self):
        """启动时执行"""
        
    def on_shutdown(self):
        """关闭时执行"""
        
    def register_signal_handlers(self):
        """注册信号处理器（SIGINT/SIGTERM）"""
```

### 3.7 工具层 (utils/)

#### logging.py - 日志配置

**职责**：
- 日志轮转（RotatingFileHandler）
- 多级别输出（文件+控制台）
- 结构化格式

```python
def setup_logging(
    level: str = 'INFO',
    log_file: str = 'logs/scanner.log',
    rotation: str = 'daily',
    retention_days: int = 30
):
    """配置日志系统"""
```

#### health.py - 健康检查

**职责**：系统健康状态检查

```python
class HealthChecker:
    def check(self) -> dict:
        """返回健康状态"""
        return {
            'status': 'healthy',  # healthy | degraded | unhealthy
            'checks': {
                'database': self._check_db(),
                'exchange': self._check_exchange(),
                'last_scan': self._check_last_scan(),
            },
            'metrics': {
                'db_size_mb': ...,
                'symbols_count': ...,
                'avg_scan_time': ...,
            }
        }
    
    def _check_db(self) -> dict:
        """数据库健康检查"""
        
    def _check_exchange(self) -> dict:
        """交易所连通性检查"""
        
    def _check_last_scan(self) -> dict:
        """上次扫描时间检查"""
```

---

## 4. 数据模型

### 4.1 数据库Schema

```sql
-- 标的列表
CREATE TABLE symbols (
    symbol TEXT PRIMARY KEY,
    volume_24h REAL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 指标快照（实时扫描用）
CREATE TABLE snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timeframe TEXT,
    timestamp DATETIME,
    close REAL, roc REAL, rsi REAL, adx REAL,
    bb_width REAL, bb_width_pct REAL, atr REAL,
    volume_ratio REAL, ma_converge REAL,
    trend_score INTEGER,
    regime TEXT,
    direction TEXT,
    signal_strength INTEGER,
    UNIQUE(symbol, timeframe, timestamp)
);

-- 历史K线（长期存储，1-2年）
CREATE TABLE history_candles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timeframe TEXT,
    timestamp DATETIME,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    UNIQUE(symbol, timeframe, timestamp)
);

-- 统计指标快照（每周计算一次）
CREATE TABLE symbol_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timeframe TEXT,
    computed_at DATETIME,
    volatility_stats TEXT,       -- JSON
    return_stats TEXT,           -- JSON
    volume_stats TEXT,           -- JSON
    regime_stats TEXT,           -- JSON
    UNIQUE(symbol, timeframe, computed_at)
);

-- 预警记录
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    stage TEXT,
    regime TEXT,
    direction TEXT,
    signal_type TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    signal_strength INTEGER,
    roc REAL, rsi REAL, adx REAL,
    bb_width_pct REAL, volume_ratio REAL,
    ranking INTEGER,
    notified INTEGER DEFAULT 0
);

-- 推送记录（去重持久化）
CREATE TABLE notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    stage TEXT,
    signal_type TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, timestamp)
);

-- 系统状态
CREATE TABLE system_status (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX idx_snapshots_symbol_tf ON snapshots(symbol, timeframe);
CREATE INDEX idx_history_symbol_tf ON history_candles(symbol, timeframe, timestamp);
CREATE INDEX idx_stats_symbol_computed ON symbol_stats(symbol, computed_at DESC);
CREATE INDEX idx_alerts_symbol_stage ON alerts(symbol, stage);
CREATE INDEX idx_notification_symbol ON notification_log(symbol, timestamp);
CREATE INDEX idx_symbols_volume ON symbols(volume_24h DESC);
```

### 4.2 配置Schema (YAML)

```yaml
# configs/default.yaml
data:
  exchange: okx
  top_n: 200
  timeframes: ['15m', '1h', '4h']

history:
  enabled: true
  timeframe: '4h'                # 历史数据主要用4h
  retention_days: 730            # 保留2年
  refresh_interval_days: 7       # 每周刷新统计
  fetch_workers: 5               # 并发获取线程数

scanner:
  interval_seconds: 300
  historical_bars: 100
  cache_retention_days: 7

indicators:
  roc_periods:
    '15m': 5
    '1h': 10
    '4h': 20
  rsi_period: 14
  adx_period: 14

stage1:
  bb_width_pct_threshold: 20
  ma_converge_threshold: 0.5
  volume_contraction: 0.5
  consolidation_bars: 20
  volume_spike: 5.0

stage2:
  breakout_volume: 2.0
  roc_entry_short: 0.5
  roc_entry_mid: 1.0
  stop_loss_trend: 2.0
  stop_loss_range: 1.5

alert:
  dedup_window_minutes: 30
  dedup_volatile_minutes: 60
  long_top_n: 20
  short_top_n: 10

feishu:
  enabled: true
  app_id: ''
  app_secret: ''
  chat_id: ''
  long_connection: true
  silent_hours: []

logging:
  level: INFO
  rotation: daily
  retention_days: 30

database:
  path: data/screening.db
  snapshot_retention_days: 90
  alert_retention_days: 180
```

---

## 5. 接口设计

### 5.1 飞书命令接口

| 命令 | 响应 | 数据来源 |
|------|------|----------|
| `状态` | 系统状态摘要 | HealthChecker |
| `扫描` | 确认消息 | Scanner.run_once() |
| `预警` | 最近8条预警 | notification_log |
| `排名` | Top10多空 | snapshots |
| `查看 BTC` | 标的详情 | snapshots + symbol_stats |
| `统计 BTC` | 历史统计 | symbol_stats |
| `帮助` | 命令列表 | - |

### 5.2 健康检查接口

```
GET /health  # 返回JSON
{
  "status": "healthy",
  "timestamp": "2026-03-21T10:00:00Z",
  "checks": {
    "database": {"status": "ok", "latency_ms": 5},
    "exchange": {"status": "ok", "latency_ms": 120},
    "last_scan": {"status": "ok", "age_seconds": 280}
  },
  "metrics": {
    "symbols_count": 200,
    "db_size_mb": 45.2,
    "avg_scan_time": 95.3
  }
}
```

---

## 6. 部署设计

### 6.1 Docker Compose

```yaml
services:
  scanner:
    build: .
    restart: unless-stopped
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    env_file:
      - .env
    healthcheck:
      test: ["CMD", "python", "scripts/healthcheck.py"]
      interval: 60s
      timeout: 10s
      retries: 3
```

### 6.2 环境变量

```bash
# .env
SCREENER_EXCHANGE=okx
SCREENER_TOP_N=200
SCREENER_SCAN_INTERVAL=300
SCREENER_FEISHU_APP_ID=cli_xxx
SCREENER_FEISHU_APP_SECRET=xxx
SCREENER_FEISHU_CHAT_ID=oc_xxx
SCREENER_LOG_LEVEL=INFO
SCREENER_DB_PATH=data/screening.db
```

---

## 7. 迁移计划

### Phase 1: 项目结构（1天）
1. 创建 `src/` 包结构
2. 移动现有代码到对应模块
3. 创建 `tests/` 目录
4. 设置 `pyproject.toml`

### Phase 2: WebSocket模块（2天）⭐ 性能关键
1. 实现 `WebSocketManager` 连接管理
2. 实现订阅和数据解析
3. 实现内存缓存同步
4. 实现断连重连机制
5. 集成到主扫描流程

### Phase 3: 历史数据模块（3天）
1. 设计并创建 `history_candles` 和 `symbol_stats` 表
2. 实现 `HistoryManager` 数据获取（分页+增量）
3. 实现统计计算（波动率/收益率/成交量分位）
4. **实现异步解耦：主系统不等待历史数据**
5. 实现 `HistoryDownloader` 后台下载
6. 实现定期刷新（每周）

### Phase 4: 信号灵活性框架（2天）⭐ 迭代核心
1. 实现 `SignalRegistry` 信号注册表
2. 实现 `SignalDefinition` 配置化信号定义
3. 实现 `SignalEvaluator` 信号评估引擎
4. 创建 `signals.yaml` 配置文件
5. 迁移现有9种信号到新框架
6. 实现自定义信号注册接口

### Phase 5: 置信度评分 + 智能推送（2天）⭐ 推送质量
1. 实现 `ConfidenceScorer` 置信度评分引擎
2. 实现 `PushController` 推送控制器
3. 实现多维度评分（信号强度/历史分位/多周期共振等）
4. 配置推送阈值和权重
5. 实现事件驱动推送（替代固定时间推送）

### Phase 6: 核心修复（2天）
1. 实现 `CacheManager.cleanup()`
2. 实现 `DeduplicationStore` 持久化
3. 修复蜡烛缓存清理
4. 更新标的列表刷新策略（每小时）

### Phase 7: 配置层（1天）
1. 实现 Pydantic Settings
2. 创建 YAML 配置文件
3. 迁移所有参数到配置层
4. 添加配置验证

### Phase 8: 可观测性（1天）
1. 实现日志轮转
2. 实现 `HealthChecker`
3. 添加健康检查端点
4. 添加性能指标

### Phase 9: 测试（2天）
1. 编写指标计算单元测试
2. 编写去重逻辑测试
3. 编写集成测试
4. 添加CI/CD

---

## 8. 信号迭代指南

### 8.1 添加新信号

```yaml
# configs/signals.yaml
signals:
  new_signal:
    display_name: 新信号名称
    description: 信号描述
    category: trend  # trend | range | momentum | volume | custom
    direction: long  # long | short | neutral
    
    # 触发条件（AND关系）
    conditions:
      - indicator: rsi
        operator: '<='
        value: 35
      - indicator: adx
        operator: '>='
        value: 20
        
    # 历史分位条件（可选）
    history_conditions:
      - indicator: rsi
        percentile: 30
        direction: below
        
    # 严重程度规则
    severity_rules:
      - condition: "rsi <= 25"
        severity: high
      - condition: "rsi <= 35"
        severity: medium
```

### 8.2 调整信号阈值

```yaml
# 只需修改配置，无需改代码
signals:
  rsi_extreme:
    conditions:
      - indicator: rsi
        operator: '<='
        value: 30  # 从35调整为30，更严格
```

### 8.3 启用/禁用信号

```yaml
signals:
  bb_width_squeeze:
    enabled: true  # true = 启用，false = 禁用
```

### 8.4 历史分位增强

```yaml
signals:
  volume_spike:
    # 基础条件：成交量放大
    conditions:
      - indicator: volume_ratio
        operator: '>='
        value: 3.0
        
    # 历史分位：当前成交量处于历史高位
    history_conditions:
      - indicator: volume
        percentile: 80  # 高于历史80%的时间
        direction: above
```

### 8.5 信号迭代流程

```
┌─────────────────────────────────────────────────────────────────────┐
│  迭代流程                                                          │
│                                                                      │
│  1. 分析        → 分析实盘表现，找出需要调整的信号                    │
│       ↓                                                          │
│  2. 配置        → 修改 signals.yaml                                │
│       ↓                                                          │
│  3. 测试        → 用历史数据回测验证                                │
│       ↓                                                          │
│  4. 上线        → 重新加载配置或重启服务                             │
│       ↓                                                          │
│  5. 监控        → 观察新信号表现                                    │
│       ↓                                                          │
│  6. 迭代        → 回到步骤1                                        │
└─────────────────────────────────────────────────────────────────────┘
```

### Phase 7: 测试（2天）
1. 编写指标计算单元测试
2. 编写去重逻辑测试
3. 编写集成测试
4. 添加CI/CD

---

## 8. 风险与决策

### 8.1 已知风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 重构破坏现有功能 | 高 | 保留原代码，渐进迁移 |
| 飞书API变更 | 中 | 抽象通知层，支持切换 |
| 数据库迁移 | 中 | 脚本备份+回滚 |
| WebSocket断连 | 中 | 指数退避重连 + REST兜底 |
| WebSocket数据丢失 | 低 | 每小时REST全量校准 |

### 8.2 设计决策

1. **为什么用Pydantic Settings而不是直接用类？**
   - 环境变量支持，便于12-Factor部署
   - 自动验证，减少配置错误

2. **为什么不引入ORM？**
   - 当前数据量小（<100万行）
   - SQLite+SQL足够简单高效

3. **为什么保留单表而非分表？**
   - 标的数量固定（200个）
   - 分表增加复杂度，收益不明显

---

## 9. 附录

### 9.1 文件映射（旧→新）

| 旧文件 | 新位置 |
|--------|--------|
| main.py | core/scanner.py |
| config.py | config/settings.py + config/indicators.py |
| data_loader.py | data/exchange.py |
| - | **data/websocket.py**（新增） |
| database.py | data/storage.py |
| - | **data/history.py**（新增） |
| monitor.py | signals/stage1.py |
| entry_signal.py | signals/stage2.py |
| alerter.py | alerts/manager.py |
| feishu_client.py | notification/feishu.py |

### 9.2 依赖清单

```
# requirements.txt
pandas>=2.0
numpy>=1.24
ccxt>=4.0
requests>=2.28
lark-oapi>=1.0
pydantic>=2.0
pydantic-settings>=2.0
PyYAML>=6.0
websocket-client>=1.0  # WebSocket客户端（新增）

# requirements-dev.txt
pytest>=7.0
pytest-asyncio>=0.21
pytest-cov>=4.0
black>=23.0
ruff>=0.1
```

### 9.3 待讨论事项

1. 是否需要支持多交易所（Binance/Bybit）？
2. 是否需要回测模块？
3. 是否需要Web UI？
4. 是否需要Alert历史查询API？

---

## 10. 历史数据模块详解

### 10.1 设计背景

当前系统仅有最近100-300根K线，无法进行以下判断：
- 当前波动率处于历史什么位置？（低波动压缩还是高波动扩张）
- 当前涨跌幅是否接近历史极限？
- 成交量是否异常放大/缩小？

历史统计是判断"当前状态是否极端"的关键依据。

### 10.2 数据规模估算

以4h timeframe为例，2年数据量：

| 标的数 | 每天K线数 | 2年K线数 | 每行大小 | 总大小 |
|--------|-----------|----------|---------|--------|
| 200 | 6 | 4380 | ~80 bytes | ~67 MB |

考虑到索引和冗余，预估总存储 **100-150 MB**，完全可接受。

### 10.3 更新策略

```
┌─────────────────────────────────────────────────────────────┐
│                      Scanner 主循环                         │
│  每5分钟执行一次 → 扫描200标的 → 生成预警                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   HistoryScheduler                           │
│  检查是否需要刷新（每周一次）→ 触发后台刷新                   │
│                                                              │
│  首次运行：获取全部历史数据（2年），计算统计                  │
│  后续运行：增量获取新K线，更新统计                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      后台线程                               │
│  ThreadPoolExecutor(5 workers)                              │
│  → fetch_historical_candles                                 │
│  → compute_all_stats                                        │
│  → save_stats                                               │
│                                                              │
│  预估耗时：200标的 × 2年数据 ≈ 30-60分钟（首次）             │
│  后续增量：~5-10分钟/周                                       │
└─────────────────────────────────────────────────────────────┘
```

### 10.4 统计指标计算公式

#### 波动率分位

```python
def calc_volatility_percentile(current: float, historical: list[float]) -> float:
    """计算当前值在历史序列中的分位"""
    if not historical:
        return 50.0
    sorted_hist = sorted(historical)
    # 计算当前值在历史中的位置
    rank = sum(1 for v in sorted_hist if v < current)
    percentile = (rank / len(sorted_hist)) * 100
    return round(percentile, 1)

# 示例：ATR分位
atr_current = 0.005
atr_history = [0.001, 0.002, 0.003, 0.004, 0.005, 0.006, 0.008, 0.010]
# 当前0.005，排在第5位，分位 = 5/8 * 100 = 62.5%
```

#### 最大涨跌幅

```python
def calc_max_return(df: pd.DataFrame, periods: list[int]) -> dict:
    """计算历史最大涨跌幅"""
    results = {}
    for period in periods:
        if len(df) > period:
            returns = df['close'].pct_change(period).dropna()
            results[f'max_up_{period}d'] = round(returns.max() * 100, 2)
            results[f'max_down_{period}d'] = round(returns.min() * 100, 2)
    return results
```

### 10.5 与信号层的集成

```python
# signals/stage1.py - 扩展信号检测

def check_bb_width_squeeze(state, history_stats):
    """波动率压缩检测 - 使用历史分位"""
    bb_pct = state.d.get('bb_width_pct')
    
    if history_stats:
        bb_history = history_stats.get('bb_width', {})
        current_pct = bb_history.get('current', 0)
        historical_pct = bb_history.get('percentile', 50)
        
        # 原始判断
        if bb_pct <= BB_WIDTH_THRESHOLD:
            # 增强判断：当前处于历史低位分位
            if historical_pct <= 20:
                return {'severity': 'high', 'context': '历史低波动'}
            elif historical_pct <= 30:
                return {'severity': 'medium', 'context': '波动率偏低'}
    
    return None

# signals/stage2.py - 入场校准

def calibrate_stop_loss(entry_price, atr, history_stats):
    """根据历史ATR分位校准止损"""
    if not history_stats:
        return entry_price - atr * STOP_LOSS_MULTIPLIER
    
    atr_historical_pct = history_stats.get('atr', {}).get('percentile', 50)
    
    # 高波动环境 → 扩大止损
    if atr_historical_pct > 80:
        multiplier = STOP_LOSS_MULTIPLIER * 1.3
    # 低波动环境 → 收紧止损
    elif atr_historical_pct < 20:
        multiplier = STOP_LOSS_MULTIPLIER * 0.8
    else:
        multiplier = STOP_LOSS_MULTIPLIER
    
    return entry_price - atr * multiplier
```

### 10.6 飞书统计查询示例

```
用户：统计 BTC
系统：
📊 BTC/USDT 历史统计 (4h)
更新时间: 2026-03-21 09:00

波动率状态:
  ATR当前: 0.0052 BTC
  ATR历史分位: 62.5% (适中)
  BB Width分位: 8.2% ⚠️ (极低波动压缩)
  标准差分位: 45.0%

收益率统计:
  近24h最大涨幅: 8.5%
  近24h最大跌幅: -12.3%
  近7天极值: +25.0% / -18.0%
  ROC历史分位: 72.3%

成交量状态:
  当前/均值比: 0.8x (缩量)
  成交量分位: 35.0%

市场状态:
  趋势占比: 65%
  震荡占比: 35%
  平均ADX: 28.5
  → 当前处于趋势市场
```

---

## 11. 架构总结

### 11.1 系统全貌

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Opportunity Screening System                  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  数据层 (Data)                                                │  │
│  │                                                               │  │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐       │  │
│  │  │  WebSocket  │    │    REST    │    │   Storage   │       │  │
│  │  │  (实时)     │    │   (兜底)    │    │   (SQLite) │       │  │
│  │  │  OKX K线    │    │  历史补全    │    │  实时+历史  │       │  │
│  │  └─────────────┘    └─────────────┘    └─────────────┘       │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│                              ▼                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  缓存层 (Cache)                                             │  │
│  │  ┌─────────────────────────────────────────────────────────┐  │  │
│  │  │  内存缓存 (实时K线)  │  历史统计 (分位/极值)          │  │  │
│  │  │  WebSocket更新      │  后台异步计算                    │  │  │
│  │  └─────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│                              ▼                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  信号层 (Signals)                                            │  │
│  │                                                               │  │
│  │  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐   │  │
│  │  │ SignalRegistry│  │SignalEvaluator │  │  Confidence    │   │  │
│  │  │ (信号注册表)  │  │ (信号评估)    │  │   Scorer      │   │  │
│  │  │ YAML配置      │  │ 条件组合      │  │ (置信度评分)  │   │  │
│  │  └───────────────┘  └───────────────┘  └───────────────┘   │  │
│  │                                                               │  │
│  │  Stage1 预警监测  │  Stage2 入场确认                        │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│                              ▼                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  预警层 (Alerts)                                             │  │
│  │                                                               │  │
│  │  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐   │  │
│  │  │    Push      │  │  Deduplication │  │  Formatter    │   │  │
│  │  │ Controller   │  │   (去重)       │  │  (格式化)     │   │  │
│  │  │ 事件驱动推送 │  │ 持久化存储    │  │ 飞书消息      │   │  │
│  │  └───────────────┘  └───────────────┘  └───────────────┘   │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│                              ▼                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  通知层 (Notification)                                        │  │
│  │                                                               │  │
│  │  ┌─────────────────┐    ┌─────────────────┐                   │  │
│  │  │    Feishu      │    │    Commands     │                   │  │
│  │  │ 长连接API推送   │    │   命令解析      │                   │  │
│  │  └─────────────────┘    └─────────────────┘                   │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 11.2 核心特性

| 特性 | 实现 | 状态 |
|------|------|------|
| **实时数据** | WebSocket连接OKX，秒级延迟 | ✅ |
| **历史统计** | 后台异步计算，长中短多窗口 | ✅ |
| **信号灵活配置** | YAML配置，动态注册 | ✅ |
| **置信度评分** | 趋势/震荡区分，多维度 | ✅ |
| **智能推送** | 事件驱动，阈值触发 | ✅ |
| **去重持久化** | 数据库存储，重启不丢 | ✅ |
| **多市场扩展** | 接口预留，可配置切换 | 🔜 |

### 11.3 性能指标

| 指标 | 当前 | 优化后 |
|------|------|--------|
| 扫描耗时 | ~100秒 | <10秒 |
| 数据实时性 | 5分钟 | 秒级 |
| API调用量 | 600次/扫描 | ≈0 |
| 推送质量 | 固定Top N | 高置信度触发 |

### 11.4 迭代优先级

```
Phase 1-2: 基础设施
├── WebSocket实时数据
└── 项目结构重构

Phase 3-4: 核心功能
├── 历史数据统计
└── 信号灵活配置

Phase 5-6: 智能推送
├── 置信度评分
└── 核心修复

Phase 7-9: 工程化
├── 配置层
├── 可观测性
└── 测试
```

### 11.5 扩展预留

```
当前: OKX 永续合约

接口预留:
├── ExchangeAdapter 抽象
├── MarketDataSource 接口
└── 多市场配置

未来可扩展:
├── Binance 合约/现货
├── A股 实时行情
└── 美股 Yahoo Finance
```
