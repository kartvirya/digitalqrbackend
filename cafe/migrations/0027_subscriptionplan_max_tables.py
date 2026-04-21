from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cafe', '0026_tenant_backfill_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='subscriptionplan',
            name='max_tables',
            field=models.IntegerField(default=50),
        ),
    ]

