"""
Management command to migrate to role-based system and merge Staff into Employee
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from cafe.models import (
    User, Staff, Employee, Restaurant, Department, Role,
    HRDepartment, HRPosition, Attendance, Leave, Permission, RolePermission
)


class Command(BaseCommand):
    help = 'Migrate to role-based system: set user roles, migrate Staff to Employee, create permissions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--skip-staff-migration',
            action='store_true',
            help='Skip Staff to Employee migration',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting role-based system migration...'))

        # 1. Create default permissions
        self.create_permissions()

        # 2. Set user roles based on existing flags
        self.migrate_user_roles()

        # 3. Migrate Staff to Employee (if not skipped)
        if not options['skip_staff_migration']:
            self.migrate_staff_to_employee()

        # 4. Assign default permissions to roles
        self.assign_default_permissions()

        self.stdout.write(self.style.SUCCESS('Role-based system migration completed successfully!'))

    def create_permissions(self):
        """Create standard permissions"""
        permissions_data = [
            # Restaurant management
            ('Manage Restaurants', 'manage_restaurants', 'restaurant', 'Can create, update, and delete restaurants'),
            # Menu management
            ('Manage Menu Items', 'manage_menu', 'menu', 'Can create, update, and delete menu items'),
            # Table/Room management
            ('Manage Tables', 'manage_tables', 'tables', 'Can manage restaurant tables'),
            ('Manage Rooms', 'manage_rooms', 'tables', 'Can manage hotel rooms'),
            ('Manage Floors', 'manage_floors', 'tables', 'Can manage floors'),
            # Order management
            ('Manage Orders', 'manage_orders', 'orders', 'Can view and update orders'),
            ('View Orders', 'view_orders', 'orders', 'Can view orders'),
            # Employee management
            ('Manage Employees', 'manage_employees', 'employees', 'Can create, update, and delete employees'),
            ('View Employees', 'view_employees', 'employees', 'Can view employee information'),
            # Payroll management
            ('Manage Payroll', 'manage_payroll', 'payroll', 'Can manage employee payroll'),
            ('View Payroll', 'view_payroll', 'payroll', 'Can view payroll information'),
            # Attendance management
            ('Manage Attendance', 'manage_attendance', 'attendance', 'Can manage employee attendance'),
            ('View Attendance', 'view_attendance', 'attendance', 'Can view attendance records'),
            # Leave management
            ('Manage Leaves', 'manage_leaves', 'leaves', 'Can approve/reject leave requests'),
            ('View Leaves', 'view_leaves', 'leaves', 'Can view leave requests'),
            # Training management
            ('Manage Training', 'manage_training', 'training', 'Can create and manage training programs'),
            ('View Training', 'view_training', 'training', 'Can view training programs'),
            # Performance management
            ('Manage Performance', 'manage_performance', 'performance', 'Can manage performance reviews'),
            ('View Performance', 'view_performance', 'performance', 'Can view performance reviews'),
        ]

        created_count = 0
        for name, codename, category, description in permissions_data:
            permission, created = Permission.objects.get_or_create(
                codename=codename,
                defaults={
                    'name': name,
                    'category': category,
                    'description': description,
                }
            )
            if created:
                created_count += 1

        self.stdout.write(self.style.SUCCESS(f'Created {created_count} permissions'))

    def migrate_user_roles(self):
        """Set user roles based on existing flags"""
        # Super admins
        super_admin_count = User.objects.filter(is_super_admin=True).update(role='super_admin')
        self.stdout.write(f'Updated {super_admin_count} users to super_admin role')

        # Restaurant admins (cafe_manager or has restaurant)
        restaurant_admin_count = User.objects.filter(
            cafe_manager=True
        ).exclude(role='super_admin').update(role='restaurant_admin')
        self.stdout.write(f'Updated {restaurant_admin_count} users to restaurant_admin role')

        # Staff members (have staff_profile)
        staff_count = 0
        for user in User.objects.filter(role='customer'):
            if hasattr(user, 'staff_profile') or hasattr(user, 'employee_profile'):
                user.role = 'staff'
                user.save()
                staff_count += 1
        self.stdout.write(f'Updated {staff_count} users to staff role')

    def migrate_staff_to_employee(self):
        """Migrate Staff records to Employee model"""
        staff_records = Staff.objects.all()
        migrated_count = 0
        skipped_count = 0

        for staff in staff_records:
            # Check if employee already exists for this user
            if hasattr(staff.user, 'employee_profile'):
                self.stdout.write(self.style.WARNING(f'Employee already exists for user {staff.user.phone}, skipping Staff record {staff.id}'))
                skipped_count += 1
                continue

            # Find or create HRDepartment from Department
            hr_department, _ = HRDepartment.objects.get_or_create(
                restaurant=staff.restaurant,
                name=staff.department.name,
                defaults={
                    'description': staff.department.description or '',
                    'is_active': staff.department.is_active,
                }
            )

            # Find or create HRPosition from Role
            hr_position, _ = HRPosition.objects.get_or_create(
                restaurant=staff.restaurant,
                department=hr_department,
                name=staff.role.name,
                defaults={
                    'description': staff.role.description or '',
                    'is_active': staff.role.is_active,
                }
            )

            # Create Employee from Staff
            employee = Employee.objects.create(
                restaurant=staff.restaurant,
                employee_id=staff.employee_id,
                personnel_number=staff.employee_id,  # Use same as employee_id
                user=staff.user,
                first_name=staff.first_name,
                last_name=staff.last_name,
                middle_name='',
                gender=staff.gender,
                date_of_birth=staff.date_of_birth,
                email=staff.email,
                phone=staff.phone,
                address=staff.address,
                city='',
                state='',
                postal_code='',
                country='India',
                position=hr_position,
                department=hr_department,
                hire_date=staff.hire_date,
                termination_date=None,
                employment_status=staff.employment_status,
                base_salary=staff.salary,
                current_salary=staff.salary,
                salary_currency='INR',
                emergency_contact_name=staff.emergency_contact_name,
                emergency_contact_phone=staff.emergency_contact_phone,
                emergency_contact_relationship='',
                profile_picture=staff.profile_picture,
                is_active=staff.is_active,
            )

            # Migrate Attendance records
            for attendance in staff.attendance_records.all():
                attendance.employee = employee
                attendance.save()

            # Migrate Leave records
            for leave in staff.leaves.all():
                leave.employee = employee
                if leave.approved_by:
                    # Try to find corresponding employee for approved_by
                    try:
                        approved_by_employee = Employee.objects.get(user=leave.approved_by.user)
                        leave.approved_by_employee = approved_by_employee
                    except Employee.DoesNotExist:
                        pass
                leave.save()

            # Update user role to staff if not already set
            if staff.user.role == 'customer':
                staff.user.role = 'staff'
                staff.user.save()

            migrated_count += 1

        self.stdout.write(self.style.SUCCESS(f'Migrated {migrated_count} Staff records to Employee'))
        if skipped_count > 0:
            self.stdout.write(self.style.WARNING(f'Skipped {skipped_count} Staff records (Employee already exists)'))

    def assign_default_permissions(self):
        """Assign default permissions to roles"""
        role_permissions = {
            'super_admin': [
                'manage_restaurants', 'manage_menu', 'manage_tables', 'manage_rooms', 'manage_floors',
                'manage_orders', 'view_orders', 'manage_employees', 'view_employees',
                'manage_payroll', 'view_payroll', 'manage_attendance', 'view_attendance',
                'manage_leaves', 'view_leaves', 'manage_training', 'view_training',
                'manage_performance', 'view_performance',
            ],
            'restaurant_admin': [
                'manage_menu', 'manage_tables', 'manage_rooms', 'manage_floors',
                'manage_orders', 'view_orders', 'manage_employees', 'view_employees',
                'manage_payroll', 'view_payroll', 'manage_attendance', 'view_attendance',
                'manage_leaves', 'view_leaves', 'manage_training', 'view_training',
                'manage_performance', 'view_performance',
            ],
            'hr_manager': [
                'manage_employees', 'view_employees', 'manage_payroll', 'view_payroll',
                'manage_attendance', 'view_attendance', 'manage_leaves', 'view_leaves',
                'manage_training', 'view_training', 'manage_performance', 'view_performance',
            ],
            'staff': [
                'view_orders', 'manage_orders', 'view_attendance', 'view_leaves',
            ],
            'customer': [],
        }

        assigned_count = 0
        for role, permission_codenames in role_permissions.items():
            for codename in permission_codenames:
                try:
                    permission = Permission.objects.get(codename=codename)
                    role_permission, created = RolePermission.objects.get_or_create(
                        role=role,
                        permission=permission
                    )
                    if created:
                        assigned_count += 1
                except Permission.DoesNotExist:
                    self.stdout.write(self.style.WARNING(f'Permission {codename} not found, skipping'))

        self.stdout.write(self.style.SUCCESS(f'Assigned {assigned_count} role permissions'))

