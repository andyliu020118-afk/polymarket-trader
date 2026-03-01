"""单元测试"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta

# Domain 测试
from src.domain.entities import Market, Order, Position
from src.domain.value_objects import Price, OrderBook, OrderBookLevel
from src.domain.enums import MarketStatus, OrderSide, OrderType, OrderStatus
from src.domain.events import OrderFilledEvent


class TestPrice:
    """价格值对象测试"""
    
    def test_valid_price(self):
        price = Price(yes_price=Decimal("0.6"), no_price=Decimal("0.4"))
        assert price.yes_price == Decimal("0.6")
        assert price.no_price == Decimal("0.4")
    
    def test_invalid_price_sum(self):
        with pytest.raises(ValueError, match="Prices must sum to ~1"):
            Price(yes_price=Decimal("0.7"), no_price=Decimal("0.4"))
    
    def test_price_out_of_range(self):
        with pytest.raises(ValueError, match="yes_price must be in"):
            Price(yes_price=Decimal("0.001"), no_price=Decimal("0.999"))
    
    def test_from_yes_price(self):
        price = Price.from_yes_price(Decimal("0.65"))
        assert price.yes_price == Decimal("0.65")
        assert price.no_price == Decimal("0.35")


class TestOrderBook:
    """订单簿测试"""
    
    def test_orderbook_spread(self):
        bids = [OrderBookLevel(Decimal("0.55"), Decimal("100"))]
        asks = [OrderBookLevel(Decimal("0.60"), Decimal("100"))]
        ob = OrderBook(bids=bids, asks=asks)
        
        assert ob.best_bid == Decimal("0.55")
        assert ob.best_ask == Decimal("0.60")
        assert ob.spread == Decimal("0.05")
    
    def test_empty_orderbook(self):
        ob = OrderBook(bids=[], asks=[])
        assert ob.best_bid == Decimal("0")
        assert ob.best_ask == Decimal("1")


class TestMarket:
    """市场实体测试"""
    
    def test_market_creation(self):
        market = Market(
            market_id="test-123",
            title="Test Market",
            current_price=Price.from_yes_price(Decimal("0.5")),
            liquidity_usd=Decimal("50000"),
            status=MarketStatus.ACTIVE
        )
        assert market.market_id == "test-123"
        assert market.is_tradable()
    
    def test_not_tradable_low_liquidity(self):
        market = Market(
            market_id="test-123",
            title="Test Market",
            liquidity_usd=Decimal("100"),  # 低于最小流动性
            status=MarketStatus.ACTIVE
        )
        assert not market.is_tradable()
    
    def test_not_tradable_closed(self):
        market = Market(
            market_id="test-123",
            title="Test Market",
            liquidity_usd=Decimal("50000"),
            status=MarketStatus.CLOSED
        )
        assert not market.is_tradable()


class TestOrder:
    """订单实体测试"""
    
    def test_order_creation(self):
        order = Order(
            market_id="market-123",
            side=OrderSide.BUY_YES,
            order_type=OrderType.LIMIT,
            price=Decimal("0.55"),
            size=Decimal("100")
        )
        assert order.status == OrderStatus.PENDING
        assert order.remaining_size == Decimal("100")
    
    def test_partial_fill(self):
        order = Order(
            market_id="market-123",
            side=OrderSide.BUY_YES,
            price=Decimal("0.55"),
            size=Decimal("100")
        )
        order.fill(Decimal("30"), Decimal("0.55"))
        
        assert order.status == OrderStatus.PARTIAL
        assert order.filled_size == Decimal("30")
        assert order.remaining_size == Decimal("70")
    
    def test_full_fill(self):
        order = Order(
            market_id="market-123",
            side=OrderSide.BUY_YES,
            price=Decimal("0.55"),
            size=Decimal("100")
        )
        order.fill(Decimal("100"), Decimal("0.55"))
        
        assert order.status == OrderStatus.FILLED
        assert order.is_filled
    
    def test_fill_event_generated(self):
        order = Order(
            market_id="market-123",
            side=OrderSide.BUY_YES,
            price=Decimal("0.55"),
            size=Decimal("100")
        )
        order.fill(Decimal("50"), Decimal("0.55"))
        
        events = order.pop_events()
        assert len(events) == 1
        assert isinstance(events[0], OrderFilledEvent)
    
    def test_invalid_fill_amount(self):
        order = Order(
            market_id="market-123",
            side=OrderSide.BUY_YES,
            price=Decimal("0.55"),
            size=Decimal("100")
        )
        with pytest.raises(ValueError, match="Fill amount must be positive"):
            order.fill(Decimal("-10"), Decimal("0.55"))


class TestPosition:
    """持仓实体测试"""
    
    def test_position_update_buy_yes(self):
        pos = Position(market_id="market-123")
        pos.update_position(
            side=OrderSide.BUY_YES,
            size=Decimal("100"),
            price=Decimal("0.55"),
            cost=Decimal("55")
        )
        
        assert pos.yes_tokens == Decimal("100")
        assert pos.net_exposure == Decimal("100")
        assert pos.total_cost == Decimal("55")
    
    def test_position_pnl_calculation(self):
        pos = Position(market_id="market-123")
        pos.update_position(
            side=OrderSide.BUY_YES,
            size=Decimal("100"),
            price=Decimal("0.50"),
            cost=Decimal("50")
        )
        
        # 价格上涨到 0.6
        pnl = pos.calculate_unrealized_pnl(Decimal("0.60"))
        assert pnl == Decimal("10")  # 100 * (0.6 - 0.5)
        
        # 价格下跌到 0.4
        pnl = pos.calculate_unrealized_pnl(Decimal("0.40"))
        assert pnl == Decimal("-10")  # 100 * (0.4 - 0.5)
    
    def test_roi_calculation(self):
        pos = Position(market_id="market-123")
        pos.update_position(
            side=OrderSide.BUY_YES,
            size=Decimal("100"),
            price=Decimal("0.50"),
            cost=Decimal("50")
        )
        
        roi = pos.calculate_roi(Decimal("0.60"))
        assert roi == Decimal("0.20")  # 20% 收益
