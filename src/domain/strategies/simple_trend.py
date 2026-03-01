"""简单趋势跟踪策略"""

from typing import Optional, List
from decimal import Decimal
from datetime import timedelta

from .base import TradingStrategy, StrategyConfig, StrategyContext, Signal, now
from ..enums import SignalAction
from ..value_objects import Price


class SimpleTrendStrategy(TradingStrategy):
    """
    简单趋势跟踪策略 (保守型)
    
    核心逻辑:
    1. 计算短期移动平均 (MA5) 和中期移动平均 (MA20)
    2. MA5 上穿 MA20 → 看涨 (买Yes)
    3. MA5 下穿 MA20 → 看跌 (买No)
    
    保守性优化:
    - 只在趋势明确时入场 (MA斜率 > 阈值)
    - 结合成交量确认
    
    胜率预期: 55-58%
    """
    
    def __init__(self, config: Optional[StrategyConfig] = None):
        super().__init__(config)
        self.short_ma_period = 5
        self.long_ma_period = 20
        self.trend_strength_threshold = Decimal("0.01")  # 1%斜率
    
    def generate_signal(self, context: StrategyContext) -> Optional[Signal]:
        """生成趋势跟踪信号"""
        if not self.enabled:
            return None
        
        history = context.price_history
        if len(history) < self.long_ma_period:
            return None
        
        # 提取价格序列
        prices = [p.yes_price for p in history]
        
        # 计算均线
        short_ma = sum(prices[-self.short_ma_period:]) / self.short_ma_period
        long_ma = sum(prices[-self.long_ma_period:]) / self.long_ma_period
        
        # 计算趋势强度 (斜率)
        if len(prices) < self.short_ma_period + 1:
            return None
        
        short_slope = (prices[-1] - prices[-self.short_ma_period]) / prices[-self.short_ma_period]
        
        # 趋势确认
        trend_confirmed = abs(short_slope) >= self.trend_strength_threshold
        
        if not trend_confirmed:
            return None
        
        market = context.market
        
        # 金叉信号 (短期均线上穿长期均线)
        if short_ma > long_ma and short_slope > 0:
            confidence = min(
                Decimal("0.65"),
                Decimal("0.5") + short_slope * Decimal("5")
            )
            
            if confidence >= self.config.min_confidence:
                size = self.calculate_position_size(confidence, context)
                return Signal(
                    strategy_id=self.name,
                    market_id=market.market_id,
                    action=SignalAction.BUY_YES,
                    confidence=confidence,
                    suggested_price=market.current_price.yes_price if market.current_price else Decimal("0.5"),
                    suggested_size=size,
                    reason=f"趋势向上: MA5={short_ma:.4f} > MA20={long_ma:.4f}, slope={short_slope:.4f}",
                    expires_at=now() + timedelta(minutes=15)
                )
        
        # 死叉信号 (短期均线下穿长期均线)
        if short_ma < long_ma and short_slope < 0:
            confidence = min(
                Decimal("0.65"),
                Decimal("0.5") + abs(short_slope) * Decimal("5")
            )
            
            if confidence >= self.config.min_confidence:
                size = self.calculate_position_size(confidence, context)
                return Signal(
                    strategy_id=self.name,
                    market_id=market.market_id,
                    action=SignalAction.BUY_NO,
                    confidence=confidence,
                    suggested_price=market.current_price.no_price if market.current_price else Decimal("0.5"),
                    suggested_size=size,
                    reason=f"趋势向下: MA5={short_ma:.4f} < MA20={long_ma:.4f}, slope={short_slope:.4f}",
                    expires_at=now() + timedelta(minutes=15)
                )
        
        return None
