"""
Financial reports generation service
Generates P&L, Balance Sheet, and VAT summary reports with Nepal compliance
"""

from datetime import datetime, timedelta
from decimal import Decimal
from django.db.models import Sum, Q, Count, Avg
from django.utils import timezone
from ..models import (
    ChartOfAccounts, JournalEntry, JournalEntryLine, 
    Bill, Order, TaxConfiguration, FiscalYear, AccountingPeriod,
    Restaurant, Staff, Payroll, PurchaseOrder
)
from .nepali_datetime import NepaliDateTime


class FinancialReportsService:
    """Service for generating financial reports"""
    
    def __init__(self, restaurant: Restaurant):
        self.restaurant = restaurant
        self.nepali_datetime = NepaliDateTime()
    
    def generate_profit_loss_statement(self, start_date: datetime, end_date: datetime) -> dict:
        """Generate Profit & Loss statement"""
        try:
            # Get revenue accounts (income)
            revenue_accounts = ChartOfAccounts.objects.filter(
                restaurant=self.restaurant,
                account_type='revenue',
                is_active=True
            )
            
            # Get expense accounts
            expense_accounts = ChartOfAccounts.objects.filter(
                restaurant=self.restaurant,
                account_type='expense',
                is_active=True
            )
            
            # Get cost of goods sold accounts
            cogs_accounts = ChartOfAccounts.objects.filter(
                restaurant=self.restaurant,
                account_type='expense',
                name__icontains='cost of goods'
            )
            
            # Calculate totals for each category
            revenue_data = self._calculate_account_totals(revenue_accounts, start_date, end_date)
            expense_data = self._calculate_account_totals(expense_accounts, start_date, end_date)
            cogs_data = self._calculate_account_totals(cogs_accounts, start_date, end_date)
            
            # Calculate gross profit
            total_revenue = sum(item['total'] for item in revenue_data)
            total_cogs = sum(item['total'] for item in cogs_data)
            gross_profit = total_revenue - total_cogs
            
            # Calculate operating expenses
            operating_expenses = sum(item['total'] for item in expense_data if item['account'].name not in ['Cost of Goods Sold'])
            
            # Calculate net profit
            net_profit = gross_profit - operating_expenses
            
            return {
                'period': {
                    'start_date': start_date.isoformat(),
                    'end_date': end_date.isoformat(),
                    'nepali_start_date': self.nepali_datetime.to_nepali(start_date),
                    'nepali_end_date': self.nepali_datetime.to_nepali(end_date),
                },
                'revenue': revenue_data,
                'cost_of_goods_sold': cogs_data,
                'gross_profit': gross_profit,
                'operating_expenses': expense_data,
                'net_profit': net_profit,
                'total_revenue': total_revenue,
                'total_expenses': total_cogs + operating_expenses,
                'profit_margin': (net_profit / total_revenue * 100) if total_revenue > 0 else 0,
                'generated_at': timezone.now().isoformat(),
            }
            
        except Exception as e:
            return {
                'error': str(e),
                'period': {
                    'start_date': start_date.isoformat(),
                    'end_date': end_date.isoformat(),
                },
                'revenue': [],
                'cost_of_goods_sold': [],
                'operating_expenses': [],
                'gross_profit': 0,
                'net_profit': 0,
                'total_revenue': 0,
                'total_expenses': 0,
                'profit_margin': 0,
            }
    
    def generate_balance_sheet(self, as_of_date: datetime) -> dict:
        """Generate Balance Sheet"""
        try:
            # Get asset accounts
            asset_accounts = ChartOfAccounts.objects.filter(
                restaurant=self.restaurant,
                account_type='asset',
                is_active=True
            )
            
            # Get liability accounts
            liability_accounts = ChartOfAccounts.objects.filter(
                restaurant=self.restaurant,
                account_type='liability',
                is_active=True
            )
            
            # Get equity accounts
            equity_accounts = ChartOfAccounts.objects.filter(
                restaurant=self.restaurant,
                account_type='equity',
                is_active=True
            )
            
            # Calculate balances
            assets_data = self._calculate_account_balances(asset_accounts, as_of_date)
            liabilities_data = self._calculate_account_balances(liability_accounts, as_of_date)
            equity_data = self._calculate_account_balances(equity_accounts, as_of_date)
            
            # Calculate totals
            total_assets = sum(item['balance'] for item in assets_data)
            total_liabilities = sum(item['balance'] for item in liabilities_data)
            total_equity = sum(item['balance'] for item in equity_data)
            
            # Verify balance sheet equation
            balance_difference = total_assets - (total_liabilities + total_equity)
            
            return {
                'as_of_date': as_of_date.isoformat(),
                'nepali_date': self.nepali_datetime.to_nepali(as_of_date),
                'assets': assets_data,
                'liabilities': liabilities_data,
                'equity': equity_data,
                'total_assets': total_assets,
                'total_liabilities': total_liabilities,
                'total_equity': total_equity,
                'balance_difference': balance_difference,
                'is_balanced': abs(balance_difference) < Decimal('0.01'),
                'generated_at': timezone.now().isoformat(),
            }
            
        except Exception as e:
            return {
                'error': str(e),
                'as_of_date': as_of_date.isoformat(),
                'assets': [],
                'liabilities': [],
                'equity': [],
                'total_assets': 0,
                'total_liabilities': 0,
                'total_equity': 0,
                'balance_difference': 0,
                'is_balanced': False,
            }
    
    def generate_vat_summary(self, start_date: datetime, end_date: datetime) -> dict:
        """Generate VAT summary report for IRD filing"""
        try:
            # Get VAT configuration
            vat_config = TaxConfiguration.objects.filter(
                restaurant=self.restaurant,
                tax_type='vat',
                is_active=True
            ).first()
            
            if not vat_config:
                return {
                    'error': 'VAT configuration not found',
                    'period': {
                        'start_date': start_date.isoformat(),
                        'end_date': end_date.isoformat(),
                    },
                    'total_sales': 0,
                    'total_vat_collected': 0,
                    'total_purchases': 0,
                    'total_vat_paid': 0,
                    'net_vat_payable': 0,
                }
            
            # Get sales data (bills)
            sales_data = Bill.objects.filter(
                restaurant=self.restaurant,
                created_at__gte=start_date,
                created_at__lte=end_date,
                status='paid'
            ).aggregate(
                total_sales=Sum('total_amount'),
                total_vat_collected=Sum('total_tax_amount'),
                sales_count=Count('id')
            )
            
            # Get purchase data (purchase orders)
            purchase_data = PurchaseOrder.objects.filter(
                restaurant=self.restaurant,
                created_at__gte=start_date,
                created_at__lte=end_date,
                status='completed'
            ).aggregate(
                total_purchases=Sum('total_amount'),
                total_vat_paid=Sum('total_tax_amount'),
                purchase_count=Count('id')
            )
            
            # Calculate VAT payable
            total_sales = sales_data['total_sales'] or Decimal('0')
            total_vat_collected = sales_data['total_vat_collected'] or Decimal('0')
            total_purchases = purchase_data['total_purchases'] or Decimal('0')
            total_vat_paid = purchase_data['total_vat_paid'] or Decimal('0')
            
            net_vat_payable = total_vat_collected - total_vat_paid
            
            # Get detailed transactions
            sales_transactions = Bill.objects.filter(
                restaurant=self.restaurant,
                created_at__gte=start_date,
                created_at__lte=end_date,
                status='paid'
            ).values(
                'bill_number', 'total_amount', 'total_tax_amount', 'created_at'
            ).order_by('-created_at')
            
            purchase_transactions = PurchaseOrder.objects.filter(
                restaurant=self.restaurant,
                created_at__gte=start_date,
                created_at__lte=end_date,
                status='completed'
            ).values(
                'order_number', 'total_amount', 'total_tax_amount', 'created_at'
            ).order_by('-created_at')
            
            return {
                'period': {
                    'start_date': start_date.isoformat(),
                    'end_date': end_date.isoformat(),
                    'nepali_start_date': self.nepali_datetime.to_nepali(start_date),
                    'nepali_end_date': self.nepali_datetime.to_nepali(end_date),
                },
                'vat_config': {
                    'rate': vat_config.rate,
                    'registration_number': getattr(vat_config, 'registration_number', ''),
                },
                'summary': {
                    'total_sales': total_sales,
                    'total_vat_collected': total_vat_collected,
                    'total_purchases': total_purchases,
                    'total_vat_paid': total_vat_paid,
                    'net_vat_payable': net_vat_payable,
                    'sales_count': sales_data['sales_count'] or 0,
                    'purchase_count': purchase_data['purchase_count'] or 0,
                },
                'sales_transactions': list(sales_transactions),
                'purchase_transactions': list(purchase_transactions),
                'generated_at': timezone.now().isoformat(),
            }
            
        except Exception as e:
            return {
                'error': str(e),
                'period': {
                    'start_date': start_date.isoformat(),
                    'end_date': end_date.isoformat(),
                },
                'summary': {
                    'total_sales': 0,
                    'total_vat_collected': 0,
                    'total_purchases': 0,
                    'total_vat_paid': 0,
                    'net_vat_payable': 0,
                },
            }
    
    def generate_tds_summary(self, start_date: datetime, end_date: datetime) -> dict:
        """Generate TDS summary report for supplier payments"""
        try:
            # Get TDS configuration
            tds_config = TaxConfiguration.objects.filter(
                restaurant=self.restaurant,
                tax_type='tds',
                is_active=True
            ).first()
            
            if not tds_config:
                return {
                    'error': 'TDS configuration not found',
                    'period': {
                        'start_date': start_date.isoformat(),
                        'end_date': end_date.isoformat(),
                    },
                    'total_payments': 0,
                    'total_tds_deducted': 0,
                }
            
            # Get payroll data (TDS on salaries)
            payroll_data = Payroll.objects.filter(
                restaurant=self.restaurant,
                payroll_date__gte=start_date,
                payroll_date__lte=end_date,
                status='paid'
            ).aggregate(
                total_salary=Sum('gross_salary'),
                total_tds=Sum('tds_amount'),
                employee_count=Count('id', distinct=True)
            )
            
            # Get supplier payment data (TDS on purchases)
            supplier_payments = PurchaseOrder.objects.filter(
                restaurant=self.restaurant,
                created_at__gte=start_date,
                created_at__lte=end_date,
                status='completed',
                supplier__isnull=False
            ).values(
                'supplier__name', 'supplier__pan_number', 'total_amount', 'total_tax_amount'
            ).order_by('-created_at')
            
            total_payments = (payroll_data['total_salary'] or Decimal('0')) + \
                          sum(po['total_amount'] for po in supplier_payments)
            
            total_tds_deducted = (payroll_data['total_tds'] or Decimal('0')) + \
                               sum(po['total_tax_amount'] for po in supplier_payments)
            
            return {
                'period': {
                    'start_date': start_date.isoformat(),
                    'end_date': end_date.isoformat(),
                    'nepali_start_date': self.nepali_datetime.to_nepali(start_date),
                    'nepali_end_date': self.nepali_datetime.to_nepali(end_date),
                },
                'tds_config': {
                    'salary_rate': getattr(tds_config, 'salary_rate', 0),
                    'supplier_rate': getattr(tds_config, 'supplier_rate', 0),
                },
                'summary': {
                    'total_payments': total_payments,
                    'total_tds_deducted': total_tds_deducted,
                    'salary_payments': payroll_data['total_salary'] or Decimal('0'),
                    'salary_tds': payroll_data['total_tds'] or Decimal('0'),
                    'supplier_payments': sum(po['total_amount'] for po in supplier_payments),
                    'supplier_tds': sum(po['total_tax_amount'] for po in supplier_payments),
                    'employee_count': payroll_data['employee_count'] or 0,
                },
                'supplier_details': list(supplier_payments),
                'generated_at': timezone.now().isoformat(),
            }
            
        except Exception as e:
            return {
                'error': str(e),
                'period': {
                    'start_date': start_date.isoformat(),
                    'end_date': end_date.isoformat(),
                },
                'summary': {
                    'total_payments': 0,
                    'total_tds_deducted': 0,
                },
            }
    
    def _calculate_account_totals(self, accounts, start_date: datetime, end_date: datetime) -> list:
        """Calculate total amounts for accounts within date range"""
        results = []
        
        for account in accounts:
            # Get journal entry lines for this account
            lines = JournalEntryLine.objects.filter(
                account=account,
                journal_entry__date__gte=start_date,
                journal_entry__date__lte=end_date,
                journal_entry__restaurant=self.restaurant,
                journal_entry__is_posted=True
            )
            
            # Calculate total based on account type and normal balance
            if account.normal_balance == 'debit':
                total = lines.aggregate(
                    total=Sum('debit_amount') - Sum('credit_amount')
                )['total'] or Decimal('0')
            else:  # credit
                total = lines.aggregate(
                    total=Sum('credit_amount') - Sum('debit_amount')
                )['total'] or Decimal('0')
            
            if total != 0:
                results.append({
                    'account': {
                        'id': account.id,
                        'name': account.name,
                        'code': account.code,
                        'account_type': account.account_type,
                        'normal_balance': account.normal_balance,
                    },
                    'total': abs(total),
                    'transaction_count': lines.count(),
                })
        
        return results
    
    def _calculate_account_balances(self, accounts, as_of_date: datetime) -> list:
        """Calculate balances for accounts as of specific date"""
        results = []
        
        for account in accounts:
            # Get journal entry lines for this account up to the date
            lines = JournalEntryLine.objects.filter(
                account=account,
                journal_entry__date__lte=as_of_date,
                journal_entry__restaurant=self.restaurant,
                journal_entry__is_posted=True
            )
            
            # Calculate balance based on account type and normal balance
            if account.normal_balance == 'debit':
                balance = lines.aggregate(
                    balance=Sum('debit_amount') - Sum('credit_amount')
                )['balance'] or Decimal('0')
            else:  # credit
                balance = lines.aggregate(
                    balance=Sum('credit_amount') - Sum('debit_amount')
                )['balance'] or Decimal('0')
            
            if balance != 0:
                results.append({
                    'account': {
                        'id': account.id,
                        'name': account.name,
                        'code': account.code,
                        'account_type': account.account_type,
                        'normal_balance': account.normal_balance,
                    },
                    'balance': abs(balance),
                    'transaction_count': lines.count(),
                })
        
        return results
    
    def get_fiscal_year_dates(self) -> tuple:
        """Get current fiscal year start and end dates"""
        current_year = timezone.now().year
        current_month = timezone.now().month
        
        # Nepal fiscal year typically runs from mid-July to mid-July
        if current_month >= 7:  # After July
            fiscal_year_start = datetime(current_year, 7, 16).date()
            fiscal_year_end = datetime(current_year + 1, 7, 15).date()
        else:  # Before July
            fiscal_year_start = datetime(current_year - 1, 7, 16).date()
            fiscal_year_end = datetime(current_year, 7, 15).date()
        
        return fiscal_year_start, fiscal_year_end
    
    def generate_comprehensive_report(self, report_type: str, start_date: datetime = None, end_date: datetime = None) -> dict:
        """Generate comprehensive financial report"""
        if not start_date or not end_date:
            start_date, end_date = self.get_fiscal_year_dates()
        
        if report_type == 'profit_loss':
            return self.generate_profit_loss_statement(start_date, end_date)
        elif report_type == 'balance_sheet':
            return self.generate_balance_sheet(end_date)
        elif report_type == 'vat_summary':
            return self.generate_vat_summary(start_date, end_date)
        elif report_type == 'tds_summary':
            return self.generate_tds_summary(start_date, end_date)
        else:
            return {
                'error': f'Unknown report type: {report_type}',
                'available_types': ['profit_loss', 'balance_sheet', 'vat_summary', 'tds_summary']
            }
