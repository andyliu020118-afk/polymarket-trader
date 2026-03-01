"""CLI 界面"""

import asyncio
import os
from decimal import Decimal

import typer
from rich.console import Console
from rich.table import Table
from loguru import logger

from ..infrastructure.blockchain_client import BlockchainClient
from ..infrastructure.polymarket_client import PolymarketClient
from ..application.trading_service import TradingService, TradingConfig, OrderRequest
from ..application.risk_service import RiskService, RiskConfig
from ..domain.enums import OrderSide


app = typer.Typer(help="Polymarket 自动化交易系统")
console = Console()


def get_trading_service() -> TradingService:
    """获取交易服务实例"""
    blockchain = BlockchainClient()
    polymarket = PolymarketClient()
    risk = RiskService(RiskConfig())
    config = TradingConfig()
    
    return TradingService(
        blockchain_client=blockchain,
        polymarket_client=polymarket,
        risk_service=risk,
        config=config
    )


@app.command()
def connect(
    private_key: str = typer.Option(
        None, 
        "--key", "-k",
        help="钱包私钥 (或设置 WALLET_PRIVATE_KEY 环境变量)"
    )
):
    """连接钱包"""
    async def _connect():
        service = get_trading_service()
        try:
            connection = await service.connect_wallet(private_key)
            console.print(f"✅ 钱包连接成功: {connection.address}")
            
            # 显示余额
            balances = service.get_balance()
            table = Table(title="账户余额")
            table.add_column("代币", style="cyan")
            table.add_column("余额", style="green")
            
            for symbol, balance in balances.items():
                table.add_row(symbol, f"{balance:.4f}")
            
            console.print(table)
            
        except Exception as e:
            console.print(f"❌ 连接失败: {e}", style="red")
            raise typer.Exit(1)
    
    asyncio.run(_connect())


@app.command()
def markets(
    limit: int = typer.Option(20, "--limit", "-l", help="显示市场数量"),
    min_liquidity: float = typer.Option(10000, "--min-liquidity", help="最小流动性")
):
    """列出可交易的市场"""
    async def _list_markets():
        service = get_trading_service()
        
        try:
            all_markets = await service.get_markets()
            
            # 过滤
            filtered = [
                m for m in all_markets 
                if m.liquidity_usd >= Decimal(str(min_liquidity)) and m.is_tradable()
            ][:limit]
            
            if not filtered:
                console.print("没有找到符合条件的市场", style="yellow")
                return
            
            table = Table(title=f"可交易市场 (共 {len(filtered)} 个)")
            table.add_column("市场ID", style="dim", no_wrap=True)
            table.add_column("标题", style="cyan", max_width=50)
            table.add_column("类别", style="blue")
            table.add_column("价格", style="green")
            table.add_column("流动性", style="yellow")
            
            for market in filtered:
                price = market.current_price.yes_price if market.current_price else Decimal("0")
                table.add_row(
                    market.market_id[:16] + "...",
                    market.title[:50],
                    market.category,
                    f"{price:.2%}",
                    f"${market.liquidity_usd:,.0f}"
                )
            
            console.print(table)
            
        except Exception as e:
            console.print(f"❌ 获取市场列表失败: {e}", style="red")
            raise typer.Exit(1)
    
    asyncio.run(_list_markets())


@app.command()
def balance():
    """查询账户余额"""
    service = get_trading_service()
    
    try:
        balances = service.get_balance()
        
        table = Table(title="账户余额")
        table.add_column("代币", style="cyan")
        table.add_column("余额", style="green")
        
        for symbol, balance in balances.items():
            table.add_row(symbol, f"{balance:.6f}")
        
        console.print(table)
        
    except Exception as e:
        console.print(f"❌ 查询余额失败: {e}", style="red")
        raise typer.Exit(1)


@app.command()
def order(
    market_id: str = typer.Argument(..., help="市场ID (condition_id)"),
    side: str = typer.Argument(..., help="方向: buy_yes/buy_no/sell_yes/sell_no"),
    size: float = typer.Argument(..., help="交易数量"),
    price: float = typer.Option(None, "--price", "-p", help="限价 (不填为市价单)"),
):
    """创建订单"""
    async def _create_order():
        service = get_trading_service()
        
        # 解析方向
        side_map = {
            "buy_yes": OrderSide.BUY_YES,
            "buy_no": OrderSide.BUY_NO,
            "sell_yes": OrderSide.SELL_YES,
            "sell_no": OrderSide.SELL_NO,
        }
        
        if side.lower() not in side_map:
            console.print(f"❌ 无效的方向: {side}. 可用: buy_yes, buy_no, sell_yes, sell_no", style="red")
            raise typer.Exit(1)
        
        try:
            request = OrderRequest(
                market_id=market_id,
                side=side_map[side.lower()],
                size=Decimal(str(size)),
                price=Decimal(str(price)) if price else None
            )
            
            order = await service.create_order(request)
            
            console.print(f"✅ 订单创建成功")
            console.print(f"   订单ID: {order.order_id}")
            console.print(f"   市场: {market_id}")
            console.print(f"   方向: {side}")
            console.print(f"   数量: {size}")
            console.print(f"   价格: {order.price:.4f}")
            console.print(f"   状态: {order.status.value}")
            
        except Exception as e:
            console.print(f"❌ 创建订单失败: {e}", style="red")
            raise typer.Exit(1)
    
    asyncio.run(_create_order())


@app.command()
def orders(
    market_id: str = typer.Option(None, "--market", "-m", help="按市场过滤")
):
    """查看订单列表"""
    service = get_trading_service()
    
    orders_list = service.get_orders(market_id)
    
    if not orders_list:
        console.print("暂无订单", style="yellow")
        return
    
    table = Table(title=f"订单列表 (共 {len(orders_list)} 个)")
    table.add_column("订单ID", style="dim", no_wrap=True)
    table.add_column("市场", style="cyan")
    table.add_column("方向", style="blue")
    table.add_column("价格", style="green")
    table.add_column("数量", style="yellow")
    table.add_column("已成交", style="magenta")
    table.add_column("状态", style="red")
    
    for order in orders_list:
        table.add_row(
            order.order_id[:12] + "...",
            order.market_id[:12] + "...",
            order.side.value,
            f"{order.price:.4f}",
            f"{order.size:.2f}",
            f"{order.filled_size:.2f}",
            order.status.value
        )
    
    console.print(table)


@app.command()
def positions():
    """查看持仓"""
    service = get_trading_service()
    
    positions_list = service.get_all_positions()
    
    if not positions_list:
        console.print("暂无持仓", style="yellow")
        return
    
    table = Table(title=f"持仓列表 (共 {len(positions_list)} 个)")
    table.add_column("持仓ID", style="dim")
    table.add_column("市场", style="cyan")
    table.add_column("Yes代币", style="green")
    table.add_column("No代币", style="blue")
    table.add_column("净敞口", style="yellow")
    table.add_column("入场均价", style="magenta")
    table.add_column("总成本", style="red")
    
    for pos in positions_list:
        table.add_row(
            pos.position_id[:12] + "...",
            pos.market_id[:12] + "...",
            f"{pos.yes_tokens:.4f}",
            f"{pos.no_tokens:.4f}",
            f"{pos.net_exposure:.4f}",
            f"{pos.avg_entry_price:.4f}",
            f"${pos.total_cost:.2f}"
        )
    
    console.print(table)
    
    # 投资组合摘要
    summary = service.get_portfolio_summary()
    console.print(f"\n📊 投资组合: {summary['total_positions']} 个持仓, 总成本 ${summary['total_cost']:.2f}")


@app.command()
def risk_status():
    """查看风控状态"""
    service = get_trading_service()
    
    if not service.risk:
        console.print("风控服务未启用", style="yellow")
        return
    
    status = service.risk.get_status()
    
    table = Table(title="风控状态")
    table.add_column("项目", style="cyan")
    table.add_column("状态", style="green")
    
    table.add_row("交易允许", "✅ 是" if status["trading_allowed"] else "❌ 否")
    table.add_row("暂停至", status["paused_until"] or "-")
    table.add_row("规则数量", str(status["rules_count"]))
    table.add_row("近期触发", str(status["recent_triggers"]))
    
    console.print(table)


def main():
    """主入口"""
    # 配置日志
    logger.add(
        "logs/polymarket-trader.log",
        rotation="1 day",
        retention="7 days",
        level="INFO"
    )
    
    # 创建日志目录
    os.makedirs("logs", exist_ok=True)
    
    app()


if __name__ == "__main__":
    main()
