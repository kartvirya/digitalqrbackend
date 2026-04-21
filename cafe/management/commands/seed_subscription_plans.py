from django.core.management.base import BaseCommand

from cafe.models import SubscriptionPlan


DEFAULT_PLAN_SEED = {
    'starter': {
        'name': 'Starter',
        'billing_cycle': 'monthly',
        'price': 1999,
        'currency': 'INR',
        'max_staff': 15,
        'max_monthly_orders': 500,
        'max_tables': 30,
        'modules': {
            'qr_order': True,
            'inventory': True,
            'hr_system': False,
            'multi_branch': False,
            'permissions': {
                'can_manage_staff': False,
                'can_manage_inventory': True,
                'can_view_analytics': True,
                'can_manage_hr': False,
            },
        },
        'is_active': True,
    },
    'pro': {
        'name': 'Pro',
        'billing_cycle': 'monthly',
        'price': 4999,
        'currency': 'INR',
        'max_staff': 50,
        'max_monthly_orders': 2500,
        'max_tables': 120,
        'modules': {
            'qr_order': True,
            'inventory': True,
            'hr_system': True,
            'multi_branch': False,
            'permissions': {
                'can_manage_staff': True,
                'can_manage_inventory': True,
                'can_view_analytics': True,
                'can_manage_hr': True,
            },
        },
        'is_active': True,
    },
    'enterprise': {
        'name': 'Enterprise',
        'billing_cycle': 'monthly',
        'price': 9999,
        'currency': 'INR',
        'max_staff': 250,
        'max_monthly_orders': 25000,
        'max_tables': 1000,
        'modules': {
            'qr_order': True,
            'inventory': True,
            'hr_system': True,
            'multi_branch': True,
            'permissions': {
                'can_manage_staff': True,
                'can_manage_inventory': True,
                'can_view_analytics': True,
                'can_manage_hr': True,
                'can_manage_branches': True,
            },
        },
        'is_active': True,
    },
}


class Command(BaseCommand):
    help = 'Seed default subscription plans (starter, pro, enterprise).'

    def handle(self, *args, **options):
        for code, defaults in DEFAULT_PLAN_SEED.items():
            plan, created = SubscriptionPlan.objects.update_or_create(code=code, defaults=defaults)
            action = 'Created' if created else 'Updated'
            self.stdout.write(self.style.SUCCESS(f'{action} plan: {plan.code} ({plan.name})'))

        self.stdout.write(self.style.SUCCESS('Subscription plan seeding completed.'))
