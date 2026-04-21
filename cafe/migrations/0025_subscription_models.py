from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('cafe', '0024_staff_operational_access'),
    ]

    operations = [
        migrations.CreateModel(
            name='SubscriptionPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.SlugField(max_length=40, unique=True)),
                ('name', models.CharField(max_length=120)),
                ('billing_cycle', models.CharField(choices=[('monthly', 'Monthly'), ('yearly', 'Yearly')], default='monthly', max_length=20)),
                ('price', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('currency', models.CharField(default='INR', max_length=10)),
                ('max_staff', models.IntegerField(default=20)),
                ('max_monthly_orders', models.IntegerField(default=1000)),
                ('modules', models.JSONField(blank=True, default=dict)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['name']},
        ),
        migrations.CreateModel(
            name='RestaurantSubscription',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('trialing', 'Trialing'), ('active', 'Active'), ('past_due', 'Past Due'), ('suspended', 'Suspended'), ('cancelled', 'Cancelled')], default='trialing', max_length=20)),
                ('trial_ends_at', models.DateTimeField(blank=True, null=True)),
                ('current_period_start', models.DateTimeField(blank=True, null=True)),
                ('current_period_end', models.DateTimeField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('plan', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='subscriptions', to='cafe.subscriptionplan')),
                ('restaurant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='subscriptions', to='cafe.restaurant')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='TenantUsageSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('month_key', models.CharField(help_text='YYYY-MM', max_length=7)),
                ('orders_count', models.IntegerField(default=0)),
                ('active_staff_count', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('restaurant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='usage_snapshots', to='cafe.restaurant')),
            ],
            options={'ordering': ['-month_key'], 'unique_together': {('restaurant', 'month_key')}},
        ),
    ]

