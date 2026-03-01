"""风控服务"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional, Dict

from loguru import logger

from ..domain.entities import Market, Order, Position
from ..domain.enums import RiskAction, Urgency, OrderSide
from ..domain.events import RiskTriggeredEvent


# 默认风控参数
DEFAULT_MAX_POSITION_PCT = Decimal("0.10")  # 单笔仓位 ≤10%
DEFAULT_MAX_POSITIONS = 5  # 最大持仓数
DEFAULT_MIN_LIQUIDITY = Decimal("10000")  # 最小流动性
DEFAULT_STOP_LOSS_PCT = Decimal("0.02")  # 单笔止损 -2%
DEFAULT_DAILY_LOSS_PCT = Decimal("0.03")  # 日止损 -3%
DEFAULT_CIRCUIT_BREAKER_VOLATILITY = Decimal("0.20")  # 熔断波动阈值 20%


@dataclass
class RiskConfig:
    """风控配置"""
    max_position_pct: Decimal = DEFAULT_MAX_POSITION_PCT
    max_positions: int = DEFAULT_MAX_POSITIONS
    min_liquidity_usd: Decimal = DEFAULT_MIN_LIQUIDITY
    stop_loss_pct: Decimal = DEFAULT_STOP_LOSS_PCT
    daily_loss_pct: Decimal = DEFAULT_DAILY_LOSS_PCT
    circuit_breaker_volatility: Decimal = DEFAULT_CIRCUIT_BREAKER_VOLATILITY
    circuit_breaker_duration_minutes: int = 30
    trading_start_hour: int = 6  # UTC
    trading_end_hour: int = 22  # UTC


@dataclass
class Portfolio:
    """投资组合"""
    total_value: Decimal = Decimal("0")
    positions: Dict[str, Position] = field(default_factory=dict)
    today_pnl: Decimal = Decimal("0")
    
    def get_position(self, market_id: str) -> Optional[Position]:
        return self.positions.get(market_id)
    
    def update_position(self, position: Position) -> None:
        self.positions[position.market_id] = position


@dataclass
class RiskContext:
    """风控上下文"""
    market: Market
    portfolio: Portfolio
    proposed_order: Optional[Order] = None
    price_history: List[Decimal] = field(default_factory=list)
    
    def get_position(self, market_id: str) -> Optional[Position]:
        return self.portfolio.get_position(market_id)


@dataclass
class RiskResult:
    """风控检查结果"""
    passed: bool
    reason: str = ""
    action: RiskAction = RiskAction.LOG
    urgency: Urgency = Urgency.LOW
    duration: Optional[timedelta] = None


class RiskRule(ABC):
    """风控规则抽象基类"""
    
    @abstractmethod
    def check(self, context: RiskContext) -> RiskResult:
        pass
    
    @property
    @abstractmethod
    def priority(self) -> int:
        """优先级，数字越小优先级越高"""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """规则名称"""
        pass


class PositionLimitRule(RiskRule):
    """仓位限制规则"""
    
    def __init__(self, config: RiskConfig):
        self.config = config
    
    @property
    def priority(self) -> int:
        return 1
    
    @property
    def name(self) -> str:
        return "PositionLimit"
    
    def check(self, context: RiskContext) -> RiskResult:
        if not context.proposed_order:
            return RiskResult(passed=True)
        
        portfolio = context.portfolio
        order = context.proposed_order
        
        # 检查单笔仓位
        order_value = order.price * order.size
        max_allowed = portfolio.total_value * self.config.max_position_pct
        
        if order_value > max_allowed:
            return RiskResult(
                passed=False,
                reason=f"单笔仓位超限: {order_value:.2f} > {max_allowed:.2f}",
                action=RiskAction.REJECT,
                urgency=Urgency.HIGH
            )
        
        # 检查总持仓数量
        current_positions = len(portfolio.positions)
        if current_positions >= self.config.max_positions:
            return RiskResult(
                passed=False,
                reason=f"持仓数量超限: {current_positions} >= {self.config.max_positions}",
                action=RiskAction.REJECT,
                urgency=Urgency.HIGH
            )
        
        return RiskResult(passed=True)


class LiquidityRule(RiskRule):
    """流动性检查规则"""
    
    def __init__(self, config: RiskConfig):
        self.config = config
    
    @property
    def priority(self) -> int:
        return 2
    
    @property
    def name(self) -> str:
        return "Liquidity"
    
    def check(self, context: RiskContext) -> RiskResult:
        market = context.market
        
        if market.liquidity_usd < self.config.min_liquidity_usd:
            return RiskResult(
                passed=False,
                reason=f"市场流动性不足: {market.liquidity_usd} < {self.config.min_liquidity_usd}",
                action=RiskAction.REJECT,
                urgency=Urgency.MEDIUM
            )
        
        return RiskResult(passed=True)


class StopLossRule(RiskRule):
    """止损规则"""
    
    def __init__(self, config: RiskConfig):
        self.config = config
    
    @property
    def priority(self) -> int:
        return 10
    
    @property
    def name(self) -> str:
        return "StopLoss"
    
    def check(self, context: RiskContext) -> RiskResult:
        position = context.get_position(context.market_id)
        if not position or position.absolute_size == 0:
            return RiskResult(passed=True)
        
        # 获取当前价格计算盈亏
        if not context.market.current_price:
            return RiskResult(passed=True)
        
        current_price = context.market.current_price.yes_price
        roi = position.calculate_roi(current_price)
        
        if roi <= -self.config.stop_loss_pct:
            return RiskResult(
                passed=False,
                reason=f"触发止损: ROI {roi:.2%} < -{self.config.stop_loss_pct:.2%}",
                action=RiskAction.CLOSE_POSITION,
                urgency=Urgency.CRITICAL
            )
        
        return RiskResult(passed=True)


class DailyLossLimitRule(RiskRule):
    """日亏损限制规则"""
    
    def __init__(self, config: RiskConfig):
        self.config = config
    
    @property
    def priority(self) -> int:
        return 20
    
    @property
    def name(self) -> str:
        return "DailyLossLimit"
    
    def check(self, context: RiskContext) -> RiskResult:
        today_pnl = context.portfolio.today_pnl
        total_value = context.portfolio.total_value
        
        if total_value <= 0:
            return RiskResult(passed=True)
        
        loss_pct = -today_pnl / total_value
        
        if loss_pct >= self.config.daily_loss_pct:
            return RiskResult(
                passed=False,
                reason=f"日亏损超限: {loss_pct:.2%} >= {self.config.daily_loss_pct:.2%}",
                action=RiskAction.PAUSE,
                urgency=Urgency.CRITICAL,
                duration=timedelta(hours=24)
            )
        
        return RiskResult(passed=True)


class CircuitBreakerRule(RiskRule):
    """熔断规则"""
    
    def __init__(self, config: RiskConfig):
        self.config = config
    
    @property
    def priority(self) -> int:
        return 30
    
    @property
    def name(self) -> str:
        return "CircuitBreaker"
    
    def check(self, context: RiskContext) -> RiskResult:
        if len(context.price_history) < 2:
            return RiskResult(passed=True)
        
        prices = context.price_history
        high = max(prices)
        low = min(prices)
        
        if low == 0:
            return RiskResult(passed=True)
        
        volatility = (high - low) / low
        
        if volatility > self.config.circuit_breaker_volatility:
            return RiskResult(
                passed=False,
                reason=f"价格波动过大: {volatility:.2%} > {self.config.circuit_breaker_volatility:.2%}",
                action=RiskAction.PAUSE,
                urgency=Urgency.HIGH,
                duration=timedelta(minutes=self.config.circuit_breaker_duration_minutes)
            )
        
        return RiskResult(passed=True)


class TradingHoursRule(RiskRule):
    """交易时间规则"""
    
    def __init__(self, config: RiskConfig):
        self.config = config
    
    @property
    def priority(self) -> int:
        return 5
    
    @property
    def name(self) -> str:
        return "TradingHours"
    
    def check(self, context: RiskContext) -> RiskResult:
        now = datetime.utcnow()
        hour = now.hour
        
        if hour < self.config.trading_start_hour or hour >= self.config.trading_end_hour:
            return RiskResult(
                passed=False,
                reason=f"非交易时段: {hour}:00 UTC (交易时间 {self.config.trading_start_hour}:00-{self.config.trading_end_hour}:00 UTC)",
                action=RiskAction.REJECT,
                urgency=Urgency.LOW
            )
        
        return RiskResult(passed=True)


class RiskService:
    """风控服务"""
    
    def __init__(self, config: Optional[RiskConfig] = None):
        self.config = config or RiskConfig()
        self.rules: List[RiskRule] = []
        self._init_rules()
        
        # 风控状态
        self._paused_until: Optional[datetime] = None
        self._triggered_events: List[RiskTriggeredEvent] = []
    
    def _init_rules(self) -> None:
        """初始化风控规则"""
        self.rules = [
            PositionLimitRule(self.config),
            LiquidityRule(self.config),
            TradingHoursRule(self.config),
            StopLossRule(self.config),
            DailyLossLimitRule(self.config),
            CircuitBreakerRule(self.config),
        ]
        # 按优先级排序
        self.rules.sort(key=lambda r: r.priority)
    
    def is_trading_allowed(self) -> bool:
        """检查是否允许交易"""
        if self._paused_until is None:
            return True
        if datetime.utcnow() >= self._paused_until:
            self._paused_until = None
            return True
        return False
    
    def check_pre_trade(self, context: RiskContext) -> RiskResult:
        """
        交易前风控检查
        
        Returns:
            RiskResult: 检查结果
        """
        if not self.is_trading_allowed():
            remaining = self._paused_until - datetime.utcnow() if self._paused_until else timedelta(0)
            return RiskResult(
                passed=False,
                reason=f"交易暂停中，剩余时间: {remaining}",
                action=RiskAction.REJECT,
                urgency=Urgency.MEDIUM
            )
        
        # 只检查高优先级规则 (交易前)
        pre_trade_rules = [r for r in self.rules if r.priority < 10]
        
        for rule in pre_trade_rules:
            result = rule.check(context)
            if not result.passed:
                logger.warning(f"Risk check failed [{rule.name}]: {result.reason}")
                return result
        
        return RiskResult(passed=True)
    
    def check_post_trade(self, context: RiskContext) -> List[RiskResult]:
        """
        交易后风控检查
        
        Returns:
            List[RiskResult]: 所有检查结果
        """
        results = []
        
        # 检查所有规则
        for rule in self.rules:
            result = rule.check(context)
            results.append(result)
            
            if not result.passed:
                logger.warning(f"Post-trade risk triggered [{rule.name}]: {result.reason}")
                
                # 触发风控动作
                self._handle_risk_triggered(rule.name, result)
        
        return results
    
    def _handle_risk_triggered(self, rule_name: str, result: RiskResult) -> None:
        """处理风控触发"""
        event = RiskTriggeredEvent(
            trigger_type=rule_name,
            description=result.reason,
            action=result.action,
            urgency=result.urgency,
            duration=result.duration
        )
        self._triggered_events.append(event)
        
        # 执行动作
        if result.action == RiskAction.PAUSE and result.duration:
            self._paused_until = datetime.utcnow() + result.duration
            logger.critical(f"Trading paused until {self._paused_until}")
        
        elif result.action == RiskAction.REJECT:
            logger.warning("Order rejected by risk control")
    
    def get_status(self) -> Dict[str, Any]:
        """获取风控状态"""
        return {
            "trading_allowed": self.is_trading_allowed(),
            "paused_until": self._paused_until.isoformat() if self._paused_until else None,
            "recent_triggers": len(self._triggered_events),
            "rules_count": len(self.rules),
        }
