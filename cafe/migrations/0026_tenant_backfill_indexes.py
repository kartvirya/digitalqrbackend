from django.db import migrations, models


def backfill_restaurant_links(apps, schema_editor):
    Staff = apps.get_model('cafe', 'Staff')
    Department = apps.get_model('cafe', 'Department')
    Role = apps.get_model('cafe', 'Role')
    User = apps.get_model('cafe', 'User')

    for staff in Staff.objects.filter(restaurant__isnull=True).select_related('user', 'department', 'role'):
        restaurant = None
        if staff.user_id:
            user = User.objects.filter(id=staff.user_id).first()
            if user:
                restaurant = user.restaurant
        if not restaurant and staff.department_id:
            restaurant = getattr(staff.department, 'restaurant', None)
        if not restaurant and staff.role_id:
            restaurant = getattr(staff.role, 'restaurant', None)
        if restaurant:
            staff.restaurant_id = restaurant.id
            staff.save(update_fields=['restaurant'])

    for department in Department.objects.filter(restaurant__isnull=True):
        staff_member = Staff.objects.filter(department_id=department.id, restaurant__isnull=False).first()
        if staff_member:
            department.restaurant_id = staff_member.restaurant_id
            department.save(update_fields=['restaurant'])

    for role in Role.objects.filter(restaurant__isnull=True):
        staff_member = Staff.objects.filter(role_id=role.id, restaurant__isnull=False).first()
        if staff_member:
            role.restaurant_id = staff_member.restaurant_id
            role.save(update_fields=['restaurant'])


class Migration(migrations.Migration):

    dependencies = [
        ('cafe', '0025_subscription_models'),
    ]

    operations = [
        migrations.RunPython(backfill_restaurant_links, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name='order',
            index=models.Index(fields=['restaurant', 'status'], name='order_rest_status_idx'),
        ),
        migrations.AddIndex(
            model_name='bill',
            index=models.Index(fields=['restaurant', 'bill_time'], name='bill_rest_time_idx'),
        ),
        migrations.AddIndex(
            model_name='staff',
            index=models.Index(fields=['restaurant', 'employment_status'], name='staff_rest_emp_idx'),
        ),
    ]

