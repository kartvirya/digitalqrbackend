import time
import json
from collections import defaultdict, deque
from django.http import HttpResponse, JsonResponse
from django.core.cache import cache
from django.conf import settings
from django.utils.deprecation import MiddlewareMixin
from django.utils import timezone
from django.core.exceptions import ValidationError
import logging

logger = logging.getLogger(__name__)

class RateLimitMiddleware(MiddlewareMixin):
    """
    Rate limiting middleware to prevent API abuse
    """
    
    def __init__(self, get_response):
        super().__init__(get_response)
        self.rate_limits = {
            'default': {'requests': 100, 'window': 60},  # 100 requests per minute
            'auth': {'requests': 5, 'window': 300},      # 5 requests per 5 minutes
            'api': {'requests': 1000, 'window': 3600},  # 1000 requests per hour
            'login': {'requests': 3, 'window': 900},     # 3 login attempts per 15 minutes
            'signup': {'requests': 2, 'window': 3600},    # 2 signup attempts per hour
        }
    
    def get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def get_rate_limit_key(self, request, limit_type):
        """Generate rate limit key for cache"""
        ip = self.get_client_ip(request)
        user_id = getattr(request.user, 'id', 'anonymous')
        path = request.path
        
        # Different limits for different endpoints
        if '/login' in path or '/api/login' in path:
            return f"rate_limit:login:{ip}:{user_id}"
        elif '/signup' in path or '/api/signup' in path:
            return f"rate_limit:signup:{ip}:{user_id}"
        elif '/api/' in path:
            return f"rate_limit:api:{ip}:{user_id}"
        elif '/auth/' in path:
            return f"rate_limit:auth:{ip}:{user_id}"
        else:
            return f"rate_limit:default:{ip}:{user_id}"
    
    def get_limit_config(self, request):
        """Get rate limit configuration for the request"""
        path = request.path
        
        if '/login' in path or '/api/login' in path:
            return self.rate_limits['login']
        elif '/signup' in path or '/api/signup' in path:
            return self.rate_limits['signup']
        elif '/api/' in path:
            return self.rate_limits['api']
        elif '/auth/' in path:
            return self.rate_limits['auth']
        else:
            return self.rate_limits['default']
    
    def is_rate_limited(self, request):
        """Check if request is rate limited"""
        limit_config = self.get_limit_config(request)
        key = self.get_rate_limit_key(request, 'default')
        
        # Get current request count
        request_data = cache.get(key, {'count': 0, 'window_start': time.time()})
        
        current_time = time.time()
        
        # Reset window if expired
        if current_time - request_data['window_start'] > limit_config['window']:
            request_data = {'count': 0, 'window_start': current_time}
        
        # Check if rate limit exceeded
        if request_data['count'] >= limit_config['requests']:
            return True, request_data
        
        # Increment count
        request_data['count'] += 1
        cache.set(key, request_data, limit_config['window'] + 60)
        
        return False, request_data
    
    def process_request(self, request):
        """Process rate limiting"""
        # Skip rate limiting for admin users in development
        # Use try-catch to handle invalid session data
        try:
            if settings.DEBUG and getattr(request.user, 'is_superuser', False):
                return None
        except (AttributeError, ValueError, ValidationError):
            # If user data is invalid, continue with rate limiting
            pass
        
        # Check rate limit
        is_limited, request_data = self.is_rate_limited(request)
        
        if is_limited:
            logger.warning(
                f"Rate limit exceeded for IP: {self.get_client_ip(request)}, "
                f"Path: {request.path}, User: {getattr(request.user, 'id', 'anonymous')}"
            )
            
            return HttpResponse(
                json.dumps({
                    'error': 'Rate limit exceeded',
                    'message': 'Too many requests. Please try again later.',
                    'retry_after': int(request_data['window_start'] + self.get_limit_config(request)['window'] - time.time())
                }),
                status=429,
                content_type='application/json'
            )
        
        return None

class SecurityHeadersMiddleware(MiddlewareMixin):
    """
    Add security headers to responses
    """
    
    def process_response(self, request, response):
        # Add security headers
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = (
            'geolocation=(), microphone=(), camera=(), '
            'payment=(), usb=(), magnetometer=(), gyroscope=()'
        )
        
        # Content Security Policy for production
        if not settings.DEBUG:
            csp = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "img-src 'self' data: https:; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'self';"
            )
            response['Content-Security-Policy'] = csp
        
        return response


class TenantSubscriptionGuardMiddleware(MiddlewareMixin):
    """
    Middleware to guard access based on tenant subscription status
    """
    
    def process_request(self, request):
        """
        Check tenant subscription status before allowing access to protected views
        """
        # Skip subscription check for certain paths
        exempt_paths = [
            '/admin/',
            '/api/auth/google/',
            '/api/auth/google/callback/',
            '/api/auth/trial-status/',
            '/signup/',
            '/login/',
            '/static/',
            '/media/',
            '/health/',
            '/favicon.ico',
        ]
        
        if any(request.path.startswith(path) for path in exempt_paths):
            return None
        
        # Skip for anonymous users (they'll be handled by individual views)
        try:
            if not hasattr(request, 'user') or not request.user.is_authenticated:
                return None
            
            # Skip for super admin
            if request.user.is_superuser or getattr(request.user, 'is_super_admin', False):
                return None
        except (AttributeError, ValueError, ValidationError):
            # If user data is invalid, allow access (will be handled by individual views)
            return None
        
        # Get user's restaurant/tenant
        restaurant = getattr(request.user, 'restaurant', None)
        if not restaurant:
            return None
        
        # Check subscription status
        try:
            subscription = restaurant.subscriptions.filter(status='active').first()
            if not subscription:
                # No active subscription - check if they have a trial
                trial_subscriptions = restaurant.subscriptions.filter(
                    status='trial',
                    trial_end_date__gt=timezone.now()
                ).first()
                
                if not trial_subscriptions:
                    # No active subscription or trial
                    if request.path.startswith('/api/'):
                        return JsonResponse({
                            'error': 'Subscription required',
                            'message': 'Your subscription has expired. Please upgrade to continue.',
                            'code': 'SUBSCRIPTION_EXPIRED'
                        }, status=402)
                    else:
                        # Redirect to billing page for web requests
                        from django.shortcuts import redirect
                        return redirect('/billing/')
        
        except Exception as e:
            logger.error(f"Error checking subscription: {e}")
            # Allow access if there's an error checking subscription
            pass
        
        return None
