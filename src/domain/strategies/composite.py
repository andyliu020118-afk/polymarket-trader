"""组合策略"""

from typing import Optional, List, Dict
from decimal import Decimal

from .base import TradingStrategy, StrategyConfig, StrategyContext, Signal
from ..enums import SignalAction


class CompositeStrategy(TradingStrategy):
    """
    组合策略
    
    组合多个策略的信号，加权生成最终信号
    """
    
    def __init__(self, strategies: List[TradingStrategy] = None, 
                 config: Optional[StrategyConfig] = None):
        super().__init__(config)
        self.strategies = strategies or []
        self.weights = self._calculate_weights()
    
    def _calculate_weights(self) -> Dict[str, Decimal]:
        """计算策略权重 (等权)"""
        if not self.strategies:
            return {}
        weight = Decimal("1") / len(self.strategies)
        return {s.name: weight for s in self.strategies}
    
    def add_strategy(self, strategy: TradingStrategy, weight: Optional[Decimal] = None) -> None:
        """添加策略"""
        self.strategies.append(strategy)
        if weight:
            self.weights[strategy.name] = weight
        else:
            # 重新计算等权
            weight = Decimal("1") / len(self.strategies)
            self.weights = {s.name: weight for s in self.strategies}
    
    def generate_signal(self, context: StrategyContext) -> Optional[Signal]:
        """生成组合信号"""
        if not self.enabled or not self.strategies:
            return None
        
        signals = []
        
        for strategy in self.strategies:
            if not strategy.enabled:
                continue
            
            signal = strategy.generate_signal(context)
            if signal and signal.is_valid():
                signals.append((signal, self.weights.get(strategy.name, Decimal("0.33"))))
        
        if not signals:
            return None
        
        # 按动作分组
        buy_yes_signals = [s for s in signals if s[0].action == SignalAction.BUY_YES]
        buy_no_signals = [s for s in signals if s[0].action == SignalAction.BUY_NO]
        
        # 选择权重最高的动作
        yes_weight = sum(w for s, w in buy_yes_signals)
        no_weight = sum(w for s, w in buy_no_signals)
        
        if yes_weight > no_weight and yes_weight >= self.config.min_confidence:
            best_signal = max(buy_yes_signals, key=lambda x: x[0].confidence)[0]
            return Signal(
                strategy_id=f"{self.name}(Composite)",
                market_id=best_signal.market_id,
                action=SignalAction.BUY_YES,
                confidence=yes_weight,
                suggested_price=best_signal.suggested_price,
                suggested_size=best_signal.suggested_size,
                reason=f"组合信号: 买Yes权重={yes_weight:.2%}"
            )
        
        if no_weight > yes_weight and no_weight >= self.config.min_confidence:
            best_signal = max(buy_no_signals, key=lambda x: x[0].confidence)[0]
            return Signal(
                strategy_id=f"{self.name}(Composite)",
                market_id=best_signal.market_id,
                action=SignalAction.BUY_NO,
                confidence=no_weight,
                suggested_price=best_signal.suggested_price,
                suggested_size=best_signal.suggested_size,
                reason=f"组合信号: 买No权重={no_weight:.2%}"
            )
        
        return None
