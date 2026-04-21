from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cafe', '0023_staff_rbac_order_inventory'),
    ]

    operations = [
        migrations.AddField(
            model_name='staff',
            name='operational_access',
            field=models.CharField(
                choices=[
                    ('auto', 'From role title (waiter/chef keywords)'),
                    ('waiter', 'Take orders & tables (waiter)'),
                    ('kitchen_chef', 'Kitchen queue'),
                    ('none', 'No waiter/kitchen portal access'),
                ],
                default='auto',
                help_text='Controls waiter/kitchen Django groups for the staff portal.',
                max_length=20,
            ),
        ),
    ]
