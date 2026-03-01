"""领域事件"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from .enums import RiskAction, Urgency


@dataclass
class DomainEvent:
    """领域事件基类"""
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class OrderCreatedEvent(DomainEvent):
    """订单创建事件"""
    order_id: str = ""
    market_id: str = ""
    side: str = ""
    price: Decimal = Decimal("0")
    size: Decimal = Decimal("0")


@dataclass
class OrderFilledEvent(DomainEvent):
    """订单成交事件"""
    order_id: str = ""
    filled_amount: Decimal = Decimal("0")
    avg_price: Decimal = Decimal("0")


@dataclass
class PositionUpdatedEvent(DomainEvent):
    """持仓更新事件"""
    position_id: str = ""
    market_id: str = ""
    new_size: Decimal = Decimal("0")
    pnl: Decimal = Decimal("0")


@dataclass
class RiskTriggeredEvent(DomainEvent):
    """风控触发事件"""
    trigger_type: str = ""  # STOP_LOSS | DAILY_LIMIT | CIRCUIT_BREAKER
    description: str = ""
    action: RiskAction = RiskAction.LOG
    urgency: Urgency = Urgency.MEDIUM
    duration: Optional[timedelta] = None


@dataclass
class StrategySignalEvent(DomainEvent):
    """策略信号事件"""
    strategy_id: str = ""
    market_id: str = ""
    signal: str = ""  # BUY | SELL | HOLD
    confidence: Decimal = Decimal("0")
    reason: str = ""
