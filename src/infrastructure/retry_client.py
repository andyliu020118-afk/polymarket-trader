"""API 客户端增强 - 订单提交和重试机制"""

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Dict, Any, Callable
from functools import wraps

import httpx
from loguru import logger


@dataclass
class RetryConfig:
    """重试配置"""
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    retry_on_status: tuple = (429, 500, 502, 503, 504)


class RetryableHTTPClient:
    """支持重试的 HTTP 客户端"""
    
    def __init__(self, config: Optional[RetryConfig] = None, **client_kwargs):
        self.config = config or RetryConfig()
        self._client = httpx.AsyncClient(**client_kwargs)
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._client.aclose()
    
    def _calculate_delay(self, attempt: int) -> float:
        """计算退避延迟 (指数退避 + 抖动)"""
        import random
        
        delay = self.config.base_delay * (self.config.exponential_base ** attempt)
        delay = min(delay, self.config.max_delay)
        
        # 添加抖动 (±20%)
        jitter = delay * 0.2 * (2 * random.random() - 1)
        return delay + jitter
    
    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """
        发送请求，带重试机制
        
        Args:
            method: HTTP 方法
            url: 请求URL
            **kwargs: 其他请求参数
            
        Returns:
            httpx.Response: 响应对象
        """
        last_exception = None
        
        for attempt in range(self.config.max_retries + 1):
            try:
                response = await self._client.request(method, url, **kwargs)
                
                # 检查是否需要重试
                if response.status_code in self.config.retry_on_status:
                    if attempt < self.config.max_retries:
                        delay = self._calculate_delay(attempt)
                        logger.warning(
                            f"Request failed with {response.status_code}, "
                            f"retrying in {delay:.2f}s (attempt {attempt + 1}/{self.config.max_retries})"
                        )
                        await asyncio.sleep(delay)
                        continue
                
                response.raise_for_status()
                return response
                
            except httpx.HTTPStatusError as e:
                last_exception = e
                if attempt < self.config.max_retries:
                    delay = self._calculate_delay(attempt)
                    logger.warning(f"HTTP error {e.response.status_code}, retrying in {delay:.2f}s")
                    await asyncio.sleep(delay)
                else:
                    raise
                    
            except (httpx.NetworkError, httpx.TimeoutException) as e:
                last_exception = e
                if attempt < self.config.max_retries:
                    delay = self._calculate_delay(attempt)
                    logger.warning(f"Network error: {e}, retrying in {delay:.2f}s")
                    await asyncio.sleep(delay)
                else:
                    raise
        
        # 所有重试都失败了
        if last_exception:
            raise last_exception
        
        raise RuntimeError("Unexpected error in retry loop")
    
    async def get(self, url: str, **kwargs) -> httpx.Response:
        """GET 请求"""
        return await self.request("GET", url, **kwargs)
    
    async def post(self, url: str, **kwargs) -> httpx.Response:
        """POST 请求"""
        return await self.request("POST", url, **kwargs)


def retry(**retry_kwargs):
    """
    重试装饰器
    
    用法:
        @retry(max_retries=3, base_delay=1.0)
        async def my_async_function():
            ...
    """
    config = RetryConfig(**retry_kwargs)
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(config.max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                    
                except Exception as e:
                    last_exception = e
                    
                    if attempt < config.max_retries:
                        delay = config.base_delay * (config.exponential_base ** attempt)
                        delay = min(delay, config.max_delay)
                        
                        logger.warning(
                            f"{func.__name__} failed: {e}, "
                            f"retrying in {delay:.2f}s (attempt {attempt + 1})"
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"{func.__name__} failed after {config.max_retries} retries")
                        raise
            
            if last_exception:
                raise last_exception
                
        return wrapper
    return decorator
