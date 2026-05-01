"""
Financial reports API views
Provides endpoints for generating P&L, Balance Sheet, and VAT/TDS summaries
"""

import logging
from datetime import datetime, timedelta
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from ..models import Restaurant
from ..services.financial_reports import FinancialReportsService
from ..permissions import IsSuperAdminOrOwner

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSuperAdminOrOwner])
def profit_loss_statement_view(request):
    """Generate Profit & Loss statement"""
    try:
        # Get date parameters
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')
        
        # Parse dates or use defaults
        if start_date_str and end_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        else:
            # Use current fiscal year
            service = FinancialReportsService(request.user.restaurant)
            start_date, end_date = service.get_fiscal_year_dates()
            start_date = datetime.combine(start_date, datetime.min.time())
            end_date = datetime.combine(end_date, datetime.max.time())
        
        # Generate report
        service = FinancialReportsService(request.user.restaurant)
        report = service.generate_profit_loss_statement(start_date, end_date)
        
        return Response(report)
        
    except ValueError as e:
        return Response({
            'success': False,
            'error': f'Invalid date format: {str(e)}'
        }, status=400)
    except Exception as e:
        logger.error(f"Error generating P&L statement: {str(e)}")
        return Response({
            'success': False,
            'error': 'Failed to generate P&L statement'
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSuperAdminOrOwner])
def balance_sheet_view(request):
    """Generate Balance Sheet"""
    try:
        # Get date parameter
        as_of_date_str = request.GET.get('as_of_date')
        
        # Parse date or use current date
        if as_of_date_str:
            as_of_date = datetime.strptime(as_of_date_str, '%Y-%m-%d')
        else:
            as_of_date = datetime.now()
        
        # Generate report
        service = FinancialReportsService(request.user.restaurant)
        report = service.generate_balance_sheet(as_of_date)
        
        return Response(report)
        
    except ValueError as e:
        return Response({
            'success': False,
            'error': f'Invalid date format: {str(e)}'
        }, status=400)
    except Exception as e:
        logger.error(f"Error generating balance sheet: {str(e)}")
        return Response({
            'success': False,
            'error': 'Failed to generate balance sheet'
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSuperAdminOrOwner])
def vat_summary_view(request):
    """Generate VAT summary report"""
    try:
        # Get date parameters
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')
        
        # Parse dates or use defaults
        if start_date_str and end_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        else:
            # Use current fiscal year
            service = FinancialReportsService(request.user.restaurant)
            start_date, end_date = service.get_fiscal_year_dates()
            start_date = datetime.combine(start_date, datetime.min.time())
            end_date = datetime.combine(end_date, datetime.max.time())
        
        # Generate report
        service = FinancialReportsService(request.user.restaurant)
        report = service.generate_vat_summary(start_date, end_date)
        
        return Response(report)
        
    except ValueError as e:
        return Response({
            'success': False,
            'error': f'Invalid date format: {str(e)}'
        }, status=400)
    except Exception as e:
        logger.error(f"Error generating VAT summary: {str(e)}")
        return Response({
            'success': False,
            'error': 'Failed to generate VAT summary'
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSuperAdminOrOwner])
def tds_summary_view(request):
    """Generate TDS summary report"""
    try:
        # Get date parameters
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')
        
        # Parse dates or use defaults
        if start_date_str and end_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        else:
            # Use current fiscal year
            service = FinancialReportsService(request.user.restaurant)
            start_date, end_date = service.get_fiscal_year_dates()
            start_date = datetime.combine(start_date, datetime.min.time())
            end_date = datetime.combine(end_date, datetime.max.time())
        
        # Generate report
        service = FinancialReportsService(request.user.restaurant)
        report = service.generate_tds_summary(start_date, end_date)
        
        return Response(report)
        
    except ValueError as e:
        return Response({
            'success': False,
            'error': f'Invalid date format: {str(e)}'
        }, status=400)
    except Exception as e:
        logger.error(f"Error generating TDS summary: {str(e)}")
        return Response({
            'success': False,
            'error': 'Failed to generate TDS summary'
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSuperAdminOrOwner])
def financial_dashboard_view(request):
    """Generate financial dashboard with key metrics"""
    try:
        # Get date parameters
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')
        
        # Parse dates or use defaults
        if start_date_str and end_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        else:
            # Use current fiscal year
            service = FinancialReportsService(request.user.restaurant)
            start_date, end_date = service.get_fiscal_year_dates()
            start_date = datetime.combine(start_date, datetime.min.time())
            end_date = datetime.combine(end_date, datetime.max.time())
        
        # Generate all reports
        service = FinancialReportsService(request.user.restaurant)
        
        profit_loss = service.generate_profit_loss_statement(start_date, end_date)
        balance_sheet = service.generate_balance_sheet(end_date)
        vat_summary = service.generate_vat_summary(start_date, end_date)
        tds_summary = service.generate_tds_summary(start_date, end_date)
        
        # Combine key metrics
        dashboard_data = {
            'period': {
                'start_date': start_date_str,
                'end_date': end_date_str,
            },
            'key_metrics': {
                'total_revenue': profit_loss.get('total_revenue', 0),
                'net_profit': profit_loss.get('net_profit', 0),
                'profit_margin': profit_loss.get('profit_margin', 0),
                'total_assets': balance_sheet.get('total_assets', 0),
                'total_liabilities': balance_sheet.get('total_liabilities', 0),
                'total_equity': balance_sheet.get('total_equity', 0),
                'vat_collected': vat_summary.get('summary', {}).get('total_vat_collected', 0),
                'vat_payable': vat_summary.get('summary', {}).get('net_vat_payable', 0),
                'tds_deducted': tds_summary.get('summary', {}).get('total_tds_deducted', 0),
            },
            'reports': {
                'profit_loss': profit_loss,
                'balance_sheet': balance_sheet,
                'vat_summary': vat_summary,
                'tds_summary': tds_summary,
            },
            'generated_at': datetime.now().isoformat(),
        }
        
        return Response(dashboard_data)
        
    except ValueError as e:
        return Response({
            'success': False,
            'error': f'Invalid date format: {str(e)}'
        }, status=400)
    except Exception as e:
        logger.error(f"Error generating financial dashboard: {str(e)}")
        return Response({
            'success': False,
            'error': 'Failed to generate financial dashboard'
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSuperAdminOrOwner])
def export_financial_report_view(request, report_type):
    """Export financial report in various formats"""
    try:
        # Get date parameters
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')
        export_format = request.GET.get('format', 'json')
        
        # Parse dates or use defaults
        if start_date_str and end_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        else:
            # Use current fiscal year
            service = FinancialReportsService(request.user.restaurant)
            start_date, end_date = service.get_fiscal_year_dates()
            start_date = datetime.combine(start_date, datetime.min.time())
            end_date = datetime.combine(end_date, datetime.max.time())
        
        # Generate report
        service = FinancialReportsService(request.user.restaurant)
        
        if report_type == 'profit_loss':
            report = service.generate_profit_loss_statement(start_date, end_date)
        elif report_type == 'balance_sheet':
            report = service.generate_balance_sheet(end_date)
        elif report_type == 'vat_summary':
            report = service.generate_vat_summary(start_date, end_date)
        elif report_type == 'tds_summary':
            report = service.generate_tds_summary(start_date, end_date)
        else:
            return Response({
                'success': False,
                'error': f'Unknown report type: {report_type}'
            }, status=400)
        
        # Format response based on export format
        if export_format == 'csv':
            # Generate CSV response (simplified for now)
            import csv
            from django.http import HttpResponse
            
            response = HttpResponse(content_type='text/csv')
            filename = f"{report_type}_{datetime.now().strftime('%Y%m%d')}.csv"
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            
            writer = csv.writer(response)
            
            if report_type == 'profit_loss':
                writer.writerow(['Account', 'Amount'])
                for item in report.get('revenue', []):
                    writer.writerow([item['account']['name'], item['total']])
                for item in report.get('cost_of_goods_sold', []):
                    writer.writerow([item['account']['name'], item['total']])
                for item in report.get('operating_expenses', []):
                    writer.writerow([item['account']['name'], item['total']])
                writer.writerow(['Gross Profit', report.get('gross_profit', 0)])
                writer.writerow(['Net Profit', report.get('net_profit', 0)])
            
            return response
            
        elif export_format == 'excel':
            # For now, return JSON with note about Excel export
            return Response({
                'success': True,
                'data': report,
                'note': 'Excel export requires additional libraries. Please use CSV format for now.'
            })
            
        else:
            # Default JSON format
            return Response(report)
        
    except ValueError as e:
        return Response({
            'success': False,
            'error': f'Invalid date format: {str(e)}'
        }, status=400)
    except Exception as e:
        logger.error(f"Error exporting financial report: {str(e)}")
        return Response({
            'success': False,
            'error': 'Failed to export financial report'
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSuperAdminOrOwner])
def fiscal_year_info_view(request):
    """Get fiscal year information"""
    try:
        service = FinancialReportsService(request.user.restaurant)
        start_date, end_date = service.get_fiscal_year_dates()
        
        return Response({
            'current_fiscal_year': {
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'nepali_start_date': service.nepali_datetime.to_nepali(start_date),
                'nepali_end_date': service.nepali_datetime.to_nepali(end_date),
            },
            'available_reports': [
                {
                    'type': 'profit_loss',
                    'name': 'Profit & Loss Statement',
                    'description': 'Revenue, expenses, and profit analysis'
                },
                {
                    'type': 'balance_sheet',
                    'name': 'Balance Sheet',
                    'description': 'Assets, liabilities, and equity snapshot'
                },
                {
                    'type': 'vat_summary',
                    'name': 'VAT Summary',
                    'description': 'VAT collected and paid for IRD filing'
                },
                {
                    'type': 'tds_summary',
                    'name': 'TDS Summary',
                    'description': 'TDS deducted on salaries and supplier payments'
                }
            ]
        })
        
    except Exception as e:
        logger.error(f"Error getting fiscal year info: {str(e)}")
        return Response({
            'success': False,
            'error': 'Failed to get fiscal year information'
        }, status=500)
