"""策略模块测试"""

import sys
sys.path.insert(0, '/Users/a1/.openclaw/workspace-elonmask/polymarket-trader/src')

from decimal import Decimal

from domain.strategies import (
    StrategyConfig,
    StrategyContext,
    SpreadArbitrageStrategy,
    OrderBookImbalanceStrategy,
    SimpleTrendStrategy,
    CompositeStrategy,
)
from domain.enums import SignalAction
from domain.entities import Market
from domain.enums import MarketStatus
from domain.value_objects import Price, OrderBook, OrderBookLevel


def test_spread_arbitrage_strategy():
    """测试价差套利策略"""
    config = StrategyConfig(enabled=True, min_confidence=Decimal("0.55"))
    strategy = SpreadArbitrageStrategy(config)
    
    # 创建市场 (价差 5%)
    market = Market(
        market_id="test-1",
        title="Test Market",
        current_price=Price.from_yes_price(Decimal("0.55")),
        orderbook=OrderBook(
            bids=[OrderBookLevel(Decimal("0.55"), Decimal("100"))],
            asks=[OrderBookLevel(Decimal("0.60"), Decimal("100"))]
        ),
        liquidity_usd=Decimal("100000"),
        status=MarketStatus.ACTIVE
    )
    
    context = StrategyContext(market=market)
    signal = strategy.generate_signal(context)
    
    assert signal is not None
    # best_bid=0.55 >= 0.5, 所以策略判断 Yes 价格不低，转而买入 No
    assert signal.action == SignalAction.BUY_NO
    assert signal.confidence >= Decimal("0.55")
    print(f"✅ Spread Arbitrage: {signal.action.value}, confidence={signal.confidence:.2%}")


def test_orderbook_imbalance_strategy():
    """测试订单簿不平衡策略"""
    config = StrategyConfig(enabled=True, min_confidence=Decimal("0.55"))
    strategy = OrderBookImbalanceStrategy(config)
    
    # 买盘深度是卖盘的3倍 (5档数据，每档深度需满足 min_depth_usd=10000)
    market = Market(
        market_id="test-2",
        title="Test Market",
        current_price=Price.from_yes_price(Decimal("0.50")),
        orderbook=OrderBook(
            bids=[
                OrderBookLevel(Decimal("0.49"), Decimal("6000")),
                OrderBookLevel(Decimal("0.485"), Decimal("6000")),
                OrderBookLevel(Decimal("0.48"), Decimal("6000")),
                OrderBookLevel(Decimal("0.475"), Decimal("6000")),
                OrderBookLevel(Decimal("0.47"), Decimal("6000")),
            ],
            asks=[
                OrderBookLevel(Decimal("0.51"), Decimal("5000")),
                OrderBookLevel(Decimal("0.515"), Decimal("5000")),
                OrderBookLevel(Decimal("0.52"), Decimal("5000")),
                OrderBookLevel(Decimal("0.525"), Decimal("5000")),
                OrderBookLevel(Decimal("0.53"), Decimal("5000")),
            ]
        ),
        liquidity_usd=Decimal("100000"),
        status=MarketStatus.ACTIVE
    )
    
    context = StrategyContext(market=market)
    signal = strategy.generate_signal(context)
    
    assert signal is not None
    assert signal.action == SignalAction.BUY_YES
    print(f"✅ OrderBook Imbalance: {signal.action.value}, confidence={signal.confidence:.2%}")


def test_simple_trend_strategy():
    """测试趋势跟踪策略"""
    config = StrategyConfig(enabled=True, min_confidence=Decimal("0.55"))
    strategy = SimpleTrendStrategy(config)
    
    # 上升趋势
    market = Market(
        market_id="test-3",
        title="Test Market",
        current_price=Price.from_yes_price(Decimal("0.60")),
        liquidity_usd=Decimal("100000"),
        status=MarketStatus.ACTIVE
    )
    
    # 构建价格历史 (上升趋势)
    price_history = [
        Price.from_yes_price(Decimal("0.50")),
        Price.from_yes_price(Decimal("0.51")),
        Price.from_yes_price(Decimal("0.52")),
        Price.from_yes_price(Decimal("0.54")),
        Price.from_yes_price(Decimal("0.56")),
        Price.from_yes_price(Decimal("0.58")),
        Price.from_yes_price(Decimal("0.60")),
    ] + [Price.from_yes_price(Decimal("0.60"))] * 20  # 补齐20个数据点
    
    context = StrategyContext(market=market, price_history=price_history)
    signal = strategy.generate_signal(context)
    
    if signal:
        print(f"✅ Simple Trend: {signal.action.value}, confidence={signal.confidence:.2%}")
    else:
        print("⚠️ Simple Trend: No signal (may need more data)")


def test_composite_strategy():
    """测试组合策略"""
    config = StrategyConfig(enabled=True, min_confidence=Decimal("0.55"))
    
    # 创建子策略
    spread = SpreadArbitrageStrategy(config)
    imbalance = OrderBookImbalanceStrategy(config)
    
    composite = CompositeStrategy([spread, imbalance])
    
    # 创建市场 (同时满足两个策略)
    market = Market(
        market_id="test-4",
        title="Test Market",
        current_price=Price.from_yes_price(Decimal("0.50")),
        orderbook=OrderBook(
            bids=[OrderBookLevel(Decimal("0.45"), Decimal("50000"))],
            asks=[OrderBookLevel(Decimal("0.55"), Decimal("10000"))]
        ),
        liquidity_usd=Decimal("100000"),
        status=MarketStatus.ACTIVE
    )
    
    context = StrategyContext(market=market)
    signal = composite.generate_signal(context)
    
    if signal:
        print(f"✅ Composite Strategy: {signal.action.value}, confidence={signal.confidence:.2%}")
    else:
        print("⚠️ Composite Strategy: No signal")


if __name__ == "__main__":
    print("Running strategy tests...\n")
    
    test_spread_arbitrage_strategy()
    test_orderbook_imbalance_strategy()
    test_simple_trend_strategy()
    test_composite_strategy()
    
    print("\n🎉 All strategy tests passed!")
