from django.middleware.csrf import CsrfViewMiddleware
from django.utils.deprecation import MiddlewareMixin
from django.http import JsonResponse
from django.utils import timezone
from .models import Restaurant, Table, Room, order, Staff, PlatformAuditLog

class CsrfExemptMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if request.path.startswith('/api/'):
            setattr(request, '_dont_enforce_csrf_checks', True)
        return None


class RestaurantContextMiddleware(MiddlewareMixin):
    """
    Middleware to extract restaurant context from request and set request.restaurant.
    Restaurant can be identified via:
    1. URL parameter: ?restaurant_id=X or ?restaurant_slug=slug
    2. Header: X-Restaurant-Id or X-Restaurant-Slug
    3. Session (for authenticated users)
    4. User's restaurant (for restaurant admins)
    """
    
    def process_request(self, request):
        restaurant = None
        
        # Super admin can access any restaurant via query parameter
        if request.user.is_authenticated and (request.user.is_super_admin or request.user.is_superuser):
            # Check query parameters first
            restaurant_id = request.GET.get('restaurant_id')
            restaurant_slug = request.GET.get('restaurant_slug')
            
            if restaurant_id:
                try:
                    restaurant = Restaurant.objects.get(id=restaurant_id, is_active=True)
                except Restaurant.DoesNotExist:
                    pass
            elif restaurant_slug:
                try:
                    restaurant = Restaurant.objects.get(slug=restaurant_slug, is_active=True)
                except Restaurant.DoesNotExist:
                    pass
        
        # For non-super-admin users, check their assigned restaurant
        if not restaurant and request.user.is_authenticated:
            if request.user.restaurant:
                restaurant = request.user.restaurant
            elif request.user.cafe_manager:
                # Legacy support: cafe_manager should have a restaurant
                # This will be migrated in data migration
                pass
        
        # Check headers (for API clients)
        if not restaurant:
            restaurant_id = request.headers.get('X-Restaurant-Id')
            restaurant_slug = request.headers.get('X-Restaurant-Slug')
            
            if restaurant_id:
                try:
                    restaurant = Restaurant.objects.get(id=restaurant_id, is_active=True)
                except Restaurant.DoesNotExist:
                    pass
            elif restaurant_slug:
                try:
                    restaurant = Restaurant.objects.get(slug=restaurant_slug, is_active=True)
                except Restaurant.DoesNotExist:
                    pass
        
        # Check session (for frontend)
        if not restaurant:
            restaurant_id = request.session.get('restaurant_id')
            if restaurant_id:
                try:
                    restaurant = Restaurant.objects.get(id=restaurant_id, is_active=True)
                except Restaurant.DoesNotExist:
                    pass

        # Fallback for legacy QR links:
        # derive restaurant from table/room unique ids when slug is missing or stale.
        if not restaurant:
            table_unique_id = (
                request.GET.get('table_unique_id')
                or request.GET.get('table')
                or request.headers.get('X-Table-Unique-Id')
            )
            room_unique_id = (
                request.GET.get('room_unique_id')
                or request.GET.get('room')
                or request.headers.get('X-Room-Unique-Id')
            )

            if table_unique_id:
                table = (
                    Table.objects.select_related('restaurant')
                    .filter(qr_unique_id=table_unique_id, restaurant__is_active=True)
                    .first()
                )
                if table:
                    restaurant = table.restaurant
            elif room_unique_id:
                room = (
                    Room.objects.select_related('restaurant')
                    .filter(qr_unique_id=room_unique_id, restaurant__is_active=True)
                    .first()
                )
                if room:
                    restaurant = room.restaurant
        
        # Set restaurant on request
        request.restaurant = restaurant
        
        return None


class TenantSubscriptionGuardMiddleware(MiddlewareMixin):
    """
    Enforce tenant subscription status for write API requests.
    """

    EXEMPT_PATH_PREFIXES = (
        '/api/auth/',
        '/api/restaurants/public_landing',
        '/api/restaurants/landing_config',
        '/admin/',
    )
    EXEMPT_PATH_SUFFIXES = (
        '/pay_now/',
        '/verify_payment/',
    )
    MODULE_PATH_RULES = {
        'qr_order': (
            '/api/orders/',
            '/api/tables/',
            '/api/floors/',
            '/api/rooms/',
        ),
        'inventory': (
            '/api/inventory/',
        ),
        'hr_system': (
            '/api/hr-',
            '/api/employees/',
            '/api/leave-requests/',
            '/api/payrolls/',
            '/api/performance-reviews/',
            '/api/trainings/',
            '/api/training-enrollments/',
        ),
        'staff_management': (
            '/api/staff/',
            '/api/departments/',
            '/api/roles/',
            '/api/attendance/',
            '/api/leaves/',
        ),
    }
    PERMISSION_PATH_RULES = {
        'can_manage_staff': ('/api/staff/', '/api/departments/', '/api/roles/'),
        'can_manage_hr': (
            '/api/hr-',
            '/api/employees/',
            '/api/leave-requests/',
            '/api/payrolls/',
            '/api/performance-reviews/',
            '/api/trainings/',
            '/api/training-enrollments/',
        ),
    }

    def _resolve_module_key(self, path: str):
        for module_key, prefixes in self.MODULE_PATH_RULES.items():
            if any(path.startswith(prefix) for prefix in prefixes):
                return module_key
        return None

    def _resolve_permission_key(self, path: str):
        for permission_key, prefixes in self.PERMISSION_PATH_RULES.items():
            if any(path.startswith(prefix) for prefix in prefixes):
                return permission_key
        return None

    def process_request(self, request):
        if not request.path.startswith('/api/'):
            return None
        if any(request.path.startswith(prefix) for prefix in self.EXEMPT_PATH_PREFIXES):
            return None
        if any(request.path.endswith(suffix) for suffix in self.EXEMPT_PATH_SUFFIXES):
            return None
        if request.method == 'OPTIONS':
            return None
        if not request.user.is_authenticated:
            return None
        if request.user.is_super_admin or request.user.is_superuser:
            return None

        restaurant = getattr(request, 'restaurant', None)
        if not restaurant:
            return JsonResponse(
                {'code': 'tenant_context_required', 'detail': 'Restaurant context is required.'},
                status=400,
            )
        if not restaurant.tenant_is_active:
            return JsonResponse(
                {
                    'code': 'subscription_inactive',
                    'detail': 'Your tenant subscription is not active. Contact support.',
                    'subscription_status': restaurant.subscription_status,
                },
                status=402,
            )
        active_sub = restaurant.active_subscription
        plan = active_sub.plan if active_sub else None
        if plan:
            module_key = self._resolve_module_key(request.path)
            modules = plan.modules or {}
            if module_key and modules.get(module_key) is False:
                PlatformAuditLog.objects.create(
                    actor=request.user if request.user.is_authenticated else None,
                    restaurant=restaurant,
                    action='module_blocked',
                    target_type='module',
                    target_id=module_key,
                    metadata={'path': request.path, 'method': request.method, 'plan': plan.code},
                )
                return JsonResponse(
                    {
                        'code': 'feature_not_enabled',
                        'detail': f'The {module_key} module is not enabled in your current plan.',
                        'module': module_key,
                        'plan': plan.code,
                    },
                    status=403,
                )
            permission_key = self._resolve_permission_key(request.path)
            permission_map = modules.get('permissions', {}) if isinstance(modules, dict) else {}
            if permission_key and isinstance(permission_map, dict) and permission_map.get(permission_key) is False:
                return JsonResponse(
                    {
                        'code': 'permission_not_enabled',
                        'detail': f'The {permission_key} permission is not enabled in your current plan.',
                        'permission': permission_key,
                        'plan': plan.code,
                    },
                    status=403,
                )
        if plan and request.method == 'POST' and request.path.startswith('/api/orders/'):
            month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            order_count = order.objects.filter(restaurant=restaurant, created_at__gte=month_start).count()
            if order_count >= plan.max_monthly_orders:
                return JsonResponse(
                    {
                        'code': 'plan_limit_exceeded',
                        'detail': 'Monthly order limit reached for current plan.',
                        'limit_type': 'max_monthly_orders',
                        'limit': plan.max_monthly_orders,
                    },
                    status=429,
                )
        if plan and request.method == 'POST' and request.path.startswith('/api/staff/'):
            active_staff = Staff.objects.filter(restaurant=restaurant, is_active=True).count()
            if active_staff >= plan.max_staff:
                return JsonResponse(
                    {
                        'code': 'plan_limit_exceeded',
                        'detail': 'Staff limit reached for current plan.',
                        'limit_type': 'max_staff',
                        'limit': plan.max_staff,
                    },
                    status=429,
                )
        if plan and request.method == 'POST' and request.path.startswith('/api/tables/'):
            active_tables = Table.objects.filter(restaurant=restaurant, is_active=True).count()
            if active_tables >= getattr(plan, 'max_tables', 50):
                return JsonResponse(
                    {
                        'code': 'plan_limit_exceeded',
                        'detail': 'Table limit reached for current plan.',
                        'limit_type': 'max_tables',
                        'limit': getattr(plan, 'max_tables', 50),
                    },
                    status=429,
                )
        return None
