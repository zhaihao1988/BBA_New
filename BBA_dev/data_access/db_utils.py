import os
import sys
import psycopg2
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL

# 数据库连接配置（test 与 qa 两套）
DB_CONFIGS = {
    'test': {
        'host': os.getenv('DB_HOST', '10.128.21.148'),
        'port': os.getenv('DB_PORT', '5431'),
        'dbname': os.getenv('DB_NAME', 'cas25_test'),
        'user': os.getenv('DB_USER', 'readonly_cas25_test'),
        'password': os.getenv('DB_PASSWORD', 'readonly_cas25_test')
    },
    'qa': {
        'host': os.getenv('QA_DB_HOST', '10.128.21.134'),
        'port': os.getenv('QA_DB_PORT', '5432'),
        'dbname': os.getenv('QA_DB_NAME', 'cas25_test_qa'),
        'user': os.getenv('QA_DB_USER', 'cas25_qa'),
        'password': os.getenv('QA_DB_PASSWORD', 'cas25_qa')
    }
}


def get_db_connection(env: str = 'test'):
    """
    建立指定环境（test/qa）的数据库连接。
    
    Args:
        env: 'test' 或 'qa'，默认为 'test'
    """
    if env not in DB_CONFIGS:
        raise ValueError(f"未知数据库环境 '{env}'，目前支持 {list(DB_CONFIGS.keys())}")
    config = DB_CONFIGS[env]
    try:
        return psycopg2.connect(**config)
    except psycopg2.Error as e:
        print(f"❌ 数据库连接失败: {e}")
        print(f"   配置信息[{env}]: host={config['host']}, port={config['port']}, dbname={config['dbname']}, user={config['user']}")
        sys.exit(1)


_ENGINE_CACHE: dict[str, Engine] = {}


def _build_sa_url(config: dict) -> URL:
    return URL.create(
        "postgresql+psycopg2",
        username=config['user'],
        password=config['password'],
        host=config['host'],
        port=int(config['port']),
        database=config['dbname']
    )


def get_sa_engine(env: str = 'test') -> Engine:
    """
    获取 SQLAlchemy Engine，用于 pandas/SQLAlchemy 查询，避免 DBAPI 警告。
    
    优化连接池配置，避免多进程时连接数过多：
    - pool_size: 每个进程的连接池大小（建议2-5）
    - max_overflow: 允许超出pool_size的连接数（建议0-3）
    - pool_pre_ping: 连接前检查连接是否有效
    """
    if env not in DB_CONFIGS:
        raise ValueError(f"未知数据库环境 '{env}'，目前支持 {list(DB_CONFIGS.keys())}")
    if env not in _ENGINE_CACHE:
        config = DB_CONFIGS[env]
        _ENGINE_CACHE[env] = create_engine(
            _build_sa_url(config),
            pool_size=3,  # 每个进程最多3个连接
            max_overflow=2,  # 允许超出2个连接
            pool_pre_ping=True,  # 连接前检查有效性
            pool_recycle=3600,  # 1小时后回收连接
            echo=False
        )
    return _ENGINE_CACHE[env]

