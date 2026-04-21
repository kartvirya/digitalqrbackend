"""Operational staff Django Groups synced from Staff.role.name."""
from __future__ import annotations

from django.contrib.auth.models import Group

GROUP_WAITER = "waiter"
GROUP_KITCHEN_CHEF = "kitchen_chef"

OPERATIONAL_GROUP_NAMES = (GROUP_WAITER, GROUP_KITCHEN_CHEF)


def role_name_to_operational_group(role_name: str | None) -> str | None:
    """Map HR Role title to a single operational group, or None if unknown."""
    if not role_name:
        return None
    n = role_name.lower().strip()
    if any(x in n for x in ("waiter", "server", "captain", "host")):
        return GROUP_WAITER
    if any(x in n for x in ("chef", "cook", "kitchen", "kds", "prep")):
        return GROUP_KITCHEN_CHEF
    return None


def resolve_operational_group_for_staff(staff) -> str | None:
    """Pick waiter / kitchen_chef / None from Staff.operational_access and role."""
    mode = getattr(staff, "operational_access", None) or "auto"
    if mode == "waiter":
        return GROUP_WAITER
    if mode == "kitchen_chef":
        return GROUP_KITCHEN_CHEF
    if mode == "none":
        return None
    role_name = staff.role.name if getattr(staff, "role_id", None) else None
    return role_name_to_operational_group(role_name)


def sync_staff_operational_groups(staff) -> None:
    """Assign linked user to at most one of waiter / kitchen_chef from Staff settings."""
    from django.contrib.auth.models import Group

    user = staff.user
    target = resolve_operational_group_for_staff(staff)
    op_groups = list(Group.objects.filter(name__in=OPERATIONAL_GROUP_NAMES))
    for g in op_groups:
        user.groups.remove(g)
    if target:
        g, _ = Group.objects.get_or_create(name=target)
        user.groups.add(g)


def sync_staff_user_groups(user, role_name: str | None) -> None:
    """Backward-compatible: sync from role name only (ignores Staff.operational_access)."""
    from django.contrib.auth.models import Group

    target = role_name_to_operational_group(role_name)
    op_groups = list(Group.objects.filter(name__in=OPERATIONAL_GROUP_NAMES))
    for g in op_groups:
        user.groups.remove(g)
    if target:
        g, _ = Group.objects.get_or_create(name=target)
        user.groups.add(g)
