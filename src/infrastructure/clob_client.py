"""Polymarket CLOB 订单管理"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Dict, Any, List

from loguru import logger

from ..domain.entities import Order
from ..domain.enums import OrderSide, OrderStatus
from .retry_client import RetryableHTTPClient, retry


POLYMARKET_CLOB_API = "https://clob.polymarket.com"


@dataclass
class CLOBOrderRequest:
    """CLOB 订单请求"""
    market_id: str
    side: str  # BUY or SELL
    outcome: str  # YES or NO
    size: Decimal
    price: Decimal
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "market": self.market_id,
            "side": self.side,
            "outcome": self.outcome,
            "size": str(self.size),
            "price": str(self.price),
        }


@dataclass
class CLOBOrderResponse:
    """CLOB 订单响应"""
    order_id: str
    status: str
    filled_size: Decimal
    remaining_size: Decimal
    avg_price: Optional[Decimal]
    transaction_hash: Optional[str]


class PolymarketCLOBClient:
    """Polymarket CLOB (Central Limit Order Book) 客户端"""
    
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        """
        初始化 CLOB 客户端
        
        Args:
            api_key: Polymarket API Key
            api_secret: API Secret
        """
        self.api_key = api_key
        self.api_secret = api_secret
        
        # 初始化带重试的 HTTP 客户端
        self._client: Optional[RetryableHTTPClient] = None
        
        # 订单缓存
        self._orders: Dict[str, CLOBOrderResponse] = {}
    
    async def __aenter__(self):
        """异步上下文管理器"""
        self._client = RetryableHTTPClient(
            base_url=POLYMARKET_CLOB_API,
            headers=self._get_headers(),
            timeout=30.0
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        if self._client:
            await self._client._client.aclose()
            self._client = None
    
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["POLYMARKET_API_KEY"] = self.api_key
        return headers
    
    @retry(max_retries=3, base_delay=1.0)
    async def submit_order(self, order: Order) -> CLOBOrderResponse:
        """
        提交订单到 CLOB
        
        Args:
            order: 订单实体
            
        Returns:
            CLOBOrderResponse: 订单响应
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")
        
        # 转换订单方向
        side, outcome = self._convert_side(order.side)
        
        # 构建请求
        request = CLOBOrderRequest(
            market_id=order.market_id,
            side=side,
            outcome=outcome,
            size=order.size,
            price=order.price,
        )
        
        logger.info(f"Submitting order to CLOB: {order.order_id}")
        
        try:
            response = await self._client.post(
                "/orders",
                json=request.to_dict()
            )
            
            data = response.json()
            
            # 解析响应
            clob_response = CLOBOrderResponse(
                order_id=data.get("orderId", order.order_id),
                status=data.get("status", "pending"),
                filled_size=Decimal(str(data.get("filledSize", 0))),
                remaining_size=Decimal(str(data.get("remainingSize", order.size))),
                avg_price=Decimal(str(data.get("avgPrice", 0))) if data.get("avgPrice") else None,
                transaction_hash=data.get("transactionHash"),
            )
            
            # 更新订单状态
            if clob_response.status == "filled":
                order.status = OrderStatus.FILLED
            elif clob_response.status == "partial":
                order.status = OrderStatus.PARTIAL
            elif clob_response.status == "rejected":
                order.status = OrderStatus.REJECTED
            
            # 缓存订单
            self._orders[clob_response.order_id] = clob_response
            
            logger.info(f"Order submitted successfully: {clob_response.order_id}, "
                       f"status={clob_response.status}")
            
            return clob_response
            
        except Exception as e:
            logger.error(f"Failed to submit order: {e}")
            order.status = OrderStatus.REJECTED
            raise
    
    def _convert_side(self, side: OrderSide) -> tuple:
        """
        转换订单方向到 CLOB 格式
        
        Returns:
            tuple: (side, outcome) 例如 ("BUY", "YES")
        """
        mapping = {
            OrderSide.BUY_YES: ("BUY", "YES"),
            OrderSide.BUY_NO: ("BUY", "NO"),
            OrderSide.SELL_YES: ("SELL", "YES"),
            OrderSide.SELL_NO: ("SELL", "NO"),
        }
        return mapping.get(side, ("BUY", "YES"))
    
    @retry(max_retries=3, base_delay=1.0)
    async def cancel_order(self, order_id: str) -> bool:
        """
        取消订单
        
        Args:
            order_id: 订单ID
            
        Returns:
            bool: 是否成功取消
        """
        if not self._client:
            raise RuntimeError("Client not initialized")
        
        try:
            response = await self._client.post(f"/orders/{order_id}/cancel")
            
            if response.status_code == 200:
                logger.info(f"Order cancelled: {order_id}")
                return True
            else:
                logger.warning(f"Failed to cancel order {order_id}: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return False
    
    @retry(max_retries=3, base_delay=1.0)
    async def get_order_status(self, order_id: str) -> Optional[CLOBOrderResponse]:
        """
        获取订单状态
        
        Args:
            order_id: 订单ID
            
        Returns:
            Optional[CLOBOrderResponse]: 订单状态
        """
        if not self._client:
            raise RuntimeError("Client not initialized")
        
        try:
            response = await self._client.get(f"/orders/{order_id}")
            data = response.json()
            
            return CLOBOrderResponse(
                order_id=data.get("orderId", order_id),
                status=data.get("status", "unknown"),
                filled_size=Decimal(str(data.get("filledSize", 0))),
                remaining_size=Decimal(str(data.get("remainingSize", 0))),
                avg_price=Decimal(str(data.get("avgPrice", 0))) if data.get("avgPrice") else None,
                transaction_hash=data.get("transactionHash"),
            )
            
        except Exception as e:
            logger.error(f"Failed to get order status: {e}")
            return None
    
    @retry(max_retries=3, base_delay=1.0)
    async def get_open_orders(self) -> List[CLOBOrderResponse]:
        """
        获取所有未完成的订单
        
        Returns:
            List[CLOBOrderResponse]: 未完成订单列表
        """
        if not self._client:
            raise RuntimeError("Client not initialized")
        
        try:
            response = await self._client.get("/orders/open")
            data = response.json()
            
            orders = []
            for order_data in data.get("orders", []):
                orders.append(CLOBOrderResponse(
                    order_id=order_data.get("orderId"),
                    status=order_data.get("status", "open"),
                    filled_size=Decimal(str(order_data.get("filledSize", 0))),
                    remaining_size=Decimal(str(order_data.get("remainingSize", 0))),
                    avg_price=Decimal(str(order_data.get("avgPrice", 0))) if order_data.get("avgPrice") else None,
                    transaction_hash=order_data.get("transactionHash"),
                ))
            
            return orders
            
        except Exception as e:
            logger.error(f"Failed to get open orders: {e}")
            return []
