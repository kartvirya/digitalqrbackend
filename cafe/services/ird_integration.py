"""
IRD (Inland Revenue Department) Nepal integration service
Handles Central Billing Monitoring (CBM) system compliance
"""

import json
import hashlib
import requests
from datetime import datetime, date
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from ..models import Restaurant, bill, order
from .nepali_datetime import NepaliDateConverter, NepaliFiscalYear


class IRDConfig:
    """IRD configuration and endpoints"""
    
    # IRD CBM API endpoints (these would be the actual IRD endpoints)
    BASE_URL = "https://cbm.ird.gov.np/api/v1"
    
    ENDPOINTS = {
        'submit_bill': '/bill',
        'void_bill': '/bill/void',
        'check_status': '/bill/{bill_id}',
        'get_token': '/auth/token',
    }
    
    # Required bill fields for IRD
    REQUIRED_BILL_FIELDS = [
        'pan_number',           # Restaurant PAN
        'customer_pan',         # Customer PAN (optional for B2C)
        'fiscal_year',          # e.g., "2081/82"
        'bill_number',          # Sequential, cannot skip
        'bill_date_bs',         # Date in Bikram Sambat
        'total_amount',         # Total bill amount
        'vat_amount',           # VAT amount
        'taxable_amount',       # Amount before VAT
        'items',                # Bill items list
    ]


class IRDService:
    """Service for IRD CBM integration"""
    
    def __init__(self, restaurant: Restaurant):
        self.restaurant = restaurant
        self.config = IRDConfig()
        
        # Get IRD credentials from restaurant settings
        self.pan_number = restaurant.settings.get('ird_pan_number')
        self.api_token = restaurant.settings.get('ird_api_token')
        self.is_enabled = restaurant.settings.get('ird_enabled', False)
        
    def is_ird_enabled(self) -> bool:
        """Check if IRD integration is enabled for this restaurant"""
        return (
            self.is_enabled and 
            self.pan_number and 
            self.api_token and
            self.restaurant.subscription_status == 'active'
        )
    
    def submit_bill_to_ird(self, bill_obj: bill) -> dict:
        """
        Submit bill to IRD CBM system
        Returns: IRD response with bill_id and verification data
        """
        if not self.is_ird_enabled():
            return {'error': 'IRD integration not enabled for this restaurant'}
        
        try:
            # Prepare bill data for IRD
            bill_data = self._prepare_bill_data(bill_obj)
            
            # Submit to IRD API
            response = self._make_ird_request('submit_bill', bill_data)
            
            if response.get('success'):
                # Store IRD response in bill metadata
                bill_metadata = bill_obj.metadata or {}
                bill_metadata.update({
                    'ird_submitted': True,
                    'ird_bill_id': response.get('bill_id'),
                    'ird_response': response,
                    'ird_submitted_at': timezone.now().isoformat(),
                })
                bill_obj.metadata = bill_metadata
                bill_obj.save(update_fields=['metadata'])
                
                return {
                    'success': True,
                    'bill_id': response.get('bill_id'),
                    'qr_code': response.get('qr_code'),
                    'verification_url': response.get('verification_url'),
                }
            else:
                return {
                    'success': False,
                    'error': response.get('error', 'Unknown error'),
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f'IRD submission failed: {str(e)}',
            }
    
    def void_bill_in_ird(self, bill_obj: bill, reason: str) -> dict:
        """
        Void/cancel bill in IRD system
        Returns: IRD response
        """
        if not self.is_ird_enabled():
            return {'error': 'IRD integration not enabled for this restaurant'}
        
        # Check if bill was submitted to IRD
        bill_metadata = bill_obj.metadata or {}
        if not bill_metadata.get('ird_submitted'):
            return {'error': 'Bill was not submitted to IRD'}
        
        ird_bill_id = bill_metadata.get('ird_bill_id')
        if not ird_bill_id:
            return {'error': 'IRD bill ID not found'}
        
        try:
            void_data = {
                'pan_number': self.pan_number,
                'bill_id': ird_bill_id,
                'reason': reason,
                'void_date_bs': self._get_current_bs_date(),
            }
            
            response = self._make_ird_request('void_bill', void_data)
            
            if response.get('success'):
                # Update bill metadata
                bill_metadata.update({
                    'ird_voided': True,
                    'ird_void_reason': reason,
                    'ird_void_response': response,
                    'ird_voided_at': timezone.now().isoformat(),
                })
                bill_obj.metadata = bill_metadata
                bill_obj.save(update_fields=['metadata'])
                
                return {'success': True, 'message': 'Bill voided successfully'}
            else:
                return {
                    'success': False,
                    'error': response.get('error', 'Unknown error'),
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f'IRD void failed: {str(e)}',
            }
    
    def check_ird_bill_status(self, bill_obj: bill) -> dict:
        """Check status of submitted bill in IRD system"""
        if not self.is_ird_enabled():
            return {'error': 'IRD integration not enabled for this restaurant'}
        
        bill_metadata = bill_obj.metadata or {}
        ird_bill_id = bill_metadata.get('ird_bill_id')
        
        if not ird_bill_id:
            return {'error': 'IRD bill ID not found'}
        
        try:
            endpoint = self.config.ENDPOINTS['check_status'].format(bill_id=ird_bill_id)
            response = self._make_ird_request('check_status', {'bill_id': ird_bill_id})
            
            return response
            
        except Exception as e:
            return {
                'success': False,
                'error': f'IRD status check failed: {str(e)}',
            }
    
    def generate_ird_compliant_invoice(self, bill_obj: bill) -> dict:
        """
        Generate IRD-compliant invoice data
        Returns: Invoice data with all required fields for printing
        """
        try:
            # Get fiscal year
            fiscal_year_bs, fiscal_year_ad = NepaliFiscalYear.get_current_fiscal_year(bill_obj.bill_time.date())
            
            # Convert bill date to BS
            bs_year, bs_month, bs_day = NepaliDateConverter.ad_to_bs(bill_obj.bill_time.date())
            bill_date_bs = NepaliDateConverter.format_bs_date(bs_year, bs_month, bs_day)
            
            # Parse order items
            order_items = json.loads(bill_obj.order_items) if isinstance(bill_obj.order_items, str) else bill_obj.order_items
            
            # Calculate VAT
            total_amount = Decimal(str(bill_obj.bill_total))
            vat_rate = Decimal('0.13')  # 13% VAT
            vat_amount = total_amount * vat_rate / (1 + vat_rate)
            taxable_amount = total_amount - vat_amount
            
            # Prepare invoice data
            invoice_data = {
                'restaurant_info': {
                    'name': self.restaurant.name,
                    'pan_number': self.pan_number,
                    'address': self.restaurant.address,
                    'phone': self.restaurant.phone,
                    'email': self.restaurant.email,
                },
                'bill_info': {
                    'invoice_number': bill_obj.invoice_number,
                    'bill_number': bill_obj.invoice_number,  # Same as invoice number
                    'bill_date_ad': bill_obj.bill_time.strftime('%Y-%m-%d'),
                    'bill_date_bs': bill_date_bs,
                    'fiscal_year_bs': fiscal_year_bs,
                    'fiscal_year_ad': fiscal_year_ad,
                    'customer_name': bill_obj.name,
                    'customer_phone': bill_obj.phone,
                    'table_number': bill_obj.table_number,
                    'payment_method': bill_obj.payment_method,
                    'payment_status': bill_obj.payment_status,
                },
                'amounts': {
                    'total_amount': float(total_amount),
                    'taxable_amount': float(taxable_amount),
                    'vat_amount': float(vat_amount),
                    'vat_rate': 13.0,
                    'tip_amount': float(bill_obj.tip_amount) if bill_obj.tip_amount else 0.0,
                },
                'items': [],
                'ird_info': {
                    'enabled': self.is_ird_enabled(),
                    'submitted': False,
                    'bill_id': None,
                    'qr_code': None,
                }
            }
            
            # Add order items
            for item in order_items:
                invoice_data['items'].append({
                    'name': item.get('name', 'Unknown Item'),
                    'quantity': item.get('quantity', 1),
                    'unit_price': float(item.get('price', 0)),
                    'total_price': float(item.get('price', 0) * item.get('quantity', 1)),
                    'category': item.get('category', 'Food'),
                })
            
            # Add IRD submission info if available
            bill_metadata = bill_obj.metadata or {}
            if bill_metadata.get('ird_submitted'):
                invoice_data['ird_info'].update({
                    'submitted': True,
                    'bill_id': bill_metadata.get('ird_bill_id'),
                    'qr_code': bill_metadata.get('ird_response', {}).get('qr_code'),
                    'submitted_at': bill_metadata.get('ird_submitted_at'),
                })
            
            return invoice_data
            
        except Exception as e:
            return {
                'error': f'Failed to generate invoice data: {str(e)}',
            }
    
    def _prepare_bill_data(self, bill_obj: bill) -> dict:
        """Prepare bill data in IRD format"""
        # Get fiscal year and BS date
        fiscal_year_bs, _ = NepaliFiscalYear.get_current_fiscal_year(bill_obj.bill_time.date())
        bs_year, bs_month, bs_day = NepaliDateConverter.ad_to_bs(bill_obj.bill_time.date())
        
        # Parse order items
        order_items = json.loads(bill_obj.order_items) if isinstance(bill_obj.order_items, str) else bill_obj.order_items
        
        # Calculate amounts
        total_amount = Decimal(str(bill_obj.bill_total))
        vat_rate = Decimal('0.13')
        vat_amount = total_amount * vat_rate / (1 + vat_rate)
        taxable_amount = total_amount - vat_amount
        
        # Prepare bill items for IRD
        ird_items = []
        for item in order_items:
            ird_items.append({
                'item_name': item.get('name', 'Unknown Item'),
                'quantity': item.get('quantity', 1),
                'unit_price': float(item.get('price', 0)),
                'total_amount': float(item.get('price', 0) * item.get('quantity', 1)),
                'vat_rate': 13.0,
            })
        
        return {
            'pan_number': self.pan_number,
            'customer_pan': None,  # Optional for B2C transactions
            'fiscal_year': fiscal_year_bs,
            'bill_number': bill_obj.invoice_number,
            'bill_date_bs': NepaliDateConverter.format_bs_date(bs_year, bs_month, bs_day),
            'total_amount': float(total_amount),
            'vat_amount': float(vat_amount),
            'taxable_amount': float(taxable_amount),
            'items': ird_items,
            'customer_name': bill_obj.name,
            'customer_phone': bill_obj.phone,
        }
    
    def _make_ird_request(self, endpoint_type: str, data: dict) -> dict:
        """Make request to IRD API"""
        # This is a mock implementation
        # In production, this would make actual HTTP requests to IRD endpoints
        
        if settings.DEBUG:
            # Mock response for development
            if endpoint_type == 'submit_bill':
                return {
                    'success': True,
                    'bill_id': f'IRD_{data["bill_number"]}_{int(datetime.now().timestamp())}',
                    'qr_code': f'QR_CODE_{data["bill_number"]}',
                    'verification_url': f'https://verify.ird.gov.np/{data["bill_number"]}',
                }
            elif endpoint_type == 'void_bill':
                return {
                    'success': True,
                    'message': 'Bill voided successfully',
                }
            elif endpoint_type == 'check_status':
                return {
                    'success': True,
                    'status': 'active',
                    'verified_at': datetime.now().isoformat(),
                }
        
        # In production, make actual HTTP request
        # This is where you'd implement the real IRD API calls
        endpoint = self.config.ENDPOINTS.get(endpoint_type)
        if not endpoint:
            return {'success': False, 'error': f'Unknown endpoint: {endpoint_type}'}
        
        # Mock implementation - replace with actual API calls
        return {'success': False, 'error': 'Production IRD API not implemented'}
    
    def _get_current_bs_date(self) -> str:
        """Get current date in BS format"""
        today = timezone.now().date()
        bs_year, bs_month, bs_day = NepaliDateConverter.ad_to_bs(today)
        return NepaliDateConverter.format_bs_date(bs_year, bs_month, bs_day)


class IRDComplianceService:
    """Service for IRD compliance checks and reporting"""
    
    def __init__(self, restaurant: Restaurant):
        self.restaurant = restaurant
        self.ird_service = IRDService(restaurant)
    
    def check_bill_compliance(self, bill_obj: bill) -> dict:
        """Check if bill complies with IRD requirements"""
        issues = []
        warnings = []
        
        # Check required fields
        if not bill_obj.invoice_number:
            issues.append("Invoice number is required")
        
        if not bill_obj.bill_time:
            issues.append("Bill date is required")
        
        if not bill_obj.bill_total or bill_obj.bill_total <= 0:
            issues.append("Bill total must be greater than 0")
        
        # Check IRD-specific requirements
        if self.ird_service.is_ird_enabled():
            if not self.ird_service.pan_number:
                issues.append("Restaurant PAN number is required for IRD")
            
            # Check if bill was submitted to IRD
            bill_metadata = bill_obj.metadata or {}
            if not bill_metadata.get('ird_submitted'):
                warnings.append("Bill not submitted to IRD CBM system")
        
        # Check sequential invoice numbers
        if bill_obj.invoice_number:
            if not self._is_sequential_invoice(bill_obj):
                issues.append("Invoice numbers must be sequential and cannot skip")
        
        return {
            'compliant': len(issues) == 0,
            'issues': issues,
            'warnings': warnings,
        }
    
    def generate_vat_report(self, start_date: date, end_date: date) -> dict:
        """Generate VAT report for IRD filing"""
        bills = bill.objects.filter(
            restaurant=self.restaurant,
            bill_time__date__range=[start_date, end_date],
            payment_status='paid'
        )
        
        total_sales = Decimal('0')
        total_vat = Decimal('0')
        taxable_sales = Decimal('0')
        
        bill_details = []
        
        for bill_obj in bills:
            total_amount = Decimal(str(bill_obj.bill_total))
            vat_rate = Decimal('0.13')
            vat_amount = total_amount * vat_rate / (1 + vat_rate)
            taxable_amount = total_amount - vat_amount
            
            total_sales += total_amount
            total_vat += vat_amount
            taxable_sales += taxable_amount
            
            bill_details.append({
                'invoice_number': bill_obj.invoice_number,
                'bill_date': bill_obj.bill_time.date(),
                'total_amount': float(total_amount),
                'vat_amount': float(vat_amount),
                'taxable_amount': float(taxable_amount),
                'customer_name': bill_obj.name,
                'ird_submitted': bill_obj.metadata.get('ird_submitted', False) if bill_obj.metadata else False,
            })
        
        return {
            'period': {
                'start_date': start_date,
                'end_date': end_date,
                'fiscal_year': NepaliFiscalYear.get_current_fiscal_year(start_date)[0],
            },
            'summary': {
                'total_bills': len(bills),
                'total_sales': float(total_sales),
                'total_vat': float(total_vat),
                'taxable_sales': float(taxable_sales),
            },
            'bills': bill_details,
        }
    
    def _is_sequential_invoice(self, bill_obj: bill) -> bool:
        """Check if invoice number is sequential"""
        # Get previous bill
        previous_bill = bill.objects.filter(
            restaurant=self.restaurant,
            bill_time__lt=bill_obj.bill_time
        ).order_by('-bill_time').first()
        
        if not previous_bill:
            return True  # First bill is always valid
        
        # Simple numeric check - in production, this would be more sophisticated
        try:
            current_num = int(bill_obj.invoice_number)
            previous_num = int(previous_bill.invoice_number)
            return current_num == previous_num + 1
        except (ValueError, TypeError):
            return False  # Non-numeric invoice numbers need different validation
