"""Seed GitHub-style roles and permission matrix for tenant RBAC."""

from django.core.management.base import BaseCommand
from django.db import transaction

from cafe.models import Permission, RolePermission, User


PERMISSIONS = [
    # Restaurant / settings
    ("Manage Restaurants", "manage_restaurants", "restaurant", "Create/update/archive restaurants"),
    ("Manage Settings", "manage_settings", "settings", "Manage tenant settings and configuration"),
    ("View Reports", "view_reports", "reports", "View analytics and reports"),
    # Menu / operations
    ("Manage Menu", "manage_menu", "menu", "Create and update menu items"),
    ("Manage Tables", "manage_tables", "tables", "Create and update tables"),
    ("Manage Rooms", "manage_rooms", "tables", "Create and update rooms"),
    ("Manage Floors", "manage_floors", "tables", "Create and update floors"),
    ("View Tables", "view_tables", "tables", "View tables and room layout"),
    ("Manage Orders", "manage_orders", "orders", "Create and update orders"),
    ("View Orders", "view_orders", "orders", "View order lists"),
    ("View Kitchen", "view_kitchen", "orders", "View kitchen queue"),
    ("Manage Inventory", "manage_inventory", "inventory", "Manage stock and ingredients"),
    # HR
    ("Manage Staff", "manage_staff", "employees", "Manage staff assignment"),
    ("Manage Employees", "manage_employees", "employees", "Manage employee records"),
    ("View Employees", "view_employees", "employees", "View employee records"),
    ("Manage Payroll", "manage_payroll", "payroll", "Manage payroll"),
    ("View Payroll", "view_payroll", "payroll", "View payroll"),
    ("Manage Attendance", "manage_attendance", "attendance", "Manage attendance records"),
    ("View Attendance", "view_attendance", "attendance", "View attendance records"),
    ("Manage Leaves", "manage_leaves", "leaves", "Approve and manage leave requests"),
    ("View Leaves", "view_leaves", "leaves", "View leave requests"),
    ("Manage Training", "manage_training", "training", "Manage training programs"),
    ("View Training", "view_training", "training", "View training records"),
    ("Manage Performance", "manage_performance", "performance", "Manage performance reviews"),
    ("View Performance", "view_performance", "performance", "View performance records"),
    # Billing / security
    ("Manage Billing", "manage_billing", "billing", "Manage billing config and invoices"),
    ("Manage Subscriptions", "manage_subscriptions", "billing", "Manage subscription plans and assignments"),
    ("Manage Roles", "manage_roles", "security", "Manage role-permission matrix"),
    ("Assign Roles", "assign_roles", "security", "Assign roles to users"),
    ("View Audit Logs", "view_audit_logs", "security", "View platform and tenant audit logs"),
]


ROLE_MATRIX = {
    "owner": "*",
    "admin": {
        "manage_settings", "view_reports", "manage_menu", "manage_tables", "manage_rooms", "manage_floors",
        "view_tables", "manage_orders", "view_orders", "view_kitchen", "manage_inventory", "manage_staff",
        "manage_employees", "view_employees", "manage_payroll", "view_payroll", "manage_attendance",
        "view_attendance", "manage_leaves", "view_leaves", "manage_training", "view_training",
        "manage_performance", "view_performance", "manage_billing", "manage_subscriptions",
    },
    "maintain": {
        "view_reports", "manage_menu", "manage_tables", "manage_rooms", "manage_floors", "view_tables",
        "manage_orders", "view_orders", "view_kitchen", "manage_inventory", "manage_staff", "manage_employees",
        "view_employees", "manage_payroll", "view_payroll", "manage_attendance", "view_attendance",
        "manage_leaves", "view_leaves", "manage_training", "view_training", "manage_performance",
        "view_performance",
    },
    "write": {
        "manage_orders", "view_orders", "view_tables", "view_kitchen", "view_reports",
    },
    "triage": {
        "view_orders", "view_tables", "view_kitchen", "view_reports", "view_employees", "view_attendance",
        "view_leaves", "view_training", "view_performance", "view_payroll",
    },
    "read": {
        "view_orders", "view_tables", "view_reports",
    },
}


LEGACY_ROLE_ALIAS = {
    "super_admin": "owner",
    "restaurant_admin": "admin",
    "hr_manager": "maintain",
    "staff": "write",
    "customer": "read",
}


class Command(BaseCommand):
    help = "Seed GitHub-style RBAC permissions and role matrix."

    @transaction.atomic
    def handle(self, *args, **kwargs):
        created_perms = 0
        updated_perms = 0

        permission_map = {}
        for name, codename, category, description in PERMISSIONS:
            obj, created = Permission.objects.get_or_create(
                codename=codename,
                defaults={
                    "name": name,
                    "category": category,
                    "description": description,
                },
            )
            if created:
                created_perms += 1
            else:
                changed = False
                if obj.name != name:
                    obj.name = name
                    changed = True
                if obj.category != category:
                    obj.category = category
                    changed = True
                if obj.description != description:
                    obj.description = description
                    changed = True
                if changed:
                    obj.save(update_fields=["name", "category", "description"])
                    updated_perms += 1
            permission_map[codename] = obj

        all_codenames = set(permission_map.keys())
        role_targets = {}
        for role, perms in ROLE_MATRIX.items():
            role_targets[role] = all_codenames if perms == "*" else set(perms)

        for legacy_role, mapped in LEGACY_ROLE_ALIAS.items():
            role_targets[legacy_role] = set(role_targets[mapped])

        total_added = 0
        total_removed = 0
        valid_roles = {choice[0] for choice in User.ROLE_CHOICES}

        for role, target_codenames in role_targets.items():
            if role not in valid_roles:
                continue
            existing = set(
                RolePermission.objects.filter(role=role).values_list("permission__codename", flat=True)
            )
            to_add = target_codenames - existing
            to_remove = existing - target_codenames

            for codename in sorted(to_add):
                RolePermission.objects.get_or_create(role=role, permission=permission_map[codename])
                total_added += 1

            if to_remove:
                RolePermission.objects.filter(role=role, permission__codename__in=to_remove).delete()
                total_removed += len(to_remove)

        self.stdout.write(self.style.SUCCESS("RBAC bootstrap completed."))
        self.stdout.write(f"Permissions created: {created_perms}")
        self.stdout.write(f"Permissions updated: {updated_perms}")
        self.stdout.write(f"Role permissions added: {total_added}")
        self.stdout.write(f"Role permissions removed: {total_removed}")
