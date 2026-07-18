from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Ad(Base):
    """The pool of ads that can be served and clicked. Replaces the in-memory
    _FAKE_ADS list once /ads/serve reads from the DB."""

    __tablename__ = "ad"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    image_url: Mapped[str]
    destination_url: Mapped[str]
    is_active: Mapped[bool] = mapped_column(default=True)
    # server_default=func.now() lets the DB stamp the time even for rows
    # inserted outside the ORM (e.g. a seed script or raw SQL).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ClickMetric(Base):
    """Durable per-minute roll-up: one row per (ad, minute). The consumer
    upserts closed minute buckets here from Redis, and the cold-path metrics
    read serves older windows from this table.

    TODO (you): define the columns. You'll need:
      - id: Mapped[int]  primary key
      - ad_id: Mapped[int]  a foreign key to ad.id, indexed
            mapped_column(ForeignKey("ad.id"), index=True)
      - minute_bucket: Mapped[datetime]  the minute window (timezone-aware)
            mapped_column(DateTime(timezone=True))
      - click_count: Mapped[int]  clicks in that minute
      - a table-level UniqueConstraint on (ad_id, minute_bucket) — this is the
        upsert key that makes a re-flush idempotent. Add it via:
            __table_args__ = (UniqueConstraint("ad_id", "minute_bucket"),)
    """

    __tablename__ = "click_metric"

    id: Mapped[int] = mapped_column(primary_key=True)
    ad_id: Mapped[int] = mapped_column(ForeignKey("ad.id"), index=True)
    minute_bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    click_count: Mapped[int]
    # Impressions (ad shown) for this ad+minute. server_default="0" so the
    # migration can backfill existing rows without a NULL violation.
    impression_count: Mapped[int] = mapped_column(server_default="0")

    __table_args__ = (UniqueConstraint("ad_id", "minute_bucket"),)
