"""领域实体"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional
from uuid import uuid4

from .enums import MarketStatus, OrderSide, OrderType, OrderStatus
from .value_objects import Price, OrderBook
from .events import (
    DomainEvent, 
    OrderFilledEvent, 
    PositionUpdatedEvent
)


MIN_LIQUIDITY = Decimal("10000")  # 最小流动性 10k USD


def now() -> datetime:
    """获取当前时间"""
    return datetime.now()


@dataclass
class Entity:
    """实体基类"""
    id: str = field(default_factory=lambda: str(uuid4()))
    _events: List[DomainEvent] = field(default_factory=list, init=False, repr=False)
    
    def add_event(self, event: DomainEvent) -> None:
        """添加领域事件"""
        self._events.append(event)
    
    def pop_events(self) -> List[DomainEvent]:
        """弹出所有事件"""
        events = self._events.copy()
        self._events.clear()
        return events


@dataclass
class Market(Entity):
    """预测市场实体"""
    market_id: str = ""  # 市场唯一ID (Polymarket 的 condition_id)
    title: str = ""
    description: str = ""
    category: str = ""  # politics/crypto/sports
    end_time: Optional[datetime] = None
    
    # 价格信息
    current_price: Optional[Price] = None
    orderbook: Optional[OrderBook] = None
    
    # 流动性指标
    liquidity_usd: Decimal = Decimal("0")
    volume_24h: Decimal = Decimal("0")
    
    # 状态
    status: MarketStatus = MarketStatus.ACTIVE
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)
    
    def __post_init__(self) -> None:
        if not self.id:
            self.id = str(uuid4())
    
    def is_tradable(self) -> bool:
        """检查是否可交易"""
        if self.status != MarketStatus.ACTIVE:
            return False
        if self.liquidity_usd < MIN_LIQUIDITY:
            return False
        if self.end_time and (self.end_time - now()) < timedelta(hours=2):
            return False
        return True
    
    def get_spread(self) -> Decimal:
        """计算买卖价差"""
        if not self.orderbook:
            return Decimal("0")
        return self.orderbook.spread
    
    def update_price(self, price: Price) -> None:
        """更新价格"""
        self.current_price = price
        self.updated_at = now()
    
    def update_orderbook(self, orderbook: OrderBook) -> None:
        """更新订单簿"""
        self.orderbook = orderbook
        self.updated_at = now()


@dataclass
class Order(Entity):
    """订单实体"""
    order_id: str = ""  # 订单ID
    market_id: str = ""  # 关联市场
    
    # 订单参数
    side: OrderSide = OrderSide.BUY_YES
    order_type: OrderType = OrderType.LIMIT
    price: Decimal = Decimal("0")
    size: Decimal = Decimal("0")
    
    # 状态管理
    status: OrderStatus = OrderStatus.PENDING
    filled_size: Decimal = Decimal("0")
    
    # 执行信息
    created_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)
    tx_hash: Optional[str] = None
    
    # 风控标记
    risk_check_passed: bool = False
    
    def __post_init__(self) -> None:
        if not self.order_id:
            self.order_id = str(uuid4())
        if not self.id:
            self.id = self.order_id
    
    @property
    def remaining_size(self) -> Decimal:
        """剩余数量"""
        return self.size - self.filled_size
    
    @property
    def is_filled(self) -> bool:
        """是否已完全成交"""
        return self.remaining_size <= 0
    
    def fill(self, amount: Decimal, avg_price: Decimal) -> None:
        """部分成交"""
        if amount <= 0:
            raise ValueError(f"Fill amount must be positive, got {amount}")
        if amount > self.remaining_size:
            raise ValueError(f"Fill amount {amount} > remaining {self.remaining_size}")
        
        self.filled_size += amount
        
        if self.remaining_size <= 0:
            self.status = OrderStatus.FILLED
        else:
            self.status = OrderStatus.PARTIAL
        
        self.updated_at = now()
        
        # 触发领域事件
        self.add_event(OrderFilledEvent(
            order_id=self.order_id,
            filled_amount=amount,
            avg_price=avg_price
        ))
    
    def cancel(self) -> None:
        """取消订单"""
        if self.status in (OrderStatus.FILLED, OrderStatus.CANCELLED):
            raise ValueError(f"Cannot cancel order in status {self.status}")
        self.status = OrderStatus.CANCELLED
        self.updated_at = now()
    
    def reject(self) -> None:
        """拒绝订单"""
        if self.status != OrderStatus.PENDING:
            raise ValueError(f"Cannot reject order in status {self.status}")
        self.status = OrderStatus.REJECTED
        self.updated_at = now()


@dataclass
class Position(Entity):
    """持仓实体"""
    position_id: str = ""  # 持仓ID
    market_id: str = ""  # 关联市场
    
    # 持仓详情
    yes_tokens: Decimal = Decimal("0")
    no_tokens: Decimal = Decimal("0")
    
    # 成本计算
    avg_entry_price: Decimal = Decimal("0")  # 净持仓的平均入场价
    total_cost: Decimal = Decimal("0")
    
    # 盈亏
    realized_pnl: Decimal = Decimal("0")
    
    # 元数据
    opened_at: datetime = field(default_factory=now)
    updated_at: datetime = field(default_factory=now)
    
    def __post_init__(self) -> None:
        if not self.position_id:
            self.position_id = str(uuid4())
        if not self.id:
            self.id = self.position_id
    
    @property
    def net_exposure(self) -> Decimal:
        """净敞口 (正数看多Yes，负数看多No)"""
        return self.yes_tokens - self.no_tokens
    
    @property
    def absolute_size(self) -> Decimal:
        """绝对持仓大小"""
        return abs(self.net_exposure)
    
    def calculate_unrealized_pnl(self, current_price: Decimal) -> Decimal:
        """计算未实现盈亏"""
        if self.net_exposure == 0:
            return Decimal("0")
        
        # 净敞口为正 = 看多Yes
        if self.net_exposure > 0:
            current_value = self.yes_tokens * current_price + \
                          self.no_tokens * (Decimal("1") - current_price)
        else:
            # 净敞口为负 = 看多No
            current_value = self.yes_tokens * current_price + \
                          self.no_tokens * (Decimal("1") - current_price)
        
        return current_value - self.total_cost
    
    def calculate_roi(self, current_price: Decimal) -> Decimal:
        """计算收益率"""
        if self.total_cost == 0:
            return Decimal("0")
        pnl = self.calculate_unrealized_pnl(current_price)
        return pnl / self.total_cost
    
    def update_position(self, side: OrderSide, size: Decimal, 
                       price: Decimal, cost: Decimal) -> None:
        """更新持仓"""
        if side == OrderSide.BUY_YES:
            self.yes_tokens += size
        elif side == OrderSide.BUY_NO:
            self.no_tokens += size
        elif side == OrderSide.SELL_YES:
            self.yes_tokens -= size
        elif side == OrderSide.SELL_NO:
            self.no_tokens -= size
        
        self.total_cost += cost
        
        # 更新平均入场价
        if self.net_exposure != 0:
            self.avg_entry_price = self.total_cost / self.absolute_size
        
        self.updated_at = now()
        
        # 触发领域事件
        self.add_event(PositionUpdatedEvent(
            position_id=self.position_id,
            market_id=self.market_id,
            new_size=self.absolute_size,
            pnl=self.calculate_unrealized_pnl(price)
        ))
