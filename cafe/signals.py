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
