from django.middleware.csrf import CsrfViewMiddleware
from django.utils.deprecation import MiddlewareMixin
from .models import Restaurant

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
        
        # Set restaurant on request
        request.restaurant = restaurant
        
        return None
