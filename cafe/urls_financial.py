"""
URL patterns for financial reports
"""

from django.urls import path
from django.http import JsonResponse
from . import views

app_name = 'financial'


def _not_available(request, *args, **kwargs):
    return JsonResponse(
        {
            'success': False,
            'error': 'Financial report endpoint is not configured in cafe.views',
        },
        status=501,
    )


profit_loss_statement_view = getattr(views, 'profit_loss_statement_view', _not_available)
balance_sheet_view = getattr(views, 'balance_sheet_view', _not_available)
vat_summary_view = getattr(views, 'vat_summary_view', _not_available)
tds_summary_view = getattr(views, 'tds_summary_view', _not_available)
financial_dashboard_view = getattr(views, 'financial_dashboard_view', _not_available)
export_financial_report_view = getattr(views, 'export_financial_report_view', _not_available)
fiscal_year_info_view = getattr(views, 'fiscal_year_info_view', _not_available)

urlpatterns = [
    # Financial reports
    path('profit-loss/', profit_loss_statement_view, name='profit_loss'),
    path('balance-sheet/', balance_sheet_view, name='balance_sheet'),
    path('vat-summary/', vat_summary_view, name='vat_summary'),
    path('tds-summary/', tds_summary_view, name='tds_summary'),
    path('dashboard/', financial_dashboard_view, name='dashboard'),
    
    # Export functionality
    path('export/<str:report_type>/', export_financial_report_view, name='export_report'),
    
    # Fiscal year information
    path('fiscal-year/', fiscal_year_info_view, name='fiscal_year'),
]
