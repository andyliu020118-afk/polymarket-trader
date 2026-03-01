"""订单簿不平衡策略"""

from typing import Optional
from decimal import Decimal
from datetime import timedelta

from .base import TradingStrategy, StrategyConfig, StrategyContext, Signal, now
from ..enums import SignalAction


class OrderBookImbalanceStrategy(TradingStrategy):
    """
    订单簿不平衡策略
    
    核心逻辑:
    1. 分析订单簿买卖盘深度比
    2. 买盘深度 >> 卖盘深度 → 看涨信号 (买Yes)
    3. 卖盘深度 >> 买盘深度 → 看跌信号 (买No)
    
    胜率预期: 55-60%
    持仓周期: 短期 (5-30分钟)
    """
    
    def __init__(self, config: Optional[StrategyConfig] = None):
        super().__init__(config)
        self.imbalance_threshold = Decimal("2.0")  # 深度比阈值
        self.min_depth_usd = Decimal("10000")  # 最小深度 10k
        self.lookback_periods = 3  # 观察周期数
    
    def generate_signal(self, context: StrategyContext) -> Optional[Signal]:
        """生成订单簿不平衡信号"""
        if not self.enabled:
            return None
        
        market = context.market
        
        if not market.orderbook:
            return None
        
        orderbook = market.orderbook
        
        # 计算买卖盘深度 (5档)
        bid_depth = orderbook.get_bid_depth(5)
        ask_depth = orderbook.get_ask_depth(5)
        
        # 深度检查
        if bid_depth < self.min_depth_usd or ask_depth < self.min_depth_usd:
            return None
        
        if ask_depth == 0:
            return None
        
        imbalance_ratio = bid_depth / ask_depth
        
        # 买盘优势 → 买入 Yes
        if imbalance_ratio >= self.imbalance_threshold:
            confidence = min(
                Decimal("0.7"),
                Decimal("0.5") + (imbalance_ratio - 2) * Decimal("0.1")
            )
            
            if confidence >= self.config.min_confidence:
                size = self.calculate_position_size(confidence, context)
                return Signal(
                    strategy_id=self.name,
                    market_id=market.market_id,
                    action=SignalAction.BUY_YES,
                    confidence=confidence,
                    suggested_price=orderbook.best_ask,
                    suggested_size=size,
                    reason=f"买盘优势: ratio={imbalance_ratio:.2f}, depth={bid_depth:.0f}/{ask_depth:.0f}",
                    expires_at=now() + timedelta(minutes=10)
                )
        
        # 卖盘优势 → 买入 No
        if imbalance_ratio <= Decimal("1") / self.imbalance_threshold:
            confidence = min(
                Decimal("0.7"),
                Decimal("0.5") + (Decimal("1") / imbalance_ratio - 2) * Decimal("0.1")
            )
            
            if confidence >= self.config.min_confidence:
                size = self.calculate_position_size(confidence, context)
                return Signal(
                    strategy_id=self.name,
                    market_id=market.market_id,
                    action=SignalAction.BUY_NO,
                    confidence=confidence,
                    suggested_price=Decimal("1") - orderbook.best_bid,
                    suggested_size=size,
                    reason=f"卖盘优势: ratio={imbalance_ratio:.2f}, depth={bid_depth:.0f}/{ask_depth:.0f}",
                    expires_at=now() + timedelta(minutes=10)
                )
        
        return None
