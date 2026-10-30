"""Planted effects E1-E5, applied only through synthetic tables (V2-SYN-1).

Each plant follows the ``PlantPlugin`` shape of ``Interfaces.md`` section
7.2 - a ``name`` and an ``inject`` hook - plus an optional ``plan_prices``
hook for plants that change list prices before demand is derived from them.
Every change a plant makes is recorded in the manifest with its planted size
and its realised size on the generated rows; nothing is planted without an
entry (DATA-4).

Plants run in this fixed order.
"""

from __future__ import annotations

from .e1_marketing_cut import MarketingCut
from .e2_stockouts import Stockouts
from .e3_promotion import Promotion
from .e4_delivery_delay import DeliveryDelay
from .e5_price_change import PriceChange

PLANTS = (MarketingCut(), Stockouts(), Promotion(), DeliveryDelay(), PriceChange())

__all__ = ["PLANTS"]
