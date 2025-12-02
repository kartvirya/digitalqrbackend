from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from cafe.models import HRDepartment, HRPosition, Employee
from datetime import date, datetime
import random

User = get_user_model()

class Command(BaseCommand):
    help = 'Populate HR system with sample data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing HR data before populating',
        )

    def handle(self, *args, **options):
        if options['clear']:
            self.stdout.write('Clearing existing HR data...')
            Employee.objects.all().delete()
            HRPosition.objects.all().delete()
            HRDepartment.objects.all().delete()
            self.stdout.write(self.style.SUCCESS('Cleared existing HR data'))

        # Create Departments
        departments_data = [
            {'name': 'Kitchen', 'description': 'Food preparation and cooking'},
            {'name': 'Service', 'description': 'Customer service and table management'},
            {'name': 'Management', 'description': 'Restaurant management and administration'},
            {'name': 'Cleaning', 'description': 'Cleaning and maintenance'},
            {'name': 'Security', 'description': 'Security and safety'},
        ]

        departments = []
        for dept_data in departments_data:
            dept, created = HRDepartment.objects.get_or_create(
                name=dept_data['name'],
                defaults={'description': dept_data['description']}
            )
            departments.append(dept)
            if created:
                self.stdout.write(f'Created department: {dept.name}')

        # Create Positions
        positions_data = [
            # Kitchen positions
            {'name': 'Head Chef', 'department': 'Kitchen', 'salary_min': 60000, 'salary_max': 80000},
            {'name': 'Sous Chef', 'department': 'Kitchen', 'salary_min': 40000, 'salary_max': 60000},
            {'name': 'Line Cook', 'department': 'Kitchen', 'salary_min': 25000, 'salary_max': 35000},
            {'name': 'Prep Cook', 'department': 'Kitchen', 'salary_min': 20000, 'salary_max': 30000},
            
            # Service positions
            {'name': 'Restaurant Manager', 'department': 'Management', 'salary_min': 50000, 'salary_max': 70000},
            {'name': 'Assistant Manager', 'department': 'Management', 'salary_min': 35000, 'salary_max': 50000},
            {'name': 'Head Waiter', 'department': 'Service', 'salary_min': 30000, 'salary_max': 40000},
            {'name': 'Waiter', 'department': 'Service', 'salary_min': 18000, 'salary_max': 25000},
            {'name': 'Hostess', 'department': 'Service', 'salary_min': 18000, 'salary_max': 25000},
            
            # Other positions
            {'name': 'Cleaner', 'department': 'Cleaning', 'salary_min': 15000, 'salary_max': 20000},
            {'name': 'Security Guard', 'department': 'Security', 'salary_min': 20000, 'salary_max': 30000},
        ]

        positions = []
        for pos_data in positions_data:
            dept = next(d for d in departments if d.name == pos_data['department'])
            pos, created = HRPosition.objects.get_or_create(
                name=pos_data['name'],
                department=dept,
                defaults={
                    'salary_range_min': pos_data['salary_min'],
                    'salary_range_max': pos_data['salary_max'],
                }
            )
            positions.append(pos)
            if created:
                self.stdout.write(f'Created position: {pos.name} in {dept.name}')

        # Sample employee data
        employees_data = [
            {
                'employee_id': 'EMP001',
                'personnel_number': 'PER001',
                'first_name': 'Rajesh',
                'last_name': 'Kumar',
                'email': 'rajesh.kumar@restaurant.com',
                'phone': '9876543210',
                'gender': 'male',
                'date_of_birth': '1985-06-15',
                'hire_date': '2020-01-15',
                'position': 'Head Chef',
                'department': 'Kitchen',
                'base_salary': 65000,
                'current_salary': 70000,
                'address': '123 Main Street, Mumbai, Maharashtra, 400001',
                'emergency_contact_name': 'Priya Kumar',
                'emergency_contact_phone': '9876543211',
                'password': 'rajesh123'
            },
            {
                'employee_id': 'EMP002',
                'personnel_number': 'PER002',
                'first_name': 'Priya',
                'last_name': 'Sharma',
                'email': 'priya.sharma@restaurant.com',
                'phone': '9876543212',
                'gender': 'female',
                'date_of_birth': '1992-03-22',
                'hire_date': '2021-05-10',
                'position': 'Restaurant Manager',
                'department': 'Management',
                'base_salary': 55000,
                'current_salary': 60000,
                'address': '456 Park Avenue, Mumbai, Maharashtra, 400002',
                'emergency_contact_name': 'Vikram Sharma',
                'emergency_contact_phone': '9876543213',
                'password': 'priya123'
            },
            {
                'employee_id': 'EMP003',
                'personnel_number': 'PER003',
                'first_name': 'Amit',
                'last_name': 'Patel',
                'email': 'amit.patel@restaurant.com',
                'phone': '9876543214',
                'gender': 'male',
                'date_of_birth': '1988-09-10',
                'hire_date': '2019-11-01',
                'position': 'Sous Chef',
                'department': 'Kitchen',
                'base_salary': 45000,
                'current_salary': 50000,
                'address': '789 Restaurant Lane, Mumbai, Maharashtra, 400003',
                'emergency_contact_name': 'Neha Patel',
                'emergency_contact_phone': '9876543215',
                'password': 'amit123'
            },
            {
                'employee_id': 'EMP004',
                'personnel_number': 'PER004',
                'first_name': 'Sneha',
                'last_name': 'Gupta',
                'email': 'sneha.gupta@restaurant.com',
                'phone': '9876543216',
                'gender': 'female',
                'date_of_birth': '1995-12-05',
                'hire_date': '2022-02-20',
                'position': 'Head Waiter',
                'department': 'Service',
                'base_salary': 32000,
                'current_salary': 35000,
                'address': '321 Service Street, Mumbai, Maharashtra, 400004',
                'emergency_contact_name': 'Rahul Gupta',
                'emergency_contact_phone': '9876543217',
                'password': 'sneha123'
            },
            {
                'employee_id': 'EMP005',
                'personnel_number': 'PER005',
                'first_name': 'Ravi',
                'last_name': 'Singh',
                'email': 'ravi.singh@restaurant.com',
                'phone': '9876543218',
                'gender': 'male',
                'date_of_birth': '1990-07-18',
                'hire_date': '2021-08-15',
                'position': 'Waiter',
                'department': 'Service',
                'base_salary': 20000,
                'current_salary': 22000,
                'address': '654 Waiter Way, Mumbai, Maharashtra, 400005',
                'emergency_contact_name': 'Sunita Singh',
                'emergency_contact_phone': '9876543219',
                'password': 'ravi123'
            }
        ]

        # Create employees
        for emp_data in employees_data:
            if User.objects.filter(phone=emp_data['phone']).exists():
                self.stdout.write(f'User with phone {emp_data["phone"]} already exists, skipping...')
                continue

            # Find position and department
            position = next(p for p in positions if p.name == emp_data['position'])
            department = next(d for d in departments if d.name == emp_data['department'])

            # Create user account
            user = User.objects.create_user(
                phone=emp_data['phone'],
                password=emp_data['password']
            )

            # Create employee
            employee = Employee.objects.create(
                user=user,
                employee_id=emp_data['employee_id'],
                personnel_number=emp_data['personnel_number'],
                first_name=emp_data['first_name'],
                last_name=emp_data['last_name'],
                email=emp_data['email'],
                phone=emp_data['phone'],
                gender=emp_data['gender'],
                date_of_birth=datetime.strptime(emp_data['date_of_birth'], '%Y-%m-%d').date(),
                hire_date=datetime.strptime(emp_data['hire_date'], '%Y-%m-%d').date(),
                position=position,
                department=department,
                base_salary=emp_data['base_salary'],
                current_salary=emp_data['current_salary'],
                address=emp_data['address'],
                emergency_contact_name=emp_data['emergency_contact_name'],
                emergency_contact_phone=emp_data['emergency_contact_phone'],
                employment_status='active'
            )

            self.stdout.write(f'Created employee: {employee.full_name} ({employee.employee_id})')

        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully populated HR data:\n'
                f'- {HRDepartment.objects.count()} departments\n'
                f'- {HRPosition.objects.count()} positions\n'
                f'- {Employee.objects.count()} employees'
            )
        )
