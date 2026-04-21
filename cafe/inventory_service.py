"""Stock movements from menu BOM and order lines."""
from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import (
    Ingredient,
    IngredientStock,
    MenuItemRecipe,
    StockMovement,
    menu_item,
    order,
)


def _aggregate_consumption_for_order(order_obj: order) -> dict[int, Decimal]:
    """Map ingredient_id -> total quantity to deduct for this order."""
    try:
        payload = json.loads(order_obj.items_json or '{}')
    except json.JSONDecodeError:
        return {}
    totals: dict[int, Decimal] = defaultdict(lambda: Decimal('0'))
    for menu_id_str, entry in payload.items():
        try:
            qty = int(entry[0]) if isinstance(entry, (list, tuple)) else int(entry.get('quantity', 1))
        except (TypeError, ValueError, IndexError, AttributeError):
            qty = 1
        try:
            mid = int(menu_id_str)
        except ValueError:
            continue
        if not menu_item.objects.filter(id=mid, restaurant_id=order_obj.restaurant_id).exists():
            continue
        for line in MenuItemRecipe.objects.filter(menu_item_id=mid).select_related('ingredient'):
            totals[line.ingredient_id] += Decimal(line.quantity) * Decimal(qty)
    return dict(totals)


@transaction.atomic
def consume_stock_for_order(order_obj: order, user=None) -> bool:
    """
    Deduct BOM stock when kitchen starts preparing. Idempotent via stock_consumed_at.
    Returns True if consumption ran (or already ran), False if nothing to do.
    """
    if order_obj.stock_consumed_at is not None:
        return True
    totals = _aggregate_consumption_for_order(order_obj)
    if not totals:
        order_obj.stock_consumed_at = timezone.now()
        order_obj.save(update_fields=['stock_consumed_at'])
        return True

    for ing_id, need in totals.items():
        if need <= 0:
            continue
        try:
            ing = Ingredient.objects.select_for_update().get(
                id=ing_id, restaurant_id=order_obj.restaurant_id, is_active=True
            )
        except Ingredient.DoesNotExist:
            continue
        stock, _ = IngredientStock.objects.select_for_update().get_or_create(
            ingredient=ing, defaults={'quantity_on_hand': Decimal('0')}
        )
        delta = -need
        stock.quantity_on_hand += delta
        stock.save(update_fields=['quantity_on_hand', 'updated_at'])
        StockMovement.objects.create(
            restaurant_id=order_obj.restaurant_id,
            ingredient=ing,
            quantity_delta=delta,
            movement_type=StockMovement.MOVEMENT_CONSUMPTION,
            order_ref=order_obj,
            notes='Order consumption (preparing)',
            created_by=user,
        )

    order_obj.stock_consumed_at = timezone.now()
    order_obj.save(update_fields=['stock_consumed_at'])
    return True


@transaction.atomic
def reverse_stock_for_order(order_obj: order, user=None) -> None:
    """Reverse consumption movements when an order is cancelled after stock was taken."""
    if not order_obj.stock_consumed_at:
        return
    movements = list(
        StockMovement.objects.filter(
            order_ref=order_obj,
            movement_type=StockMovement.MOVEMENT_CONSUMPTION,
        ).select_related('ingredient')
    )
    if not movements:
        order_obj.stock_consumed_at = None
        order_obj.save(update_fields=['stock_consumed_at'])
        return
    for m in movements:
        ing = m.ingredient
        qty_back = -m.quantity_delta  # positive amount to add back
        if qty_back <= 0:
            continue
        stock, _ = IngredientStock.objects.select_for_update().get_or_create(
            ingredient=ing, defaults={'quantity_on_hand': Decimal('0')}
        )
        stock.quantity_on_hand += qty_back
        stock.save(update_fields=['quantity_on_hand', 'updated_at'])
        StockMovement.objects.create(
            restaurant_id=order_obj.restaurant_id,
            ingredient=ing,
            quantity_delta=qty_back,
            movement_type=StockMovement.MOVEMENT_REVERSAL,
            order_ref=order_obj,
            notes='Cancelled order stock reversal',
            created_by=user,
        )
    movements.delete()
    order_obj.stock_consumed_at = None
    order_obj.save(update_fields=['stock_consumed_at'])
