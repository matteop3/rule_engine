"""
Price list fixtures for tests.
Provides reusable fixtures and helpers for creating price lists and items.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.domain import PriceList, PriceListItem


@pytest.fixture(scope="function")
def price_list(db_session: Session) -> PriceList:
    """Creates a PriceList with broad validity for general test use."""
    pl = PriceList(
        name="Test Price List",
        description="Price list for testing",
        valid_from=dt.date(2020, 1, 1),
        valid_to=dt.date(9999, 12, 31),
    )
    db_session.add(pl)
    db_session.commit()
    db_session.refresh(pl)
    return pl


def create_price_list_with_items(
    db: Session,
    items: dict[str, Decimal],
    name: str = "Test Price List",
    valid_from: dt.date | None = None,
    valid_to: dt.date | None = None,
) -> PriceList:
    """
    Create a price list with items in one call.

    Args:
        db: Database session
        items: Mapping of part_number → unit_price
        name: Price list name
        valid_from: Start date (default: 2020-01-01)
        valid_to: End date (default: 9999-12-31)

    Returns:
        The created PriceList with items committed
    """
    vf = valid_from or dt.date(2020, 1, 1)
    vt = valid_to or dt.date(9999, 12, 31)

    pl = PriceList(name=name, valid_from=vf, valid_to=vt)
    db.add(pl)
    db.flush()

    for part_number, unit_price in items.items():
        pli = PriceListItem(
            price_list_id=pl.id,
            part_number=part_number,
            unit_price=unit_price,
            valid_from=vf,
            valid_to=vt,
        )
        db.add(pli)

    db.commit()
    db.refresh(pl)
    return pl
