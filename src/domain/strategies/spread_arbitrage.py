"""价差套利策略"""

from typing import Optional
from decimal import Decimal
from datetime import timedelta

from .base import TradingStrategy, StrategyConfig, StrategyContext, Signal, now
from ..enums import SignalAction


class SpreadArbitrageStrategy(TradingStrategy):
    """
    价差套利策略
    
    核心逻辑:
    1. 监测订单簿价差
    2. 当价差 > 阈值时，买入低价方
    3. 持仓至价差收敛或达到最大持仓时间
    
    适用场景: 流动性充足的市场，价差波动明显
    胜率预期: 55-60%
    """
    
    def __init__(self, config: Optional[StrategyConfig] = None):
        super().__init__(config)
        self.min_spread = Decimal("0.02")  # 最小价差 2%
        self.min_liquidity = Decimal("50000")  # 最小流动性 50k
        self.max_hold_time = 3600  # 最大持仓时间 1小时
    
    def generate_signal(self, context: StrategyContext) -> Optional[Signal]:
        """生成价差套利信号"""
        if not self.enabled:
            return None
        
        market = context.market
        
        # 流动性检查
        if market.liquidity_usd < self.min_liquidity:
            return None
        
        # 需要订单簿数据
        if not market.orderbook:
            return None
        
        spread = market.get_spread()
        
        # 价差套利条件
        if spread < self.min_spread:
            return None
        
        # 计算置信度 (价差越大，置信度越高)
        confidence = min(
            Decimal("0.95"),
            Decimal("0.5") + spread * Decimal("10")
        )
        
        if confidence < self.config.min_confidence:
            return None
        
        # 确定方向
        best_bid = market.orderbook.best_bid
        best_ask = market.orderbook.best_ask
        
        if best_bid < Decimal("0.5"):
            # Yes 价格偏低，买入 Yes
            action = SignalAction.BUY_YES
            entry_price = best_ask
        else:
            # No 价格偏低，买入 No
            action = SignalAction.BUY_NO
            entry_price = Decimal("1") - best_ask
        
        # 计算仓位
        size = self.calculate_position_size(confidence, context)
        
        return Signal(
            strategy_id=self.name,
            market_id=market.market_id,
            action=action,
            confidence=confidence,
            suggested_price=entry_price,
            suggested_size=size,
            reason=f"价差套利: spread={spread:.2%}, bid={best_bid:.4f}, ask={best_ask:.4f}",
            expires_at=now() + timedelta(minutes=5)
        )
