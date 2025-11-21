import psycopg2
import sys
import os

# 数据库连接配置
# 优先从环境变量读取，否则使用默认配置
DB_CONFIG = {
    'host': os.getenv('DB_HOST', '10.128.21.148'),
    'port': os.getenv('DB_PORT', '5431'),
    'dbname': os.getenv('DB_NAME', 'cas25_test'),
    'user': os.getenv('DB_USER', 'readonly_cas25_test'),
    'password': os.getenv('DB_PASSWORD', 'readonly_cas25_test')
}

def get_db_connection():
    """
    建立并返回数据库连接。
    如果连接失败，打印错误并退出程序。
    
    支持从环境变量读取配置：
    - DB_HOST: 数据库主机地址
    - DB_PORT: 数据库端口
    - DB_NAME: 数据库名称
    - DB_USER: 数据库用户名
    - DB_PASSWORD: 数据库密码
    """
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except psycopg2.Error as e:
        print(f"❌ 数据库连接失败: {e}")
        print(f"   配置信息: host={DB_CONFIG['host']}, port={DB_CONFIG['port']}, dbname={DB_CONFIG['dbname']}, user={DB_CONFIG['user']}")
        sys.exit(1)

