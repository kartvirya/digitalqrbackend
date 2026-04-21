"""
Custom permission classes for role-based access control
"""
from rest_framework import permissions


def is_restaurant_power_user(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    return bool(
        user.is_superuser
        or getattr(user, 'is_super_admin', False)
        or getattr(user, 'cafe_manager', False)
        or (hasattr(user, 'is_restaurant_admin') and user.is_restaurant_admin())
    )


def order_request_has_qr_context(request) -> bool:
    """Table or room unique id from body, query, or headers (anonymous QR flows)."""
    data = getattr(request, 'data', {}) or {}
    qp = request.query_params
    meta = request.META
    tid = (
        data.get('table_unique_id')
        or qp.get('table_unique_id')
        or qp.get('table')
        or meta.get('HTTP_X_TABLE_UNIQUE_ID')
    )
    rid = (
        data.get('room_unique_id')
        or qp.get('room_unique_id')
        or qp.get('room')
        or meta.get('HTTP_X_ROOM_UNIQUE_ID')
    )
    return bool(tid or rid)


class OrderCreatePermission(permissions.BasePermission):
    """Anonymous or logged-in customer: QR context required. Waiter/admin: broader create."""

    def has_permission(self, request, view):
        if getattr(view, 'action', None) != 'create':
            return True
        if request.user and request.user.is_authenticated:
            if is_restaurant_power_user(request.user):
                return True
            if request.user.has_perm('cafe.can_place_waiter_order'):
                return True
            # Logged-in guest/customer: same rules as anonymous (table/room context)
            return order_request_has_qr_context(request)
        return order_request_has_qr_context(request)


class OrderListRetrievePermission(permissions.BasePermission):
    def has_permission(self, request, view):
        act = getattr(view, 'action', None)
        if act not in ('list', 'retrieve'):
            return True
        if request.user and request.user.is_authenticated:
            return True
        if act == 'retrieve':
            return order_request_has_qr_context(request)
        return True


class OrderUpdateStatusPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if getattr(view, 'action', None) != 'update_status':
            return True
        if not request.user or not request.user.is_authenticated:
            return False
        if is_restaurant_power_user(request.user):
            return True
        return (
            request.user.has_perm('cafe.can_update_order_status_kitchen')
            or request.user.has_perm('cafe.can_update_order_status_runner')
        )


class OrderMarkPaidPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if getattr(view, 'action', None) != 'mark_paid':
            return True
        if not request.user or not request.user.is_authenticated:
            return False
        if is_restaurant_power_user(request.user):
            return True
        return request.user.has_perm('cafe.can_mark_paid')


class OrderAssignRunnerPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if getattr(view, 'action', None) != 'assign_runner':
            return True
        if not request.user or not request.user.is_authenticated:
            return False
        if is_restaurant_power_user(request.user):
            return True
        return request.user.has_perm('cafe.can_assign_runner')


class OrderClearTablePermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if getattr(view, 'action', None) != 'clear_table':
            return True
        if not request.user or not request.user.is_authenticated:
            return False
        if is_restaurant_power_user(request.user):
            return True
        return request.user.has_perm('cafe.can_mark_paid')


def order_transition_allowed(user, old_status: str, new_status: str) -> bool:
    if is_restaurant_power_user(user):
        return True
    if new_status == 'cancelled':
        return user.has_perm('cafe.can_update_order_status_kitchen') or user.has_perm(
            'cafe.can_update_order_status_runner'
        )
    edge = (old_status, new_status)
    kitchen_edges = {
        ('pending', 'preparing'),
        ('confirmed', 'preparing'),
        ('preparing', 'ready'),
    }
    runner_edges = {
        ('pending', 'confirmed'),
        ('ready', 'served'),
        ('served', 'delivered'),
        ('delivered', 'completed'),
    }
    if user.has_perm('cafe.can_update_order_status_kitchen') and edge in (kitchen_edges | runner_edges):
        return True
    if user.has_perm('cafe.can_update_order_status_runner') and edge in runner_edges:
        return True
    return False


class InventoryManagePermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if is_restaurant_power_user(request.user):
            return True
        if request.method in permissions.SAFE_METHODS:
            return request.user.has_perm('cafe.can_view_inventory')
        return request.user.has_perm('cafe.can_manage_inventory')


class PurchaseOrderPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if is_restaurant_power_user(request.user):
            return True
        if getattr(view, 'action', None) == 'receive_lines':
            return request.user.has_perm('cafe.can_receive_purchase_order') or request.user.has_perm(
                'cafe.can_manage_purchase_order'
            )
        if request.method in permissions.SAFE_METHODS:
            return request.user.has_perm('cafe.can_manage_purchase_order') or request.user.has_perm(
                'cafe.can_receive_purchase_order'
            )
        return request.user.has_perm('cafe.can_manage_purchase_order')


class IsSuperAdmin(permissions.BasePermission):
    """Only allows super admins"""
    
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            (request.user.is_super_admin or request.user.role == 'super_admin')
        )


class IsRestaurantAdmin(permissions.BasePermission):
    """Allows restaurant admins and super admins"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Super admin / Django superuser has access
        if request.user.is_superuser or request.user.is_super_admin or request.user.role == 'super_admin':
            return True
        
        # Restaurant admin has access
        return request.user.is_restaurant_admin()


class IsHRManager(permissions.BasePermission):
    """Allows HR managers, restaurant admins, and super admins"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Super admin has access
        if request.user.is_super_admin or request.user.role == 'super_admin':
            return True
        
        # Restaurant admin has access
        if request.user.is_restaurant_admin():
            return True
        
        # HR Manager has access
        return request.user.is_hr_manager()


class IsStaff(permissions.BasePermission):
    """Allows staff members, HR managers, restaurant admins, and super admins"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Super admin has access
        if request.user.is_super_admin or request.user.role == 'super_admin':
            return True
        
        # Restaurant admin has access
        if request.user.is_restaurant_admin():
            return True
        
        # HR Manager has access
        if request.user.is_hr_manager():
            return True
        
        # Staff has access
        return request.user.is_staff_member()


class HasPermission(permissions.BasePermission):
    """Check if user has a specific permission"""
    
    def __init__(self, permission_name):
        self.permission_name = permission_name
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        return request.user.has_permission(self.permission_name)


class IsRestaurantScoped(permissions.BasePermission):
    """Ensures user can only access their restaurant's data"""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Super admin can access all restaurants
        if request.user.is_super_admin or request.user.role == 'super_admin':
            return True
        
        # Other users must have a restaurant
        return request.user.restaurant is not None
    
    def has_object_permission(self, request, view, obj):
        # Super admin can access all objects
        if request.user.is_super_admin or request.user.role == 'super_admin':
            return True
        
        # Check if object belongs to user's restaurant
        if hasattr(obj, 'restaurant'):
            return obj.restaurant == request.user.restaurant
        
        return False

