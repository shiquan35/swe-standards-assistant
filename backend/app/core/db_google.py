from contextlib import contextmanager

# TODO make sure to install the required packages in your environment:
from google.cloud.sql.connector import Connector, IPTypes
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.env import env

DB_USER = env.DB_USER
DB_PASS = env.DB_PASS
DB_NAME = env.DB_NAME
DB_CONNECTION_NAME = env.DB_CONNECTION_NAME
# Create Cloud SQL Connector instance
connector = Connector()


def getconn():
    return connector.connect(
        DB_CONNECTION_NAME,
        "pg8000",  # or "psycopg2" if you prefer
        user=DB_USER,
        password=DB_PASS,
        db=DB_NAME,
        ip_type=IPTypes.PUBLIC,  # or PRIVATE if using private IP
    )


# SQLAlchemy engine using Cloud SQL Connector
engine = create_engine("postgresql+pg8000://", creator=getconn)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_db_session():
    """Create a new database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
