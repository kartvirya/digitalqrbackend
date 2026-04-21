"""Create waiter / kitchen_chef groups and attach model permissions. Safe to re-run."""
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from cafe.models import Staff
from cafe.staff_groups import GROUP_KITCHEN_CHEF, GROUP_WAITER, sync_staff_operational_groups


class Command(BaseCommand):
    help = 'Create operational groups and assign permissions; backfill staff users.'

    def handle(self, *args, **options):
        waiter, _ = Group.objects.get_or_create(name=GROUP_WAITER)
        chef, _ = Group.objects.get_or_create(name=GROUP_KITCHEN_CHEF)

        order_ct = ContentType.objects.get(app_label='cafe', model='order')
        bill_ct = ContentType.objects.get(app_label='cafe', model='bill')
        ing_ct = ContentType.objects.get(app_label='cafe', model='ingredient')
        po_ct = ContentType.objects.get(app_label='cafe', model='purchaseorder')

        def add_codes(group, pairs):
            group.permissions.clear()
            for ct, code in pairs:
                p = Permission.objects.get(content_type=ct, codename=code)
                group.permissions.add(p)

        add_codes(
            waiter,
            [
                (order_ct, 'can_place_waiter_order'),
                (order_ct, 'can_view_kitchen_queue'),
                (order_ct, 'can_update_order_status_runner'),
                (order_ct, 'can_assign_runner'),
                (bill_ct, 'can_mark_paid'),
                (bill_ct, 'can_create_bill'),
                (ing_ct, 'can_manage_inventory'),
                (ing_ct, 'can_view_inventory'),
                (po_ct, 'can_manage_purchase_order'),
                (po_ct, 'can_receive_purchase_order'),
            ],
        )
        add_codes(
            chef,
            [
                (order_ct, 'can_view_kitchen_queue'),
                (order_ct, 'can_update_order_status_kitchen'),
                (order_ct, 'can_update_order_status_runner'),
                (order_ct, 'can_assign_runner'),
                (bill_ct, 'can_mark_paid'),
                (bill_ct, 'can_create_bill'),
                (ing_ct, 'can_view_inventory'),
            ],
        )

        self.stdout.write(self.style.SUCCESS('Configured waiter and kitchen_chef groups.'))

        n = 0
        for staff in Staff.objects.select_related('role', 'user').iterator():
            sync_staff_operational_groups(staff)
            n += 1
        self.stdout.write(self.style.SUCCESS(f'Synced operational groups for {n} staff users.'))
