"""配置管理"""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class PositionRiskConfig(BaseModel):
    """仓位风控配置"""
    max_position_per_trade: float = 0.10
    max_positions_total: int = 5
    min_liquidity_usd: float = 10000
    min_market_volume_24h: float = 5000


class StopLossConfig(BaseModel):
    """止损配置"""
    per_trade: float = 0.02
    daily_limit: float = 0.03
    trailing_stop: float = 0.01
    max_drawdown: float = 0.05


class CircuitBreakerConfig(BaseModel):
    """熔断配置"""
    enabled: bool = True
    price_volatility: float = 0.20
    volume_anomaly: float = 3.0
    pause_duration_minutes: int = 30
    cooldown_minutes: int = 60


class TradingHoursConfig(BaseModel):
    """交易时间配置"""
    enabled: bool = False
    timezone: str = "UTC"
    start_hour: int = 6
    end_hour: int = 22
    weekends_allowed: bool = True


class RateLimitConfig(BaseModel):
    """限流配置"""
    enabled: bool = True
    min_interval_seconds: float = 1.0
    max_requests_per_minute: int = 60
    max_orders_per_minute: int = 10


class RiskConfig(BaseModel):
    """风控总配置"""
    position: PositionRiskConfig = Field(default_factory=PositionRiskConfig)
    stop_loss: StopLossConfig = Field(default_factory=StopLossConfig)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    trading_hours: TradingHoursConfig = Field(default_factory=TradingHoursConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)


class BlockchainConfig(BaseModel):
    """区块链配置"""
    network: str = "polygon-mainnet"
    rpc_url: str = "https://polygon-rpc.com"
    
    class GasConfig(BaseModel):
        default_limit: int = 300000
        price_multiplier: float = 1.1
        max_priority_fee_gwei: int = 30
    
    gas: GasConfig = Field(default_factory=GasConfig)


class PolymarketConfig(BaseModel):
    """Polymarket API 配置"""
    api_base: str = "https://clob.polymarket.com"
    gamma_api: str = "https://gamma-api.polymarket.com"
    api_key: str = ""
    api_secret: str = ""
    
    class RequestConfig(BaseModel):
        timeout: int = 30
        max_retries: int = 3
        retry_delay: float = 1.0
    
    request: RequestConfig = Field(default_factory=RequestConfig)


class TradingConfig(BaseModel):
    """交易配置"""
    default_slippage: float = 0.01
    max_slippage: float = 0.05
    max_order_size: float = 1000
    min_order_size: float = 1
    default_expiry_minutes: int = 10


class AppConfig(BaseSettings):
    """应用总配置"""
    app_name: str = "Polymarket Trader"
    version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False
    
    blockchain: BlockchainConfig = Field(default_factory=BlockchainConfig)
    polymarket: PolymarketConfig = Field(default_factory=PolymarketConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    
    class Config:
        env_prefix = "PM_"
        env_nested_delimiter = "__"


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """
    加载配置文件
    
    优先级:
    1. 传入的配置文件路径
    2. 环境变量 PM_CONFIG_PATH
    3. 默认路径 config/settings.yaml
    """
    # 确定配置文件路径
    if not config_path:
        config_path = os.getenv("PM_CONFIG_PATH", "config/settings.yaml")
    
    config_file = Path(config_path)
    
    # 如果存在配置文件，从文件加载
    if config_file.exists():
        with open(config_file, "r") as f:
            yaml_config = yaml.safe_load(f)
        
        # 展平配置结构
        flattened = _flatten_config(yaml_config)
        return AppConfig(**flattened)
    
    # 否则从环境变量加载
    return AppConfig()


def _flatten_config(config: dict, prefix: str = "") -> dict:
    """展平嵌套配置字典"""
    flattened = {}
    
    for key, value in config.items():
        new_key = f"{prefix}{key}" if not prefix else f"{prefix}_{key}"
        
        if isinstance(value, dict):
            flattened.update(_flatten_config(value, new_key))
        else:
            flattened[new_key] = value
    
    return flattened
