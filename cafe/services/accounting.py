from decimal import Decimal
from datetime import datetime, date
from django.db import transaction
from django.utils import timezone
from ..models import (
    Restaurant, ChartOfAccounts, JournalEntry, JournalEntryLine, 
    TaxConfiguration, FiscalYear, AccountingPeriod, order, bill
)


class AccountingService:
    """Service for handling accounting operations with Nepal compliance"""
    
    def __init__(self, restaurant):
        self.restaurant = restaurant
    
    def create_sales_journal_entry(self, order_obj, bill_obj=None):
        """
        Create journal entry for sales with VAT calculation
        Debit: Accounts Receivable/Cash
        Credit: Food Sales, Beverage Sales, VAT Payable
        """
        if not self.restaurant:
            raise ValueError("Restaurant is required for accounting operations")
        
        with transaction.atomic():
            # Get tax configurations
            vat_config = TaxConfiguration.objects.filter(
                restaurant=self.restaurant,
                tax_type='vat',
                is_active=True
            ).first()
            
            vat_rate = Decimal(str(vat_config.rate_percentage)) / 100 if vat_config else Decimal('0.13')
            
            # Calculate amounts
            total_amount = Decimal(str(bill_obj.bill_total if bill_obj else order_obj.price))
            vat_amount = total_amount * vat_rate / (1 + vat_rate)  # Extract VAT from inclusive amount
            net_sales = total_amount - vat_amount
            
            # Create journal entry
            entry = JournalEntry.objects.create(
                restaurant=self.restaurant,
                date=timezone.now().date(),
                description=f"Sales - Order #{order_obj.id}",
                reference_type='order',
                reference_id=str(order_obj.id),
                total_debit=total_amount,
                total_credit=total_amount,
                created_by=order_obj.user
            )
            
            # Get accounts
            cash_account = self._get_account_by_code('1000')  # Cash/eSewa/Khalti
            receivables_account = self._get_account_by_code('1100')  # Accounts Receivable
            food_sales_account = self._get_account_by_code('4000')  # Food Sales
            vat_payable_account = self._get_account_by_code('2100')  # VAT Payable
            
            # Determine if cash or credit sale
            if order_obj.payment_status == 'paid':
                # Cash sale
                JournalEntryLine.objects.create(
                    journal_entry=entry,
                    account=cash_account,
                    description=f"Cash sales - Order #{order_obj.id}",
                    debit_amount=total_amount,
                    credit_amount=0
                )
            else:
                # Credit sale
                JournalEntryLine.objects.create(
                    journal_entry=entry,
                    account=receivables_account,
                    description=f"Credit sales - Order #{order_obj.id}",
                    debit_amount=total_amount,
                    credit_amount=0
                )
            
            # Credit sales accounts
            JournalEntryLine.objects.create(
                journal_entry=entry,
                account=food_sales_account,
                description=f"Food sales - Order #{order_obj.id}",
                debit_amount=0,
                credit_amount=net_sales
            )
            
            # Credit VAT payable
            JournalEntryLine.objects.create(
                journal_entry=entry,
                account=vat_payable_account,
                description=f"VAT on sales - Order #{order_obj.id}",
                debit_amount=0,
                credit_amount=vat_amount
            )
            
            # Post the entry
            entry.is_posted = True
            entry.posted_at = timezone.now()
            entry.save()
            
            return entry
    
    def create_purchase_journal_entry(self, purchase_order):
        """
        Create journal entry for purchase with TDS and input VAT
        Debit: Inventory, VAT Input (if applicable)
        Credit: Accounts Payable, TDS Payable
        """
        with transaction.atomic():
            # Get tax configurations
            tds_goods_config = TaxConfiguration.objects.filter(
                restaurant=self.restaurant,
                tax_type='tds_goods',
                is_active=True
            ).first()
            
            tds_rate = Decimal(str(tds_goods_config.rate_percentage)) / 100 if tds_goods_config else Decimal('0.015')
            
            # Calculate totals
            total_amount = Decimal('0')
            for line in purchase_order.lines.all():
                if line.unit_cost and line.quantity_received:
                    total_amount += line.unit_cost * line.quantity_received
            
            tds_amount = total_amount * tds_rate
            net_payment = total_amount - tds_amount
            
            # Create journal entry
            entry = JournalEntry.objects.create(
                restaurant=self.restaurant,
                date=timezone.now().date(),
                description=f"Purchase - PO #{purchase_order.id}",
                reference_type='purchase_order',
                reference_id=str(purchase_order.id),
                total_debit=total_amount,
                total_credit=total_amount,
                created_by=purchase_order.created_by
            )
            
            # Get accounts
            inventory_account = self._get_account_by_code('1200')  # Inventory
            payables_account = self._get_account_by_code('2000')  # Accounts Payable
            tds_payable_account = self._get_account_by_code('2200')  # TDS Payable
            
            # Debit inventory
            JournalEntryLine.objects.create(
                journal_entry=entry,
                account=inventory_account,
                description=f"Purchase - PO #{purchase_order.id}",
                debit_amount=total_amount,
                credit_amount=0
            )
            
            # Credit accounts payable (net of TDS)
            JournalEntryLine.objects.create(
                journal_entry=entry,
                account=payables_account,
                description=f"Supplier payment - PO #{purchase_order.id}",
                debit_amount=0,
                credit_amount=net_payment
            )
            
            # Credit TDS payable
            JournalEntryLine.objects.create(
                journal_entry=entry,
                account=tds_payable_account,
                description=f"TDS on purchase - PO #{purchase_order.id}",
                debit_amount=0,
                credit_amount=tds_amount
            )
            
            # Post the entry
            entry.is_posted = True
            entry.posted_at = timezone.now()
            entry.save()
            
            return entry
    
    def create_payroll_journal_entry(self, payroll_obj):
        """
        Create journal entry for payroll with SSF calculations
        Debit: Salaries & Wages Expense
        Credit: Cash/eSewa, SSF Payable (both employer and employee portions), TDS Payable
        """
        with transaction.atomic():
            # Get tax configurations
            ssf_employer_config = TaxConfiguration.objects.filter(
                restaurant=self.restaurant,
                tax_type='ssf_employer',
                is_active=True
            ).first()
            
            ssf_employee_config = TaxConfiguration.objects.filter(
                restaurant=self.restaurant,
                tax_type='ssf_employee',
                is_active=True
            ).first()
            
            tds_config = TaxConfiguration.objects.filter(
                restaurant=self.restaurant,
                tax_type='tds_services',
                is_active=True
            ).first()
            
            ssf_employer_rate = Decimal(str(ssf_employer_config.rate_percentage)) / 100 if ssf_employer_config else Decimal('0.20')
            ssf_employee_rate = Decimal(str(ssf_employee_config.rate_percentage)) / 100 if ssf_employee_config else Decimal('0.11')
            tds_rate = Decimal(str(tds_config.rate_percentage)) / 100 if tds_config else Decimal('0.15')
            
            # Calculate amounts
            gross_salary = payroll_obj.basic_salary + payroll_obj.allowances
            ssf_employer = gross_salary * ssf_employer_rate
            ssf_employee = gross_salary * ssf_employee_rate
            tds_amount = gross_salary * tds_rate
            net_salary = gross_salary - ssf_employee - tds_amount
            total_cost = gross_salary + ssf_employer  # Total cost to company
            
            # Create journal entry
            entry = JournalEntry.objects.create(
                restaurant=self.restaurant,
                date=payroll_obj.payment_date,
                description=f"Payroll - {payroll_obj.employee.full_name} for {payroll_obj.month}/{payroll_obj.year}",
                reference_type='payroll',
                reference_id=str(payroll_obj.id),
                total_debit=total_cost,
                total_credit=total_cost,
                created_by=payroll_obj.created_by
            )
            
            # Get accounts
            salary_expense_account = self._get_account_by_code('5200')  # Salaries & Wages
            cash_account = self._get_account_by_code('1000')  # Cash/eSewa/Khalti
            ssf_payable_account = self._get_account_by_code('2300')  # SSF Payable
            tds_payable_account = self._get_account_by_code('2200')  # TDS Payable
            
            # Debit salary expense (gross + employer SSF)
            JournalEntryLine.objects.create(
                journal_entry=entry,
                account=salary_expense_account,
                description=f"Salary expense - {payroll_obj.employee.full_name}",
                debit_amount=total_cost,
                credit_amount=0
            )
            
            # Credit cash (net salary)
            JournalEntryLine.objects.create(
                journal_entry=entry,
                account=cash_account,
                description=f"Net salary payment - {payroll_obj.employee.full_name}",
                debit_amount=0,
                credit_amount=net_salary
            )
            
            # Credit SSF payable (both employer and employee portions)
            total_ssf = ssf_employer + ssf_employee
            JournalEntryLine.objects.create(
                journal_entry=entry,
                account=ssf_payable_account,
                description=f"SSF contributions - {payroll_obj.employee.full_name}",
                debit_amount=0,
                credit_amount=total_ssf
            )
            
            # Credit TDS payable
            JournalEntryLine.objects.create(
                journal_entry=entry,
                account=tds_payable_account,
                description=f"TDS on salary - {payroll_obj.employee.full_name}",
                debit_amount=0,
                credit_amount=tds_amount
            )
            
            # Post the entry
            entry.is_posted = True
            entry.posted_at = timezone.now()
            entry.save()
            
            return entry
    
    def _get_account_by_code(self, code):
        """Helper to get chart of account by code"""
        try:
            return ChartOfAccounts.objects.get(
                restaurant=self.restaurant,
                code=code,
                is_active=True
            )
        except ChartOfAccounts.DoesNotExist:
            raise ValueError(f"Account with code {code} not found for restaurant {self.restaurant.name}")
    
    def generate_trial_balance(self, as_of_date=None):
        """Generate trial balance as of specific date"""
        if as_of_date is None:
            as_of_date = timezone.now().date()
        
        # Get all posted journal entries up to the date
        entries = JournalEntry.objects.filter(
            restaurant=self.restaurant,
            is_posted=True,
            date__lte=as_of_date
        ).prefetch_related('lines__account')
        
        # Calculate balances for each account
        account_balances = {}
        
        for entry in entries:
            for line in entry.lines:
                account_code = line.account.code
                if account_code not in account_balances:
                    account_balances[account_code] = {
                        'account': line.account,
                        'debit_total': Decimal('0'),
                        'credit_total': Decimal('0'),
                    }
                
                account_balances[account_code]['debit_total'] += line.debit_amount
                account_balances[account_code]['credit_total'] += line.credit_amount
        
        # Calculate final balances
        trial_balance = []
        for code, data in account_balances.items():
            account = data['account']
            debit_total = data['debit_total']
            credit_total = data['credit_total']
            
            # Calculate balance based on account type
            if account.account_type in ['asset', 'expense']:
                balance = debit_total - credit_total
                if balance > 0:
                    debit_balance = balance
                    credit_balance = Decimal('0')
                else:
                    debit_balance = Decimal('0')
                    credit_balance = abs(balance)
            else:  # liability, equity, revenue
                balance = credit_total - debit_total
                if balance > 0:
                    debit_balance = Decimal('0')
                    credit_balance = balance
                else:
                    debit_balance = abs(balance)
                    credit_balance = Decimal('0')
            
            trial_balance.append({
                'account_code': code,
                'account_name': account.name,
                'account_type': account.account_type,
                'debit_total': debit_total,
                'credit_total': credit_total,
                'debit_balance': debit_balance,
                'credit_balance': credit_balance,
            })
        
        return sorted(trial_balance, key=lambda x: x['account_code'])


class TaxService:
    """Service for Nepal tax calculations and compliance"""
    
    def __init__(self, restaurant):
        self.restaurant = restaurant
    
    def calculate_vat(self, amount, is_inclusive=True):
        """Calculate VAT for given amount"""
        vat_config = TaxConfiguration.objects.filter(
            restaurant=self.restaurant,
            tax_type='vat',
            is_active=True
        ).first()
        
        if not vat_config:
            return Decimal('0'), amount
        
        vat_rate = Decimal(str(vat_config.rate_percentage)) / 100
        
        if is_inclusive:
            # VAT is included in amount
            vat_amount = amount * vat_rate / (1 + vat_rate)
            net_amount = amount - vat_amount
        else:
            # VAT is additional to amount
            vat_amount = amount * vat_rate
            net_amount = amount
        
        return vat_amount, net_amount
    
    def calculate_tds(self, amount, transaction_type='goods'):
        """Calculate TDS for given amount and transaction type"""
        tax_type = f'tds_{transaction_type}'
        tds_config = TaxConfiguration.objects.filter(
            restaurant=self.restaurant,
            tax_type=tax_type,
            is_active=True
        ).first()
        
        if not tds_config:
            return Decimal('0'), amount
        
        tds_rate = Decimal(str(tds_config.rate_percentage)) / 100
        tds_amount = amount * tds_rate
        net_amount = amount - tds_amount
        
        return tds_amount, net_amount
    
    def calculate_ssf(self, gross_salary):
        """Calculate SSF contributions for salary"""
        ssf_employer_config = TaxConfiguration.objects.filter(
            restaurant=self.restaurant,
            tax_type='ssf_employer',
            is_active=True
        ).first()
        
        ssf_employee_config = TaxConfiguration.objects.filter(
            restaurant=self.restaurant,
            tax_type='ssf_employee',
            is_active=True
        ).first()
        
        employer_rate = Decimal(str(ssf_employer_config.rate_percentage)) / 100 if ssf_employer_config else Decimal('0.20')
        employee_rate = Decimal(str(ssf_employee_config.rate_percentage)) / 100 if ssf_employee_config else Decimal('0.11')
        
        ssf_employer = gross_salary * employer_rate
        ssf_employee = gross_salary * employee_rate
        
        return ssf_employer, ssf_employee
