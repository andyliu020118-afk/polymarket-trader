"""领域枚举类型"""

from enum import Enum, auto


class MarketStatus(Enum):
    """市场状态"""
    ACTIVE = "active"
    CLOSED = "closed"
    RESOLVED = "resolved"
    PAUSED = "paused"


class OrderSide(Enum):
    """订单方向"""
    BUY_YES = "buy_yes"
    BUY_NO = "buy_no"
    SELL_YES = "sell_yes"
    SELL_NO = "sell_no"


class OrderType(Enum):
    """订单类型"""
    LIMIT = "limit"
    MARKET = "market"


class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class SignalAction(Enum):
    """信号动作"""
    BUY_YES = "buy_yes"
    BUY_NO = "buy_no"
    SELL = "sell"
    HOLD = "hold"


class RiskAction(Enum):
    """风控动作"""
    REJECT = "reject"
    PAUSE = "pause"
    CLOSE_POSITION = "close_position"
    NOTIFY = "notify"
    LOG = "log"


class Urgency(Enum):
    """紧急程度"""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4
