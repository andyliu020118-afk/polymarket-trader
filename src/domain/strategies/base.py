"""策略基类"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, List

from ..entities import Market
from ..enums import SignalAction
from ..value_objects import Price


# 最小置信度
MIN_CONFIDENCE = Decimal("0.55")


def now() -> datetime:
    """获取当前时间"""
    return datetime.now()


@dataclass
class StrategyConfig:
    """策略配置基类"""
    enabled: bool = True
    min_confidence: Decimal = Decimal("0.55")
    signal_expiry_seconds: int = 300
    max_position_size: Decimal = Decimal("100")


@dataclass
class Signal:
    """交易信号"""
    strategy_id: str
    market_id: str
    action: SignalAction
    confidence: Decimal
    suggested_price: Decimal
    suggested_size: Decimal
    reason: str
    timestamp: datetime = field(default_factory=now)
    expires_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.expires_at is None:
            self.expires_at = self.timestamp + timedelta(seconds=300)
    
    def is_valid(self) -> bool:
        """检查信号是否有效"""
        return datetime.now() < self.expires_at and self.confidence >= MIN_CONFIDENCE


@dataclass
class StrategyContext:
    """策略上下文"""
    market: Market
    price_history: List[Price] = field(default_factory=list)
    portfolio_value: Decimal = Decimal("1000")
    current_positions: Dict[str, Decimal] = field(default_factory=dict)


class TradingStrategy(ABC):
    """交易策略抽象基类"""
    
    def __init__(self, config: Optional[StrategyConfig] = None):
        self.config = config or StrategyConfig()
        self.name = self.__class__.__name__
        self.enabled = self.config.enabled
    
    @abstractmethod
    def generate_signal(self, context: StrategyContext) -> Optional[Signal]:
        """生成交易信号"""
        pass
    
    def calculate_position_size(self, confidence: Decimal, 
                               context: StrategyContext) -> Decimal:
        """
        计算仓位大小
        
        基于凯利公式简化版：仓位 = 置信度 * 最大仓位
        """
        if not self.config.enabled:
            return Decimal("0")
        
        # 基础仓位 (根据置信度调整)
        base_size = self.config.max_position_size * confidence
        
        # 根据投资组合调整
        max_portfolio_position = context.portfolio_value * Decimal("0.1")  # 10%
        
        return min(base_size, max_portfolio_position)
    
    def on_market_data(self, market: Market) -> None:
        """市场数据更新回调 - 可重写"""
        pass
