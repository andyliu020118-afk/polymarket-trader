"""区块链客户端 - 钱包连接和交互"""

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Dict, Any

from eth_account import Account
from eth_typing import ChecksumAddress
from loguru import logger
from web3 import Web3
from web3.types import TxParams, Wei


USDC_CONTRACT_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # Polygon Mainnet
USDC_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
]


@dataclass
class WalletConnection:
    """钱包连接信息"""
    address: ChecksumAddress
    connected: bool = False
    chain_id: Optional[int] = None
    
    def __str__(self) -> str:
        return f"Wallet({self.address[:10]}...{self.address[-8:]}, connected={self.connected})"


@dataclass
class TokenBalance:
    """代币余额"""
    symbol: str
    balance: Decimal
    decimals: int
    
    def __str__(self) -> str:
        return f"{self.balance} {self.symbol}"


class BlockchainClient:
    """区块链客户端 - 处理钱包连接和交易"""
    
    def __init__(self, rpc_url: Optional[str] = None, private_key: Optional[str] = None):
        """
        初始化区块链客户端
        
        Args:
            rpc_url: Polygon RPC URL (默认使用公共节点)
            private_key: 钱包私钥 (从环境变量读取更安全)
        """
        # 默认使用 Polygon 公共 RPC
        self.rpc_url = rpc_url or os.getenv(
            "POLYGON_RPC_URL", 
            "https://polygon-rpc.com"
        )
        
        # 优先从参数获取，其次环境变量
        self._private_key = private_key or os.getenv("WALLET_PRIVATE_KEY")
        
        # 初始化 Web3
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        
        # 钱包连接
        self._connection: Optional[WalletConnection] = None
        self._account: Optional[Account] = None
        
        # USDC 合约
        self._usdc_contract = None
        
        logger.info(f"BlockchainClient initialized with RPC: {self.rpc_url}")
    
    @property
    def is_connected(self) -> bool:
        """检查是否已连接钱包"""
        return self._connection is not None and self._connection.connected
    
    @property
    def wallet_address(self) -> Optional[ChecksumAddress]:
        """获取当前钱包地址"""
        return self._connection.address if self._connection else None
    
    def connect_with_private_key(self, private_key: Optional[str] = None) -> WalletConnection:
        """
        使用私钥连接钱包
        
        Args:
            private_key: 钱包私钥 (0x开头)
        
        Returns:
            WalletConnection: 钱包连接信息
        """
        key = private_key or self._private_key
        if not key:
            raise ValueError("Private key not provided. Set WALLET_PRIVATE_KEY env var.")
        
        try:
            # 创建账户
            self._account = Account.from_key(key)
            address = self.w3.to_checksum_address(self._account.address)
            
            # 验证连接
            chain_id = self.w3.eth.chain_id
            
            self._connection = WalletConnection(
                address=address,
                connected=True,
                chain_id=chain_id
            )
            
            # 初始化 USDC 合约
            self._init_usdc_contract()
            
            logger.info(f"Wallet connected: {address} on chain {chain_id}")
            return self._connection
            
        except Exception as e:
            logger.error(f"Failed to connect wallet: {e}")
            raise
    
    def connect_external_wallet(self, address: str) -> WalletConnection:
        """
        连接外部钱包 (如 MetaMask/Phantom)
        仅用于查询，不能发送交易
        
        Args:
            address: 钱包地址
        """
        try:
            checksum_address = self.w3.to_checksum_address(address)
            chain_id = self.w3.eth.chain_id
            
            self._connection = WalletConnection(
                address=checksum_address,
                connected=True,
                chain_id=chain_id
            )
            
            # 初始化 USDC 合约 (只读)
            self._init_usdc_contract()
            
            logger.info(f"External wallet connected: {checksum_address}")
            return self._connection
            
        except Exception as e:
            logger.error(f"Failed to connect external wallet: {e}")
            raise
    
    def _init_usdc_contract(self) -> None:
        """初始化 USDC 合约"""
        if self._usdc_contract is None:
            self._usdc_contract = self.w3.eth.contract(
                address=self.w3.to_checksum_address(USDC_CONTRACT_ADDRESS),
                abi=USDC_ABI
            )
    
    def get_native_balance(self) -> Decimal:
        """获取原生代币 (MATIC) 余额"""
        if not self.is_connected:
            raise RuntimeError("Wallet not connected")
        
        balance_wei = self.w3.eth.get_balance(self.wallet_address)
        return Decimal(self.w3.from_wei(balance_wei, 'ether'))
    
    def get_usdc_balance(self) -> TokenBalance:
        """获取 USDC 余额"""
        if not self.is_connected:
            raise RuntimeError("Wallet not connected")
        
        if not self._usdc_contract:
            raise RuntimeError("USDC contract not initialized")
        
        try:
            # 获取 decimals
            decimals = self._usdc_contract.functions.decimals().call()
            
            # 获取余额
            balance_raw = self._usdc_contract.functions.balanceOf(
                self.wallet_address
            ).call()
            
            balance = Decimal(balance_raw) / (10 ** decimals)
            
            return TokenBalance(
                symbol="USDC",
                balance=balance,
                decimals=decimals
            )
            
        except Exception as e:
            logger.error(f"Failed to get USDC balance: {e}")
            raise
    
    def get_all_balances(self) -> Dict[str, TokenBalance]:
        """获取所有余额"""
        balances = {}
        
        # MATIC
        matic_balance = self.get_native_balance()
        balances["MATIC"] = TokenBalance(
            symbol="MATIC",
            balance=matic_balance,
            decimals=18
        )
        
        # USDC
        balances["USDC"] = self.get_usdc_balance()
        
        return balances
    
    def build_transaction(self, to: str, value: Decimal, 
                         data: bytes = b"") -> TxParams:
        """
        构建交易
        
        Args:
            to: 目标地址
            value: 发送金额 (MATIC)
            data: 交易数据
        """
        if not self.is_connected or not self._account:
            raise RuntimeError("Wallet not connected with private key")
        
        nonce = self.w3.eth.get_transaction_count(self.wallet_address)
        
        tx: TxParams = {
            'nonce': nonce,
            'to': self.w3.to_checksum_address(to),
            'value': self.w3.to_wei(value, 'ether'),
            'gas': 21000,  # 基础转账 gas
            'gasPrice': self.w3.eth.gas_price,
            'data': data,
            'chainId': self.w3.eth.chain_id,
        }
        
        return tx
    
    def sign_and_send_transaction(self, tx: TxParams) -> str:
        """
        签名并发送交易
        
        Args:
            tx: 交易参数
            
        Returns:
            交易哈希
        """
        if not self._account:
            raise RuntimeError("No private key available for signing")
        
        try:
            # 签名
            signed = self._account.sign_transaction(tx)
            
            # 发送
            tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
            
            logger.info(f"Transaction sent: {tx_hash.hex()}")
            return tx_hash.hex()
            
        except Exception as e:
            logger.error(f"Failed to send transaction: {e}")
            raise
    
    def wait_for_receipt(self, tx_hash: str, timeout: int = 120) -> Dict[str, Any]:
        """等待交易确认"""
        try:
            receipt = self.w3.eth.wait_for_transaction_receipt(
                tx_hash, 
                timeout=timeout
            )
            return dict(receipt)
        except Exception as e:
            logger.error(f"Failed to get transaction receipt: {e}")
            raise
