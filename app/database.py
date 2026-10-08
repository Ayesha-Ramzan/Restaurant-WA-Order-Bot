"""
Database setup and models for the Restaurant WhatsApp Bot.

WHY this file exists:
Keeping all database structure in ONE file makes it easy to see your
entire data design at a glance, and easy to update later.
"""

import os
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./restaurant.db")

# WHY: SQLite for local testing (zero setup), Postgres for real server (via .env)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    address = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    orders = relationship("Order", back_populates="customer")


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)   # e.g. "Main Course", "Drinks"
    price = Column(Float, nullable=False)
    is_available = Column(Boolean, default=True)
    is_recommended = Column(Boolean, default=False)  # for "our favourite dishes"


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    items_json = Column(String, nullable=False)   # simple JSON string of ordered items
    total_price = Column(Float, nullable=False)
    status = Column(String, default="pending")    # pending -> confirmed -> delivered
    created_at = Column(DateTime, default=datetime.utcnow)      # when order was PLACED
    placed_at = Column(DateTime, nullable=True)                 # when order was confirmed & paid
    delivered_at = Column(DateTime, nullable=True)              # expected/actual delivery time
    payment_method = Column(String, nullable=True)              # "cash" or "jazzcash"

    customer = relationship("Customer", back_populates="orders")


class FAQ(Base):
    __tablename__ = "faqs"

    id = Column(Integer, primary_key=True, index=True)
    question = Column(String, nullable=False)
    answer = Column(String, nullable=False)


def init_db():
    """WHY: creates all tables automatically the first time the app runs."""
    Base.metadata.create_all(bind=engine)
    # WHY: migration for an existing restaurant.db - add the new time columns
    # if the table was created before they existed (SQLite has no IF NOT EXISTS
    # for columns, so we check the table info first).
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    if "orders" in inspector.get_table_names():
        existing = {c["name"] for c in inspector.get_columns("orders")}
        with engine.begin() as conn:
            if "placed_at" not in existing:
                conn.execute(text("ALTER TABLE orders ADD COLUMN placed_at DATETIME"))
            if "delivered_at" not in existing:
                conn.execute(text("ALTER TABLE orders ADD COLUMN delivered_at DATETIME"))
            if "payment_method" not in existing:
                conn.execute(text("ALTER TABLE orders ADD COLUMN payment_method VARCHAR"))


def get_db():
    """WHY: gives FastAPI a fresh, safe database session per request, then closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
