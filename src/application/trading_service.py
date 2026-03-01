"""交易服务"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Dict, List
from uuid import uuid4

from loguru import logger

from ..domain.entities import Market, Order, Position
from ..domain.enums import OrderSide, OrderType, OrderStatus
from ..domain.value_objects import Price
from ..infrastructure.blockchain_client import BlockchainClient, WalletConnection
from ..infrastructure.polymarket_client import PolymarketClient
from .risk_service import RiskService, RiskContext, Portfolio


@dataclass
class TradingConfig:
    """交易配置"""
    default_slippage: Decimal = Decimal("0.01")  # 默认滑点 1%
    max_order_size: Decimal = Decimal("1000")  # 最大单笔订单
    min_order_size: Decimal = Decimal("1")  # 最小单笔订单


@dataclass
class OrderRequest:
    """订单请求"""
    market_id: str
    side: OrderSide
    size: Decimal
    price: Optional[Decimal] = None  # None 表示市价单
    order_type: OrderType = field(init=False)
    
    def __post_init__(self) -> None:
        self.order_type = OrderType.LIMIT if self.price else OrderType.MARKET


class TradingService:
    """交易服务 - 处理订单和持仓"""
    
    def __init__(
        self,
        blockchain_client: BlockchainClient,
        polymarket_client: Optional[PolymarketClient] = None,
        risk_service: Optional[RiskService] = None,
        config: Optional[TradingConfig] = None
    ):
        self.blockchain = blockchain_client
        self.polymarket = polymarket_client
        self.risk = risk_service
        self.config = config or TradingConfig()
        
        # 内存存储 (后续替换为数据库)
        self._orders: Dict[str, Order] = {}
        self._positions: Dict[str, Position] = {}
        self._portfolio = Portfolio()
    
    async def connect_wallet(self, private_key: Optional[str] = None) -> WalletConnection:
        """连接钱包"""
        return self.blockchain.connect_with_private_key(private_key)
    
    def get_balance(self) -> Dict[str, Decimal]:
        """获取账户余额"""
        balances = self.blockchain.get_all_balances()
        return {
            symbol: balance.balance 
            for symbol, balance in balances.items()
        }
    
    async def get_markets(self) -> List[Market]:
        """获取市场列表"""
        if not self.polymarket:
            raise RuntimeError("Polymarket client not initialized")
        
        async with self.polymarket:
            return await self.polymarket.get_markets()
    
    async def get_market(self, market_id: str) -> Optional[Market]:
        """获取单个市场"""
        if not self.polymarket:
            raise RuntimeError("Polymarket client not initialized")
        
        async with self.polymarket:
            return await self.polymarket.get_market_by_id(market_id)
    
    async def create_order(self, request: OrderRequest) -> Order:
        """
        创建订单
        
        Args:
            request: 订单请求
            
        Returns:
            Order: 创建的订单
        """
        # 参数校验
        self._validate_order_request(request)
        
        # 获取市场信息
        if not self.polymarket:
            raise RuntimeError("Polymarket client not initialized")
        
        async with self.polymarket:
            market = await self.polymarket.get_market_by_id(request.market_id)
        
        if not market:
            raise ValueError(f"Market not found: {request.market_id}")
        
        # 确定价格
        price = request.price
        if not price and market.current_price:
            price = market.current_price.yes_price if request.side == OrderSide.BUY_YES else market.current_price.no_price
        
        if not price:
            raise ValueError("Cannot determine order price")
        
        # 创建订单实体
        order = Order(
            order_id=str(uuid4()),
            market_id=request.market_id,
            side=request.side,
            order_type=request.order_type,
            price=price,
            size=request.size,
            status=OrderStatus.PENDING,
        )
        
        # 风控检查
        if self.risk:
            position = self._positions.get(request.market_id)
            context = RiskContext(
                market=market,
                portfolio=self._portfolio,
                proposed_order=order,
            )
            if position:
                context.portfolio.positions[request.market_id] = position
            
            result = self.risk.check_pre_trade(context)
            if not result.passed:
                order.reject()
                logger.warning(f"Order rejected by risk control: {result.reason}")
                self._orders[order.order_id] = order
                return order
            
            order.risk_check_passed = True
        
        # 保存订单
        self._orders[order.order_id] = order
        
        logger.info(f"Order created: {order.order_id} for market {request.market_id}")
        return order
    
    def _validate_order_request(self, request: OrderRequest) -> None:
        """校验订单请求"""
        if request.size <= 0:
            raise ValueError(f"Order size must be positive, got {request.size}")
        
        if request.size < self.config.min_order_size:
            raise ValueError(f"Order size too small: {request.size} < {self.config.min_order_size}")
        
        if request.size > self.config.max_order_size:
            raise ValueError(f"Order size too large: {request.size} > {self.config.max_order_size}")
        
        if request.price is not None and (request.price <= 0 or request.price >= 1):
            raise ValueError(f"Price must be in (0, 1), got {request.price}")
    
    def cancel_order(self, order_id: str) -> Order:
        """取消订单"""
        order = self._orders.get(order_id)
        if not order:
            raise ValueError(f"Order not found: {order_id}")
        
        order.cancel()
        logger.info(f"Order cancelled: {order_id}")
        return order
    
    def get_order(self, order_id: str) -> Optional[Order]:
        """获取订单"""
        return self._orders.get(order_id)
    
    def get_orders(self, market_id: Optional[str] = None) -> List[Order]:
        """获取订单列表"""
        orders = list(self._orders.values())
        if market_id:
            orders = [o for o in orders if o.market_id == market_id]
        return orders
    
    def get_position(self, market_id: str) -> Optional[Position]:
        """获取持仓"""
        return self._positions.get(market_id)
    
    def get_all_positions(self) -> List[Position]:
        """获取所有持仓"""
        return list(self._positions.values())
    
    def simulate_fill(self, order_id: str, filled_amount: Decimal, 
                     avg_price: Decimal) -> None:
        """
        模拟订单成交 (用于测试)
        
        Args:
            order_id: 订单ID
            filled_amount: 成交数量
            avg_price: 成交均价
        """
        order = self._orders.get(order_id)
        if not order:
            raise ValueError(f"Order not found: {order_id}")
        
        if order.status not in (OrderStatus.PENDING, OrderStatus.PARTIAL):
            raise ValueError(f"Cannot fill order in status {order.status}")
        
        # 执行成交
        order.fill(filled_amount, avg_price)
        
        # 更新持仓
        self._update_position(order, filled_amount, avg_price)
        
        logger.info(f"Order filled: {order_id}, amount={filled_amount}, price={avg_price}")
    
    def _update_position(self, order: Order, filled_amount: Decimal, 
                        avg_price: Decimal) -> None:
        """更新持仓"""
        position = self._positions.get(order.market_id)
        
        if not position:
            position = Position(
                position_id=str(uuid4()),
                market_id=order.market_id,
            )
            self._positions[order.market_id] = position
        
        # 计算成本
        cost = filled_amount * avg_price
        
        # 更新持仓
        position.update_position(
            side=order.side,
            size=filled_amount,
            price=avg_price,
            cost=cost
        )
        
        # 更新投资组合
        self._portfolio.positions[order.market_id] = position
    
    def calculate_unrealized_pnl(self, market_id: str, current_price: Decimal) -> Decimal:
        """计算未实现盈亏"""
        position = self._positions.get(market_id)
        if not position:
            return Decimal("0")
        
        return position.calculate_unrealized_pnl(current_price)
    
    def get_portfolio_summary(self) -> Dict:
        """获取投资组合摘要"""
        total_cost = sum(p.total_cost for p in self._positions.values())
        
        return {
            "total_positions": len(self._positions),
            "total_cost": total_cost,
            "positions": [
                {
                    "market_id": p.market_id,
                    "net_exposure": p.net_exposure,
                    "avg_entry_price": p.avg_entry_price,
                    "total_cost": p.total_cost,
                }
                for p in self._positions.values()
            ]
        }
