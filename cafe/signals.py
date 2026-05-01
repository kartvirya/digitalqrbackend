from datetime import timedelta

from django.db.models.signals import post_save
from django.utils import timezone
from django.dispatch import receiver

from .models import (
    Staff,
    Restaurant,
    SubscriptionPlan,
    RestaurantSubscription,
    TenantUsageSnapshot,
    Floor,
    Table,
    order,
    bill,
    MenuItemRecipe,
    IngredientStock,
    StockMovement,
    PurchaseOrder,
    Payroll,
)
from .staff_groups import sync_staff_operational_groups


@receiver(post_save, sender=Staff)
def sync_staff_groups_on_save(sender, instance, **kwargs):
    sync_staff_operational_groups(instance)


@receiver(post_save, sender=Restaurant)
def bootstrap_restaurant_subscription(sender, instance, created, **kwargs):
    """
    Initialize a newly created tenant with default plan, usage snapshot,
    and minimal floor/table scaffold so onboarding is ready immediately.
    """
    if not created:
        return

    starter_plan, _ = SubscriptionPlan.objects.get_or_create(
        code='starter',
        defaults={
            'name': 'Starter',
            'billing_cycle': 'monthly',
            'price': 0,
            'currency': 'INR',
            'max_staff': 10,
            'max_monthly_orders': 200,
            'max_tables': 20,
            'modules': {'qr_order': True, 'inventory': True, 'hr_system': False, 'multi_branch': False},
            'is_active': True,
        },
    )
    trial_ends_at = timezone.now() + timedelta(days=14)
    RestaurantSubscription.objects.create(
        restaurant=instance,
        plan=starter_plan,
        status='trialing',
        trial_ends_at=trial_ends_at,
        current_period_start=timezone.now(),
        current_period_end=trial_ends_at,
        is_active=True,
        metadata={'seeded_by': 'bootstrap_signal'},
    )
    TenantUsageSnapshot.objects.get_or_create(
        restaurant=instance,
        month_key=timezone.now().strftime('%Y-%m'),
        defaults={'orders_count': 0, 'active_staff_count': 0},
    )

    floor = Floor.objects.create(
        restaurant=instance,
        name='Main Floor',
        description='Default floor created during tenant onboarding.',
        is_active=True,
    )
    for table_number in ['T1', 'T2', 'T3', 'T4']:
        Table.objects.create(
            restaurant=instance,
            floor=floor,
            table_number=table_number,
            table_name=f'Table {table_number[-1]}',
            capacity=4,
            is_active=True,
        )


@receiver(post_save, sender=order)
def handle_inventory_for_order_status_change(sender, instance, created, **kwargs):
    """
    Handle inventory operations based on order status changes:
    - Deduct stock when order is completed/ready
    - Restore stock when order is cancelled
    This is idempotent and tracks when stock was consumed.
    """
    if not instance.restaurant:
        return  # Skip orders without restaurant (legacy data)
    
    try:
        if instance.status in ['completed', 'ready']:
            # Deduct inventory on order completion
            # Prevent duplicate deductions
            if instance.stock_consumed_at:
                return
            
            # Parse order items JSON to get menu items and quantities
            import json
            order_items = json.loads(instance.items_json)
            
            for item in order_items:
                menu_item_id = item.get('id')
                quantity = item.get('quantity', 1)
                
                if not menu_item_id:
                    continue
                    
                # Get recipe for this menu item
                recipe_lines = MenuItemRecipe.objects.filter(
                    menu_item_id=menu_item_id
                ).select_related('ingredient')
                
                for recipe_line in recipe_lines:
                    ingredient = recipe_line.ingredient
                    # Calculate total ingredient quantity needed
                    total_quantity = recipe_line.quantity * quantity
                    
                    # Get or create stock record
                    stock, _ = IngredientStock.objects.get_or_create(
                        ingredient=ingredient,
                        defaults={'quantity_on_hand': 0}
                    )
                    
                    # Check if sufficient stock exists
                    if stock.quantity_on_hand < total_quantity:
                        # Log insufficient stock warning but continue deduction
                        print(f"Warning: Insufficient stock for {ingredient.name}. "
                              f"Available: {stock.quantity_on_hand}, Required: {total_quantity}")
                    
                    # Create stock movement record
                    StockMovement.objects.create(
                        restaurant=instance.restaurant,
                        ingredient=ingredient,
                        quantity_delta=-total_quantity,  # Negative for deduction
                        movement_type=StockMovement.MOVEMENT_CONSUMPTION,
                        order_ref=instance,
                        notes=f"Auto-deducted for order #{instance.id}",
                        created_by=instance.user
                    )
                    
                    # Update stock level
                    stock.quantity_on_hand = max(stock.quantity_on_hand - total_quantity, 0)
                    stock.save()
            
            # Mark order as having stock consumed (idempotency)
            instance.stock_consumed_at = timezone.now()
            instance.save(update_fields=['stock_consumed_at'])
            
        elif instance.status == 'cancelled':
            # Restore inventory on order cancellation
            # Only restore if stock was previously consumed
            if not instance.stock_consumed_at:
                return
            
            # Find all stock movements for this order that were consumption movements
            consumption_movements = StockMovement.objects.filter(
                order_ref=instance,
                movement_type=StockMovement.MOVEMENT_CONSUMPTION
            ).select_related('ingredient')
            
            for movement in consumption_movements:
                ingredient = movement.ingredient
                # Reverse the quantity (make it positive)
                restore_quantity = abs(movement.quantity_delta)
                
                # Get stock record
                stock, _ = IngredientStock.objects.get_or_create(
                    ingredient=ingredient,
                    defaults={'quantity_on_hand': 0}
                )
                
                # Create reversal stock movement
                StockMovement.objects.create(
                    restaurant=instance.restaurant,
                    ingredient=ingredient,
                    quantity_delta=restore_quantity,  # Positive for restoration
                    movement_type=StockMovement.MOVEMENT_REVERSAL,
                    order_ref=instance,
                    notes=f"Stock restored for cancelled order #{instance.id}",
                    created_by=instance.user
                )
                
                # Update stock level
                stock.quantity_on_hand += restore_quantity
                stock.save()
            
            # Clear the stock consumed timestamp
            instance.stock_consumed_at = None
            instance.save(update_fields=['stock_consumed_at'])
        
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"Error processing inventory for order {instance.id}: {e}")
    except Exception as e:
        print(f"Unexpected error in inventory processing for order {instance.id}: {e}")


@receiver(post_save, sender=bill)
def create_sales_journal_entry(sender, instance, created, **kwargs):
    """Create accounting journal entry when a bill is generated"""
    if not created:  # Only process on creation
        return
    
    if not instance.restaurant:
        return  # Skip bills without restaurant (legacy data)
    
    try:
        from .services.accounting import AccountingService
        accounting_service = AccountingService(instance.restaurant)
        accounting_service.create_sales_journal_entry(instance.order, instance)
    except Exception as e:
        print(f"Error creating sales journal entry for bill {instance.id}: {e}")


@receiver(post_save, sender=PurchaseOrder)
def create_purchase_journal_entry(sender, instance, **kwargs):
    """Create accounting journal entry when purchase order is received"""
    # Only process when status changes to 'received' or 'partially_received'
    if instance.status not in ['received', 'partially_received']:
        return
    
    if not instance.restaurant:
        return  # Skip POs without restaurant (legacy data)
    
    try:
        from .services.accounting import AccountingService
        accounting_service = AccountingService(instance.restaurant)
        accounting_service.create_purchase_journal_entry(instance)
    except Exception as e:
        print(f"Error creating purchase journal entry for PO {instance.id}: {e}")


@receiver(post_save, sender=Payroll)
def create_payroll_journal_entry(sender, instance, **kwargs):
    """Create accounting journal entry when payroll is processed"""
    # Only process when payment status is 'paid'
    if instance.payment_status != 'paid':
        return
    
    if not instance.employee or not instance.employee.restaurant:
        return  # Skip payroll without restaurant
    
    try:
        from .services.accounting import AccountingService
        accounting_service = AccountingService(instance.employee.restaurant)
        accounting_service.create_payroll_journal_entry(instance)
    except Exception as e:
        print(f"Error creating payroll journal entry for payroll {instance.id}: {e}")
