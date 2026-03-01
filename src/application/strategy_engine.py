"""策略引擎 - 策略管理和执行"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Dict, Callable

from loguru import logger

from ..domain.strategies import (
    TradingStrategy,
    Signal,
    StrategyContext,
    StrategyConfig,
    SpreadArbitrageStrategy,
    OrderBookImbalanceStrategy,
    SimpleTrendStrategy,
    CompositeStrategy,
)
from ..domain.entities import Market
from ..domain.events import StrategySignalEvent
from ..infrastructure.polymarket_client import PolymarketClient


@dataclass
class BacktestResult:
    """回测结果"""
    strategy_name: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal
    total_pnl: Decimal
    max_drawdown: Decimal
    sharpe_ratio: Decimal


@dataclass
class EngineConfig:
    """引擎配置"""
    check_interval_seconds: int = 30
    max_concurrent_signals: int = 3
    min_signal_confidence: Decimal = Decimal("0.55")
    enable_backtest: bool = False


class SignalFilter:
    """信号过滤器"""
    
    def __init__(self, min_confidence: Decimal = Decimal("0.55")):
        self.min_confidence = min_confidence
        self._recent_signals: Dict[str, datetime] = {}
        self._cooldown_seconds = 60  # 同一市场信号冷却时间
    
    def filter(self, signal: Signal) -> bool:
        """
        过滤信号
        
        Returns:
            bool: True 表示通过过滤
        """
        # 置信度检查
        if signal.confidence < self.min_confidence:
            return False
        
        # 有效期检查
        if not signal.is_valid():
            return False
        
        # 冷却检查
        now = datetime.now()
        last_signal = self._recent_signals.get(signal.market_id)
        
        if last_signal:
            elapsed = (now - last_signal).total_seconds()
            if elapsed < self._cooldown_seconds:
                logger.debug(f"Signal filtered: cooldown active for {signal.market_id}")
                return False
        
        # 记录信号时间
        self._recent_signals[signal.market_id] = now
        return True


class StrategyEngine:
    """策略引擎"""
    
    def __init__(
        self,
        config: Optional[EngineConfig] = None,
        polymarket_client: Optional[PolymarketClient] = None
    ):
        self.config = config or EngineConfig()
        self.polymarket = polymarket_client
        
        # 策略管理
        self._strategies: List[TradingStrategy] = []
        self._composite: Optional[CompositeStrategy] = None
        
        # 信号处理
        self._signal_filter = SignalFilter(self.config.min_signal_confidence)
        self._signal_handlers: List[Callable[[Signal], None]] = []
        
        # 状态
        self._running = False
        self._price_history: Dict[str, List] = {}  # 价格历史
        self._signals_generated: List[Signal] = []
    
    def register_strategy(self, strategy: TradingStrategy) -> None:
        """注册策略"""
        self._strategies.append(strategy)
        logger.info(f"Strategy registered: {strategy.name}")
    
    def create_default_strategies(self) -> None:
        """创建默认策略组合"""
        # 价差套利
        spread_config = StrategyConfig(
            enabled=True,
            min_confidence=Decimal("0.60"),
            signal_expiry_seconds=300,
        )
        spread_strategy = SpreadArbitrageStrategy(spread_config)
        self.register_strategy(spread_strategy)
        
        # 订单簿不平衡
        imbalance_config = StrategyConfig(
            enabled=True,
            min_confidence=Decimal("0.55"),
            signal_expiry_seconds=600,
        )
        imbalance_strategy = OrderBookImbalanceStrategy(imbalance_config)
        self.register_strategy(imbalance_strategy)
        
        # 趋势跟踪
        trend_config = StrategyConfig(
            enabled=True,
            min_confidence=Decimal("0.58"),
            signal_expiry_seconds=900,
        )
        trend_strategy = SimpleTrendStrategy(trend_config)
        self.register_strategy(trend_strategy)
        
        # 创建组合策略
        self._composite = CompositeStrategy(self._strategies)
        logger.info(f"Created composite strategy with {len(self._strategies)} components")
    
    def add_signal_handler(self, handler: Callable[[Signal], None]) -> None:
        """添加信号处理器"""
        self._signal_handlers.append(handler)
    
    async def analyze_market(self, market: Market) -> Optional[Signal]:
        """
        分析单个市场
        
        Args:
            market: 市场数据
            
        Returns:
            Optional[Signal]: 生成的信号
        """
        if not market.is_tradable():
            return None
        
        # 获取订单簿
        if self.polymarket and not market.orderbook:
            async with self.polymarket:
                market.orderbook = await self.polymarket.get_orderbook(market.market_id)
        
        # 构建上下文
        context = StrategyContext(
            market=market,
            price_history=self._price_history.get(market.market_id, []),
        )
        
        # 使用组合策略生成信号
        if self._composite:
            signal = self._composite.generate_signal(context)
        else:
            # 如果没有组合策略，使用第一个可用策略
            signal = None
            for strategy in self._strategies:
                if strategy.enabled:
                    signal = strategy.generate_signal(context)
                    if signal:
                        break
        
        if signal and self._signal_filter.filter(signal):
            self._signals_generated.append(signal)
            
            # 触发事件
            event = StrategySignalEvent(
                strategy_id=signal.strategy_id,
                market_id=signal.market_id,
                signal=signal.action.value,
                confidence=signal.confidence,
                reason=signal.reason
            )
            
            logger.info(f"Signal generated: {signal.action.value} for {signal.market_id} "
                       f"(confidence={signal.confidence:.2%})")
            
            # 调用处理器
            for handler in self._signal_handlers:
                try:
                    handler(signal)
                except Exception as e:
                    logger.error(f"Signal handler error: {e}")
            
            return signal
        
        return None
    
    async def analyze_all_markets(self, markets: Optional[List[Market]] = None) -> List[Signal]:
        """
        分析所有市场
        
        Args:
            markets: 市场列表，None 则自动获取
            
        Returns:
            List[Signal]: 生成的信号列表
        """
        if markets is None and self.polymarket:
            async with self.polymarket:
                markets = await self.polymarket.get_markets()
        
        if not markets:
            return []
        
        signals = []
        
        for market in markets:
            try:
                signal = await self.analyze_market(market)
                if signal:
                    signals.append(signal)
            except Exception as e:
                logger.error(f"Error analyzing market {market.market_id}: {e}")
                continue
        
        logger.info(f"Analysis complete: {len(signals)} signals from {len(markets)} markets")
        return signals
    
    async def run_continuous(self, interval_seconds: Optional[int] = None) -> None:
        """
        持续运行策略引擎
        
        Args:
            interval_seconds: 检查间隔，None 使用配置默认值
        """
        interval = interval_seconds or self.config.check_interval_seconds
        self._running = True
        
        logger.info(f"Strategy engine started (interval={interval}s)")
        
        while self._running:
            try:
                signals = await self.analyze_all_markets()
                
                if signals:
                    logger.info(f"Generated {len(signals)} signals in this cycle")
                
                await asyncio.sleep(interval)
                
            except Exception as e:
                logger.error(f"Engine error: {e}")
                await asyncio.sleep(interval)
        
        logger.info("Strategy engine stopped")
    
    def stop(self) -> None:
        """停止引擎"""
        self._running = False
    
    def get_statistics(self) -> Dict:
        """获取引擎统计信息"""
        return {
            "strategies_registered": len(self._strategies),
            "signals_generated_total": len(self._signals_generated),
            "signals_by_strategy": self._count_signals_by_strategy(),
            "running": self._running,
        }
    
    def _count_signals_by_strategy(self) -> Dict[str, int]:
        """按策略统计信号数量"""
        counts = {}
        for signal in self._signals_generated:
            strategy = signal.strategy_id
            counts[strategy] = counts.get(strategy, 0) + 1
        return counts
    
    def update_price_history(self, market_id: str, price) -> None:
        """更新价格历史"""
        if market_id not in self._price_history:
            self._price_history[market_id] = []
        
        self._price_history[market_id].append(price)
        
        # 保留最近100个数据点
        if len(self._price_history[market_id]) > 100:
            self._price_history[market_id] = self._price_history[market_id][-100:]
    
    def run_backtest(
        self,
        strategy: TradingStrategy,
        historical_data: List,
        initial_capital: Decimal = Decimal("1000")
    ) -> BacktestResult:
        """
        运行回测
        
        Args:
            strategy: 要回测的策略
            historical_data: 历史市场数据
            initial_capital: 初始资金
            
        Returns:
            BacktestResult: 回测结果
        """
        logger.info(f"Starting backtest for {strategy.name}")
        
        capital = initial_capital
        trades = []
        
        for data in historical_data:
            # 构建上下文
            context = StrategyContext(
                market=data,
                price_history=self._price_history.get(data.market_id, []),
                portfolio_value=capital,
            )
            
            # 生成信号
            signal = strategy.generate_signal(context)
            
            if signal:
                # 模拟执行
                trade_result = self._simulate_trade(signal, data, capital)
                trades.append(trade_result)
                capital += trade_result.get("pnl", Decimal("0"))
        
        # 计算指标
        winning_trades = sum(1 for t in trades if t.get("pnl", 0) > 0)
        losing_trades = len(trades) - winning_trades
        total_pnl = sum(t.get("pnl", Decimal("0")) for t in trades)
        
        win_rate = Decimal(winning_trades) / len(trades) if trades else Decimal("0")
        
        return BacktestResult(
            strategy_name=strategy.name,
            total_trades=len(trades),
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            total_pnl=total_pnl,
            max_drawdown=Decimal("0"),  # TODO: 计算最大回撤
            sharpe_ratio=Decimal("0"),  # TODO: 计算夏普比率
        )
    
    def _simulate_trade(self, signal: Signal, market_data, capital: Decimal) -> Dict:
        """模拟交易执行"""
        # 简化的模拟执行
        size = min(signal.suggested_size, capital * Decimal("0.1"))
        
        # 假设以建议价格成交
        entry_price = signal.suggested_price
        
        # 假设持仓到下一个数据点 (简化为随机盈亏)
        import random
        pnl = size * Decimal(random.uniform(-0.02, 0.03))  # -2% 到 +3%
        
        return {
            "signal": signal,
            "size": size,
            "entry_price": entry_price,
            "pnl": pnl,
        }
