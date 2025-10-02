from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.engine import Engine
from sqlalchemy import event
import config

# Ensure SQLite has foreign key support
def _enable_sqlite_foreign_keys(dbapi_conn, conn_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

engine = create_engine(config.DB_URL, connect_args={"check_same_thread": False})
event.listen(engine, 'connect', _enable_sqlite_foreign_keys)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def init_db():
    import models  # noqa: F401 - ensure models are imported so Base.metadata.create_all works
    Base.metadata.create_all(bind=engine)
