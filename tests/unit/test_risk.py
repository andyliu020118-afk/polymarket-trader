"""风控服务测试"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta

from src.domain.entities import Market, Order, Position
from src.domain.value_objects import Price
from src.domain.enums import OrderSide, OrderType, MarketStatus, RiskAction
from src.application.risk_service import (
    RiskService, RiskConfig, RiskContext, Portfolio,
    PositionLimitRule, StopLossRule, DailyLossLimitRule
)


class TestPositionLimitRule:
    """仓位限制规则测试"""
    
    def test_position_within_limit(self):
        config = RiskConfig(max_position_pct=Decimal("0.1"), max_positions=5)
        rule = PositionLimitRule(config)
        
        portfolio = Portfolio(total_value=Decimal("1000"))
        order = Order(
            market_id="m1",
            side=OrderSide.BUY_YES,
            price=Decimal("0.5"),
            size=Decimal("100")  # 50 USDC, 5% of portfolio
        )
        context = RiskContext(
            market=Market(market_id="m1", liquidity_usd=Decimal("100000")),
            portfolio=portfolio,
            proposed_order=order
        )
        
        result = rule.check(context)
        assert result.passed
    
    def test_position_exceeds_limit(self):
        config = RiskConfig(max_position_pct=Decimal("0.1"))  # 10%
        rule = PositionLimitRule(config)
        
        portfolio = Portfolio(total_value=Decimal("1000"))
        order = Order(
            market_id="m1",
            side=OrderSide.BUY_YES,
            price=Decimal("0.8"),
            size=Decimal("200")  # 160 USDC, 16% of portfolio
        )
        context = RiskContext(
            market=Market(market_id="m1", liquidity_usd=Decimal("100000")),
            portfolio=portfolio,
            proposed_order=order
        )
        
        result = rule.check(context)
        assert not result.passed
        assert result.action == RiskAction.REJECT


class TestStopLossRule:
    """止损规则测试"""
    
    def test_stop_loss_triggered(self):
        config = RiskConfig(stop_loss_pct=Decimal("0.02"))  # -2%
        rule = StopLossRule(config)
        
        position = Position(market_id="m1")
        position.update_position(
            side=OrderSide.BUY_YES,
            size=Decimal("100"),
            price=Decimal("0.50"),
            cost=Decimal("50")
        )
        
        portfolio = Portfolio(positions={"m1": position})
        market = Market(
            market_id="m1",
            current_price=Price.from_yes_price(Decimal("0.48"))  # -4%
        )
        
        context = RiskContext(
            market=market,
            portfolio=portfolio
        )
        
        result = rule.check(context)
        assert not result.passed
        assert "止损" in result.reason
    
    def test_stop_loss_not_triggered(self):
        config = RiskConfig(stop_loss_pct=Decimal("0.02"))
        rule = StopLossRule(config)
        
        position = Position(market_id="m1")
        position.update_position(
            side=OrderSide.BUY_YES,
            size=Decimal("100"),
            price=Decimal("0.50"),
            cost=Decimal("50")
        )
        
        portfolio = Portfolio(positions={"m1": position})
        market = Market(
            market_id="m1",
            current_price=Price.from_yes_price(Decimal("0.51"))  # +2%
        )
        
        context = RiskContext(
            market=market,
            portfolio=portfolio
        )
        
        result = rule.check(context)
        assert result.passed


class TestDailyLossLimitRule:
    """日亏损限制测试"""
    
    def test_daily_loss_exceeded(self):
        config = RiskConfig(daily_loss_pct=Decimal("0.03"))  # -3%
        rule = DailyLossLimitRule(config)
        
        portfolio = Portfolio(
            total_value=Decimal("1000"),
            today_pnl=Decimal("-50")  # -5%
        )
        
        context = RiskContext(
            market=Market(market_id="m1"),
            portfolio=portfolio
        )
        
        result = rule.check(context)
        assert not result.passed
        assert result.action == RiskAction.PAUSE


class TestRiskService:
    """风控服务集成测试"""
    
    def test_service_initialization(self):
        service = RiskService()
        assert len(service.rules) == 6  # 6条规则
        assert service.is_trading_allowed()
    
    def test_pre_trade_check_pass(self):
        service = RiskService()
        
        order = Order(
            market_id="m1",
            side=OrderSide.BUY_YES,
            price=Decimal("0.5"),
            size=Decimal("10")
        )
        portfolio = Portfolio(total_value=Decimal("1000"))
        market = Market(
            market_id="m1",
            liquidity_usd=Decimal("100000"),
            status=MarketStatus.ACTIVE
        )
        
        context = RiskContext(
            market=market,
            portfolio=portfolio,
            proposed_order=order
        )
        
        result = service.check_pre_trade(context)
        assert result.passed
    
    def test_pause_trading(self):
        service = RiskService()
        
        # 模拟触发暂停
        service._paused_until = datetime.utcnow() + timedelta(minutes=30)
        
        assert not service.is_trading_allowed()
        
        context = RiskContext(
            market=Market(market_id="m1"),
            portfolio=Portfolio()
        )
        
        result = service.check_pre_trade(context)
        assert not result.passed
        assert "暂停" in result.reason
    
    def test_get_status(self):
        service = RiskService()
        status = service.get_status()
        
        assert "trading_allowed" in status
        assert "rules_count" in status
        assert status["rules_count"] == 6
