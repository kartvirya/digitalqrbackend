from django.db import migrations


def seed_default_plans(apps, schema_editor):
    SubscriptionPlan = apps.get_model('cafe', 'SubscriptionPlan')

    plan_defaults = {
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

    for code, defaults in plan_defaults.items():
        SubscriptionPlan.objects.update_or_create(code=code, defaults=defaults)


class Migration(migrations.Migration):
    dependencies = [
        ('cafe', '0027_subscriptionplan_max_tables'),
    ]

    operations = [
        migrations.RunPython(seed_default_plans, migrations.RunPython.noop),
    ]
