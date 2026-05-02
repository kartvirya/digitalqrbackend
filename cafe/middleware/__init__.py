# Middleware package for cafe application
from django.utils.deprecation import MiddlewareMixin

from .rate_limit import (
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    TenantSubscriptionGuardMiddleware,
)


class CsrfExemptMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if request.path.startswith('/api/'):
            setattr(request, '_dont_enforce_csrf_checks', True)
        return None


__all__ = [
    'CsrfExemptMiddleware',
    'RateLimitMiddleware',
    'SecurityHeadersMiddleware',
    'TenantSubscriptionGuardMiddleware',
]
