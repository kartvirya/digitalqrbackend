from django.db import migrations


class Migration(migrations.Migration):
    """
    Remove the 'username' field from User model state.
    The PostgreSQL database was originally created without a username column
    (the initial migration didn't include it), so we only update the ORM state
    without touching the database schema.
    """

    dependencies = [
        ('cafe', '0033_add_audit_log'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name='user',
                    name='username',
                ),
            ],
            database_operations=[],
        ),
    ]
