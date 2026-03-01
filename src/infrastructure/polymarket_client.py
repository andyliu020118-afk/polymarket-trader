"""Polymarket API 客户端"""

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Dict, Any

import httpx
from loguru import logger

from ..domain.entities import Market
from ..domain.value_objects import Price, OrderBook, OrderBookLevel
from ..domain.enums import MarketStatus


POLYMARKET_API_BASE = "https://clob.polymarket.com"
GAMMA_API_BASE = "https://gamma-api.polymarket.com"


@dataclass
class MarketData:
    """市场数据"""
    market_id: str
    title: str
    description: str
    category: str
    current_price: Decimal
    liquidity: Decimal
    volume_24h: Decimal
    status: str


class PolymarketClient:
    """Polymarket CLOB API 客户端"""
    
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        """
        初始化 Polymarket 客户端
        
        Args:
            api_key: API Key (可选，只读操作不需要)
            api_secret: API Secret (可选)
        """
        self.api_key = api_key
        self.api_secret = api_secret
        
        # HTTP 客户端
        self._client: Optional[httpx.AsyncClient] = None
        
        # 缓存
        self._markets_cache: Dict[str, Any] = {}
        
    async def __aenter__(self):
        """异步上下文管理器"""
        self._client = httpx.AsyncClient(
            base_url=POLYMARKET_API_BASE,
            headers=self._get_headers(),
            timeout=30.0
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        if self._client:
            await self._client.aclose()
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
    
    async def _get(self, endpoint: str, params: Optional[Dict] = None) -> Any:
        """发送 GET 请求"""
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")
        
        try:
            response = await self._client.get(endpoint, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code}: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Request failed: {e}")
            raise
    
    async def get_markets(self, active_only: bool = True, 
                         limit: int = 100) -> List[Market]:
        """
        获取市场列表
        
        Args:
            active_only: 只返回活跃市场
            limit: 返回数量限制
        """
        try:
            # 使用 Gamma API 获取市场列表
            async with httpx.AsyncClient() as client:
                params = {
                    "active": active_only,
                    "closed": False,
                    "archived": False,
                    "limit": limit,
                }
                response = await client.get(
                    f"{GAMMA_API_BASE}/markets",
                    params=params,
                    timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
            
            markets = []
            for market_data in data.get("data", []):
                try:
                    market = self._parse_market(market_data)
                    if market:
                        markets.append(market)
                except Exception as e:
                    logger.warning(f"Failed to parse market {market_data.get('conditionId')}: {e}")
                    continue
            
            logger.info(f"Fetched {len(markets)} markets")
            return markets
            
        except Exception as e:
            logger.error(f"Failed to fetch markets: {e}")
            return []
    
    def _parse_market(self, data: Dict[str, Any]) -> Optional[Market]:
        """解析市场数据"""
        try:
            condition_id = data.get("conditionId")
            if not condition_id:
                return None
            
            # 获取当前价格 (从 outcomes)
            outcomes = data.get("outcomes", "[]")
            if isinstance(outcomes, str):
                import json
                try:
                    outcomes = json.loads(outcomes)
                except:
                    outcomes = []
            
            current_price = Decimal("0.5")  # 默认
            if outcomes and len(outcomes) > 0:
                first_outcome = outcomes[0]
                if isinstance(first_outcome, dict):
                    current_price = Decimal(str(first_outcome.get("price", 0.5)))
            
            # 解析状态
            status_str = data.get("status", "active")
            status = MarketStatus.ACTIVE if status_str == "active" else MarketStatus.CLOSED
            
            # 构建市场对象
            market = Market(
                market_id=condition_id,
                title=data.get("question", ""),
                description=data.get("description", ""),
                category=data.get("category", ""),
                current_price=Price.from_yes_price(current_price),
                liquidity_usd=Decimal(str(data.get("liquidity", 0))),
                volume_24h=Decimal(str(data.get("volume", 0))),
                status=status,
            )
            
            return market
            
        except Exception as e:
            logger.warning(f"Failed to parse market data: {e}")
            return None
    
    async def get_orderbook(self, market_id: str) -> OrderBook:
        """
        获取市场订单簿
        
        Args:
            market_id: 市场 condition_id
        """
        try:
            data = await self._get(f"/book/{market_id}")
            
            # 解析 bids
            bids_data = data.get("bids", [])
            bids = [
                OrderBookLevel(
                    price=Decimal(str(bid["price"])),
                    size=Decimal(str(bid["size"]))
                )
                for bid in bids_data
                if "price" in bid and "size" in bid
            ]
            bids.sort(key=lambda x: x.price, reverse=True)  # 从高到低
            
            # 解析 asks
            asks_data = data.get("asks", [])
            asks = [
                OrderBookLevel(
                    price=Decimal(str(ask["price"])),
                    size=Decimal(str(ask["size"]))
                )
                for ask in asks_data
                if "price" in ask and "size" in ask
            ]
            asks.sort(key=lambda x: x.price)  # 从低到高
            
            return OrderBook(bids=bids, asks=asks)
            
        except Exception as e:
            logger.error(f"Failed to fetch orderbook for {market_id}: {e}")
            return OrderBook(bids=[], asks=[])
    
    async def get_market_by_id(self, market_id: str) -> Optional[Market]:
        """获取单个市场详情"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{GAMMA_API_BASE}/markets/{market_id}",
                    timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
                return self._parse_market(data)
        except Exception as e:
            logger.error(f"Failed to fetch market {market_id}: {e}")
            return None
    
    async def get_price_history(self, market_id: str, 
                               resolution: str = "1h",
                               limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取历史价格数据
        
        Args:
            market_id: 市场 ID
            resolution: 时间分辨率 (1m, 5m, 15m, 1h, 4h, 1d)
            limit: 返回条数
        """
        try:
            data = await self._get(
                f"/prices-history",
                params={
                    "market": market_id,
                    "resolution": resolution,
                    "limit": limit
                }
            )
            return data.get("history", [])
        except Exception as e:
            logger.error(f"Failed to fetch price history: {e}")
            return []
