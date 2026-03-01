"""领域值对象"""

from dataclasses import dataclass
from decimal import Decimal
from typing import List


@dataclass(frozen=True)
class Price:
    """价格值对象"""
    yes_price: Decimal
    no_price: Decimal
    
    def __post_init__(self) -> None:
        # 不变量检查
        if not (Decimal("0.01") <= self.yes_price <= Decimal("0.99")):
            raise ValueError(f"yes_price must be in [0.01, 0.99], got {self.yes_price}")
        if not (Decimal("0.01") <= self.no_price <= Decimal("0.99")):
            raise ValueError(f"no_price must be in [0.01, 0.99], got {self.no_price}")
        if abs(self.yes_price + self.no_price - 1) > Decimal("0.01"):
            raise ValueError(f"Prices must sum to ~1, got {self.yes_price + self.no_price}")
    
    @classmethod
    def from_yes_price(cls, yes_price: Decimal) -> "Price":
        """从 Yes 价格构造"""
        return cls(yes_price=yes_price, no_price=Decimal("1") - yes_price)


@dataclass
class OrderBookLevel:
    """订单簿档位"""
    price: Decimal
    size: Decimal
    
    def __post_init__(self) -> None:
        if self.price <= 0:
            raise ValueError("price must be positive")
        if self.size <= 0:
            raise ValueError("size must be positive")


@dataclass
class OrderBook:
    """订单簿值对象"""
    bids: List[OrderBookLevel]  # 买入报价 (从高到低)
    asks: List[OrderBookLevel]  # 卖出报价 (从低到高)
    
    @property
    def best_bid(self) -> Decimal:
        """最高买价"""
        return max((bid.price for bid in self.bids), default=Decimal("0"))
    
    @property
    def best_ask(self) -> Decimal:
        """最低卖价"""
        return min((ask.price for ask in self.asks), default=Decimal("1"))
    
    @property
    def spread(self) -> Decimal:
        """买卖价差"""
        return self.best_ask - self.best_bid
    
    @property
    def mid_price(self) -> Decimal:
        """中间价"""
        return (self.best_bid + self.best_ask) / 2
    
    def get_bid_depth(self, levels: int = 5) -> Decimal:
        """计算买盘深度"""
        return sum(bid.size * bid.price for bid in self.bids[:levels])
    
    def get_ask_depth(self, levels: int = 5) -> Decimal:
        """计算卖盘深度"""
        return sum(ask.size * (Decimal("1") - ask.price) for ask in self.asks[:levels])
