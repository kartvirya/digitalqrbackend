from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('cafe', '0028_seed_default_subscription_plans'),
    ]

    operations = [
        migrations.AddField(
            model_name='restaurant',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='restaurant',
            name='lifecycle_status',
            field=models.CharField(
                choices=[('active', 'Active'), ('suspended', 'Suspended'), ('archived', 'Archived'), ('terminated', 'Terminated')],
                default='active',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='restaurant',
            name='terminated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name='BillingInvoice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('invoice_number', models.CharField(max_length=40, unique=True)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('currency', models.CharField(default='INR', max_length=10)),
                ('due_date', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(choices=[('pending_payment', 'Pending Payment'), ('paid', 'Paid'), ('failed', 'Failed'), ('void', 'Void')], default='pending_payment', max_length=20)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('plan', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='billing_invoices', to='cafe.subscriptionplan')),
                ('restaurant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='billing_invoices', to='cafe.restaurant')),
                ('subscription', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='billing_invoices', to='cafe.restaurantsubscription')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='PlatformAuditLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(max_length=80)),
                ('target_type', models.CharField(blank=True, default='', max_length=40)),
                ('target_id', models.CharField(blank=True, default='', max_length=50)),
                ('before_state', models.JSONField(blank=True, default=dict)),
                ('after_state', models.JSONField(blank=True, default=dict)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='platform_audit_logs', to=settings.AUTH_USER_MODEL)),
                ('restaurant', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='platform_audit_logs', to='cafe.restaurant')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='BillingTransaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('gateway', models.CharField(default='esewa', max_length=20)),
                ('status', models.CharField(choices=[('initiated', 'Initiated'), ('success', 'Success'), ('failed', 'Failed')], default='initiated', max_length=20)),
                ('gateway_reference', models.CharField(blank=True, max_length=120, null=True)),
                ('request_payload', models.JSONField(blank=True, default=dict)),
                ('response_payload', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('invoice', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='transactions', to='cafe.billinginvoice')),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]
