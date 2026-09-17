

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
# from app.db import SessionLocal,engine
from app.models.user import User,Base
from datetime import datetime



test_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, echo=True)
sessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
db = sessionLocal()
Base.metadata.create_all(bind=test_engine)
# 遍历所有继承base的模型类，为每个类生成表 create table if not exists
# 用之前必须先from app.models.user import User 


user = User(id=1666, email="sss", password_hash="sss",created_at=datetime.now())
db.add(user)
db.commit()
db.refresh(user)
print(db.get(User,1666).id)
db.close()
