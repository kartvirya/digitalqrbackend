"""
Management command to migrate existing data to multi-tenant structure.
Creates a default restaurant and assigns all existing data to it.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from cafe.models import (
    Restaurant, User, Floor, Table, Room, menu_item, order, bill,
    Department, Role, Staff, Attendance, Leave,
    HRDepartment, HRPosition, Employee, EmployeeDocument, Payroll,
    LeaveRequest, PerformanceReview, Training, TrainingEnrollment
)


class Command(BaseCommand):
    help = 'Migrate existing data to multi-tenant structure by creating a default restaurant'

    def add_arguments(self, parser):
        parser.add_argument(
            '--restaurant-name',
            type=str,
            default='Default Restaurant',
            help='Name for the default restaurant'
        )
        parser.add_argument(
            '--restaurant-slug',
            type=str,
            default='default',
            help='Slug for the default restaurant'
        )
        parser.add_argument(
            '--create-super-admin',
            action='store_true',
            help='Create a super admin user'
        )
        parser.add_argument(
            '--super-admin-phone',
            type=str,
            default='9999999999',
            help='Phone number for super admin'
        )
        parser.add_argument(
            '--super-admin-password',
            type=str,
            default='admin123',
            help='Password for super admin'
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting multi-tenant migration...'))

        # Create default restaurant
        restaurant_name = options['restaurant_name']
        restaurant_slug = options['restaurant_slug']

        restaurant, created = Restaurant.objects.get_or_create(
            slug=restaurant_slug,
            defaults={
                'name': restaurant_name,
                'is_active': True,
                'subscription_status': 'active',
            }
        )

        if created:
            self.stdout.write(self.style.SUCCESS(f'Created default restaurant: {restaurant.name}'))
        else:
            self.stdout.write(self.style.WARNING(f'Restaurant with slug "{restaurant_slug}" already exists. Using existing restaurant.'))

        # Migrate all models to default restaurant
        self.migrate_model(Floor, restaurant, 'floors')
        self.migrate_model(Table, restaurant, 'tables')
        self.migrate_model(Room, restaurant, 'rooms')
        self.migrate_model(menu_item, restaurant, 'menu items')
        self.migrate_model(order, restaurant, 'orders')
        self.migrate_model(bill, restaurant, 'bills')
        self.migrate_model(Department, restaurant, 'departments')
        self.migrate_model(Role, restaurant, 'roles')
        self.migrate_model(Staff, restaurant, 'staff')
        self.migrate_model(HRDepartment, restaurant, 'HR departments')
        self.migrate_model(HRPosition, restaurant, 'HR positions')
        self.migrate_model(Employee, restaurant, 'employees')

        # Update users with cafe_manager flag to be restaurant admins
        cafe_managers = User.objects.filter(cafe_manager=True, restaurant__isnull=True)
        updated_count = cafe_managers.update(restaurant=restaurant)
        if updated_count > 0:
            self.stdout.write(self.style.SUCCESS(f'Updated {updated_count} cafe managers to restaurant admins'))

        # Create super admin if requested
        if options['create_super_admin']:
            super_admin_phone = options['super_admin_phone']
            super_admin_password = options['super_admin_password']

            super_admin, created = User.objects.get_or_create(
                phone=super_admin_phone,
                defaults={
                    'is_super_admin': True,
                    'is_superuser': True,
                    'is_staff': True,
                }
            )

            if created:
                super_admin.set_password(super_admin_password)
                super_admin.save()
                self.stdout.write(self.style.SUCCESS(f'Created super admin: {super_admin_phone}'))
            else:
                super_admin.is_super_admin = True
                super_admin.is_superuser = True
                super_admin.is_staff = True
                super_admin.set_password(super_admin_password)
                super_admin.save()
                self.stdout.write(self.style.SUCCESS(f'Updated existing user to super admin: {super_admin_phone}'))

        self.stdout.write(self.style.SUCCESS('Migration completed successfully!'))

    def migrate_model(self, model_class, restaurant, model_name):
        """Migrate a model's records to the default restaurant"""
        # Get all records without a restaurant
        records = model_class.objects.filter(restaurant__isnull=True)
        count = records.count()

        if count > 0:
            updated = records.update(restaurant=restaurant)
            self.stdout.write(self.style.SUCCESS(f'Migrated {updated} {model_name} to {restaurant.name}'))
        else:
            self.stdout.write(self.style.WARNING(f'No {model_name} to migrate'))

