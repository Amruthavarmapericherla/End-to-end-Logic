from __future__ import annotations
import logging
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, create_engine
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.engine import Engine

from config import CONFIG
from scraper import ParsedServiceInfo

log = logging.getLogger(__name__)


class MySQLRepo:
    def __init__(self):
        self.engine: Engine = create_engine(CONFIG.MYSQL_URL, pool_pre_ping=True)
        self.meta = MetaData()
        self.table = Table(
            CONFIG.MYSQL_TABLE,
            self.meta,
            Column("ico", String(64), primary_key=True),
            Column("services_active", String(1024)),
            Column("commitment_end", DateTime, nullable=True),
            Column("price_cards", String(2048)),
            Column("updated_at", DateTime, nullable=False),
            mysql_engine="InnoDB",
            mysql_charset="utf8mb4",
        )
        self.meta.create_all(self.engine)

    def upsert_summary(self, ico: str, parsed: ParsedServiceInfo) -> None:
        values = {
            "ico": ico,
            "services_active": ", ".join(parsed.services_active),
            "commitment_end": parsed.commitment_end_date,
            "price_cards": "; ".join(parsed.price_cards),
            "updated_at": datetime.utcnow(),
        }
        with self.engine.begin() as conn:
            stmt = mysql_insert(self.table).values(**values)
            stmt = stmt.on_duplicate_key_update(
                services_active=stmt.inserted.services_active,
                commitment_end=stmt.inserted.commitment_end,
                price_cards=stmt.inserted.price_cards,
                updated_at=stmt.inserted.updated_at,
            )
            conn.execute(stmt)
