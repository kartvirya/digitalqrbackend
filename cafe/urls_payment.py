"""
URL patterns for payment gateway integrations
"""

from django.urls import path
from django.http import JsonResponse
from django.views import View
from . import views

app_name = 'payment'


def _not_available(request, *args, **kwargs):
    return JsonResponse(
        {
            'success': False,
            'error': 'Payment endpoint is not configured in cafe.views',
        },
        status=501,
    )


class _PaymentNotAvailableView(View):
    def post(self, request, *args, **kwargs):
        return _not_available(request, *args, **kwargs)


PaymentInitiationView = getattr(views, 'PaymentInitiationView', _PaymentNotAvailableView)
PaymentVerificationView = getattr(views, 'PaymentVerificationView', _PaymentNotAvailableView)
payment_gateways_view = getattr(views, 'payment_gateways_view', _not_available)
invoice_payment_status_view = getattr(views, 'invoice_payment_status_view', _not_available)
retry_payment_view = getattr(views, 'retry_payment_view', _not_available)
esewa_success_view = getattr(views, 'esewa_success_view', _not_available)
esewa_failure_view = getattr(views, 'esewa_failure_view', _not_available)

urlpatterns = [
    # Payment initiation and verification
    path('initiate/', PaymentInitiationView.as_view(), name='initiate'),
    path('verify/<str:gateway>/', PaymentVerificationView.as_view(), name='verify'),
    
    # Payment status and management
    path('gateways/', payment_gateways_view, name='gateways'),
    path('invoice/<int:invoice_id>/status/', invoice_payment_status_view, name='invoice_status'),
    path('invoice/<int:invoice_id>/retry/', retry_payment_view, name='retry_payment'),
    
    # Payment callback URLs
    path('esewa/success/', esewa_success_view, name='esewa_success'),
    path('esewa/failure/', esewa_failure_view, name='esewa_failure'),
]
