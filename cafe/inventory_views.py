from decimal import Decimal

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from .models import (
    Ingredient,
    IngredientStock,
    MenuItemRecipe,
    PurchaseOrder,
    PurchaseOrderLine,
    Restaurant,
    StockMovement,
    Supplier,
    menu_item,
)
from .permissions import (
    InventoryManagePermission,
    PurchaseOrderPermission,
    is_restaurant_power_user,
)
from .serializers import (
    IngredientSerializer,
    MenuItemRecipeSerializer,
    PurchaseOrderLineSerializer,
    PurchaseOrderSerializer,
    StockMovementSerializer,
    SupplierSerializer,
)


def resolve_restaurant_for_inventory(request):
    r = getattr(request, 'restaurant', None)
    if r:
        return r
    u = request.user
    if not u.is_authenticated:
        return None
    if getattr(u, 'restaurant', None):
        return u.restaurant
    if hasattr(u, 'staff_profile') and u.staff_profile.restaurant_id:
        return Restaurant.objects.filter(id=u.staff_profile.restaurant_id).first()
    return None


class SupplierViewSet(viewsets.ModelViewSet):
    serializer_class = SupplierSerializer
    permission_classes = [permissions.IsAuthenticated, InventoryManagePermission]

    def get_queryset(self):
        r = resolve_restaurant_for_inventory(self.request)
        qs = Supplier.objects.all().order_by('name')
        if is_restaurant_power_user(self.request.user) and not r:
            return qs
        if not r:
            return Supplier.objects.none()
        return qs.filter(restaurant=r)

    def perform_create(self, serializer):
        r = resolve_restaurant_for_inventory(self.request)
        if not r:
            raise PermissionDenied('Restaurant context is required')
        serializer.save(restaurant=r)


class IngredientViewSet(viewsets.ModelViewSet):
    serializer_class = IngredientSerializer
    permission_classes = [permissions.IsAuthenticated, InventoryManagePermission]

    def get_queryset(self):
        r = resolve_restaurant_for_inventory(self.request)
        qs = Ingredient.objects.all().order_by('name')
        if is_restaurant_power_user(self.request.user) and not r:
            return qs
        if not r:
            return Ingredient.objects.none()
        return qs.filter(restaurant=r)

    def perform_create(self, serializer):
        r = resolve_restaurant_for_inventory(self.request)
        if not r:
            raise PermissionDenied('Restaurant context is required')
        ing = serializer.save(restaurant=r)
        IngredientStock.objects.get_or_create(ingredient=ing, defaults={'quantity_on_hand': Decimal('0')})

    @action(detail=True, methods=['post'])
    def adjust_stock(self, request, pk=None):
        ingredient = self.get_object()
        if not is_restaurant_power_user(request.user) and not request.user.has_perm(
            'cafe.can_manage_inventory'
        ):
            raise PermissionDenied()
        delta = Decimal(str(request.data.get('quantity_delta', 0)))
        notes = request.data.get('notes', '')
        with transaction.atomic():
            stock, _ = IngredientStock.objects.select_for_update().get_or_create(
                ingredient=ingredient, defaults={'quantity_on_hand': Decimal('0')}
            )
            stock.quantity_on_hand += delta
            stock.save(update_fields=['quantity_on_hand', 'updated_at'])
            StockMovement.objects.create(
                restaurant=ingredient.restaurant,
                ingredient=ingredient,
                quantity_delta=delta,
                movement_type=StockMovement.MOVEMENT_ADJUSTMENT,
                notes=notes,
                created_by=request.user,
            )
        return Response(IngredientSerializer(ingredient).data)


class MenuItemRecipeViewSet(viewsets.ModelViewSet):
    serializer_class = MenuItemRecipeSerializer
    permission_classes = [permissions.IsAuthenticated, InventoryManagePermission]

    def get_queryset(self):
        r = resolve_restaurant_for_inventory(self.request)
        qs = MenuItemRecipe.objects.select_related('menu_item', 'ingredient').all()
        if r:
            qs = qs.filter(menu_item__restaurant=r, ingredient__restaurant=r)
        elif not is_restaurant_power_user(self.request.user):
            return MenuItemRecipe.objects.none()
        mid = self.request.query_params.get('menu_item')
        if mid:
            qs = qs.filter(menu_item_id=mid)
        return qs

    def perform_create(self, serializer):
        r = resolve_restaurant_for_inventory(self.request)
        mi = serializer.validated_data.get('menu_item')
        ing = serializer.validated_data.get('ingredient')
        if r and (mi.restaurant_id != r.id or ing.restaurant_id != r.id):
            raise PermissionDenied('Items must belong to your restaurant')
        serializer.save()


class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StockMovementSerializer
    permission_classes = [permissions.IsAuthenticated, InventoryManagePermission]

    def get_queryset(self):
        r = resolve_restaurant_for_inventory(self.request)
        qs = StockMovement.objects.select_related('ingredient').order_by('-created_at')
        if r:
            return qs.filter(restaurant=r)
        if is_restaurant_power_user(self.request.user):
            return qs
        return StockMovement.objects.none()


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    serializer_class = PurchaseOrderSerializer
    permission_classes = [permissions.IsAuthenticated, PurchaseOrderPermission]

    def get_queryset(self):
        r = resolve_restaurant_for_inventory(self.request)
        qs = PurchaseOrder.objects.select_related('supplier').prefetch_related('lines').order_by('-created_at')
        if r:
            return qs.filter(restaurant=r)
        if is_restaurant_power_user(self.request.user):
            return qs
        return PurchaseOrder.objects.none()

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        r = resolve_restaurant_for_inventory(request)
        if not r:
            return Response({'error': 'Restaurant context required'}, status=status.HTTP_400_BAD_REQUEST)
        supplier_id = request.data.get('supplier')
        lines = request.data.get('lines', [])
        if not supplier_id or not lines:
            return Response({'error': 'supplier and lines required'}, status=status.HTTP_400_BAD_REQUEST)
        supplier = get_object_or_404(Supplier, id=supplier_id, restaurant=r)
        po = PurchaseOrder.objects.create(
            restaurant=r,
            supplier=supplier,
            status=request.data.get('status', PurchaseOrder.STATUS_DRAFT),
            reference=request.data.get('reference', ''),
            expected_date=request.data.get('expected_date'),
            notes=request.data.get('notes', ''),
        )
        for row in lines:
            ing = get_object_or_404(Ingredient, id=row['ingredient'], restaurant=r)
            PurchaseOrderLine.objects.create(
                purchase_order=po,
                ingredient=ing,
                quantity_ordered=Decimal(str(row['quantity_ordered'])),
                unit_cost=Decimal(str(row['unit_cost'])) if row.get('unit_cost') is not None else None,
            )
        return Response(PurchaseOrderSerializer(po).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def receive_lines(self, request, pk=None):
        po = self.get_object()
        receipts = request.data.get('receipts', [])
        if not receipts:
            return Response({'error': 'receipts required'}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            for rec in receipts:
                line = get_object_or_404(PurchaseOrderLine, id=rec['line_id'], purchase_order=po)
                qty = Decimal(str(rec['quantity']))
                if qty <= 0:
                    continue
                remaining = line.quantity_ordered - line.quantity_received
                if qty > remaining:
                    return Response(
                        {'error': f'Line {line.id}: cannot receive more than remaining {remaining}'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                ing = line.ingredient
                stock, _ = IngredientStock.objects.select_for_update().get_or_create(
                    ingredient=ing, defaults={'quantity_on_hand': Decimal('0')}
                )
                stock.quantity_on_hand += qty
                stock.save(update_fields=['quantity_on_hand', 'updated_at'])
                line.quantity_received += qty
                line.save(update_fields=['quantity_received'])
                StockMovement.objects.create(
                    restaurant=po.restaurant,
                    ingredient=ing,
                    quantity_delta=qty,
                    movement_type=StockMovement.MOVEMENT_PURCHASE,
                    purchase_order_line=line,
                    notes=f'PO {po.id} receive',
                    created_by=request.user,
                )
            lines = list(po.lines.all())
            all_received = lines and all(
                ln.quantity_received >= ln.quantity_ordered for ln in lines
            )
            any_received = any(ln.quantity_received > 0 for ln in lines)
            if all_received:
                po.status = PurchaseOrder.STATUS_RECEIVED
            elif any_received:
                po.status = PurchaseOrder.STATUS_PARTIAL
            po.save(update_fields=['status', 'updated_at'])
        return Response(PurchaseOrderSerializer(po).data)
