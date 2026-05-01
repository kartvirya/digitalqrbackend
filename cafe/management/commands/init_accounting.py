from django.core.management.base import BaseCommand
from django.db import transaction
from cafe.models import Restaurant, ChartOfAccounts, TaxConfiguration, FiscalYear
from datetime import date


class Command(BaseCommand):
    help = 'Initialize standard chart of accounts and tax configurations for restaurants'

    def handle(self, *args, **options):
        # Standard Nepal restaurant chart of accounts
        standard_accounts = [
            # Assets
            ('1000', 'Cash / eSewa / Khalti', 'asset'),
            ('1100', 'Accounts Receivable', 'asset'),
            ('1200', 'Inventory', 'asset'),
            ('1300', 'Prepaid Expenses', 'asset'),
            ('1400', 'Fixed Assets - Equipment', 'asset'),
            ('1500', 'Accumulated Depreciation', 'asset'),
            
            # Liabilities
            ('2000', 'Accounts Payable', 'liability'),
            ('2100', 'VAT Payable (13%)', 'liability'),
            ('2200', 'TDS Payable', 'liability'),
            ('2300', 'SSF Payable', 'liability'),
            ('2400', 'Accrued Expenses', 'liability'),
            ('2500', 'Loans Payable', 'liability'),
            
            # Equity
            ('3000', "Owner's Equity", 'equity'),
            ('3100', 'Retained Earnings', 'equity'),
            ('3200', 'Capital Contributions', 'equity'),
            
            # Revenue
            ('4000', 'Food Sales', 'revenue'),
            ('4100', 'Beverage Sales', 'revenue'),
            ('4200', 'Service Charge Revenue', 'revenue'),
            ('4300', 'Other Revenue', 'revenue'),
            
            # Cost of Goods Sold
            ('5000', 'Cost of Goods Sold - Food', 'expense'),
            ('5100', 'Cost of Goods Sold - Beverages', 'expense'),
            
            # Operating Expenses
            ('5200', 'Salaries & Wages', 'expense'),
            ('5300', 'Rent Expense', 'expense'),
            ('5400', 'Utilities Expense', 'expense'),
            ('5500', 'Marketing & Advertising', 'expense'),
            ('5600', 'Repairs & Maintenance', 'expense'),
            ('5700', 'Supplies Expense', 'expense'),
            ('5800', 'Insurance Expense', 'expense'),
            ('5900', 'Bank Charges', 'expense'),
            ('6000', 'Depreciation Expense', 'expense'),
            ('6100', 'Other Operating Expenses', 'expense'),
        ]

        # Standard tax configurations
        tax_configs = [
            ('vat', 13.00, date(2023, 7, 17), None, 'Standard VAT rate for Nepal'),
            ('tds_goods', 1.50, date(2023, 7, 17), None, 'TDS on purchase of goods'),
            ('tds_services', 15.00, date(2023, 7, 17), None, 'TDS on professional services'),
            ('ssf_employer', 20.00, date(2023, 7, 17), None, 'Social Security Fund - Employer contribution'),
            ('ssf_employee', 11.00, date(2023, 7, 17), None, 'Social Security Fund - Employee deduction'),
            ('service_charge', 10.00, date(2023, 7, 17), None, 'Service charge (typical for Kathmandu restaurants)'),
        ]

        restaurants = Restaurant.objects.all()
        
        for restaurant in restaurants:
            self.stdout.write(f"Processing restaurant: {restaurant.name}")
            
            with transaction.atomic():
                # Create chart of accounts
                accounts_created = 0
                for code, name, account_type in standard_accounts:
                    account, created = ChartOfAccounts.objects.get_or_create(
                        restaurant=restaurant,
                        code=code,
                        defaults={
                            'name': name,
                            'account_type': account_type,
                            'is_active': True,
                        }
                    )
                    if created:
                        accounts_created += 1
                        self.stdout.write(f"  Created account: {code} - {name}")
                
                # Create tax configurations
                taxes_created = 0
                for tax_type, rate, effective_date, expiry_date, description in tax_configs:
                    tax_config, created = TaxConfiguration.objects.get_or_create(
                        restaurant=restaurant,
                        tax_type=tax_type,
                        effective_date=effective_date,
                        defaults={
                            'rate_percentage': rate,
                            'expiry_date': expiry_date,
                            'description': description,
                            'is_active': True,
                        }
                    )
                    if created:
                        taxes_created += 1
                        self.stdout.write(f"  Created tax config: {tax_type} - {rate}%")
                
                # Create current fiscal year (Nepal runs from Shrawan to Ashadh)
                # For 2024, fiscal year is 2081/82 BS (approx July 2024 to July 2025)
                current_year = date.today().year
                bs_year_offset = 56  # Approximate difference between AD and BS
                
                fiscal_year_bs = f"{current_year + bs_year_offset}/{(current_year + bs_year_offset + 1) % 100:02d}"
                fiscal_year_ad = f"{current_year}/{(current_year + 1) % 100:02d}"
                
                fiscal_year, created = FiscalYear.objects.get_or_create(
                    restaurant=restaurant,
                    year_bs=fiscal_year_bs,
                    defaults={
                        'year_ad': fiscal_year_ad,
                        'start_date_bs': date(current_year, 7, 16),  # Approximate Shrawan 1
                        'end_date_bs': date(current_year + 1, 7, 15),  # Approximate Ashadh end
                        'start_date_ad': date(current_year, 7, 16),
                        'end_date_ad': date(current_year + 1, 7, 15),
                        'is_active': True,
                        'is_closed': False,
                    }
                )
                if created:
                    self.stdout.write(f"  Created fiscal year: {fiscal_year_bs}")
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Completed {restaurant.name}: "
                        f"{accounts_created} accounts, {taxes_created} tax configs"
                    )
                )
        
        self.stdout.write(self.style.SUCCESS("Accounting initialization completed!"))
