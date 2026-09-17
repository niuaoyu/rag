
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

# 管理数据库连接的引擎对象
engine = create_engine(
    settings.database_url, 
    connect_args={"check_same_thread": False}, # sqlite 特有的参数，允许在不同线程中使用同一个连接
    echo=True # 打印SQL语句
    )

# 工厂管理一次操作
SessionLocal = sessionmaker(
    autocommit=False,   # 显式 commit，事务边界清晰
    autoflush=False ,   # 别自动 flush，避免意外 SQL
    bind=engine
    )

def get_db():
    """
    生成数据库会话对象，使用完毕后关闭连接
    """
    db = SessionLocal()
    try:
        yield db 
        # 生成器，返回 db 对象给调用者 用完还必须回来，然后执行 finally 里的 db.close()，关闭连接
        # 不能用 return db，因为 return 会直接退出函数，finally 里的 db.close() 就不会执行了
        # 业务和事务逻辑分离
        # commit和rollback都在业务函数里处理，get_db只负责生成和关闭连接，
    finally:
        db.close()