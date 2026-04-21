from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import PlatformAuditLog, Restaurant


class TenantLifecycleTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_model = get_user_model()
        self.super_admin = self.user_model.objects.create_user(
            phone='9222222222',
            password='pass1234',
            is_super_admin=True,
            is_staff=True,
            role='super_admin',
        )
        self.restaurant = Restaurant.objects.create(name='Lifecycle Cafe', slug='lifecycle-cafe')
        self.client.force_login(self.super_admin)

    def test_archive_restore_terminate_flow(self):
        archive = self.client.post(f'/api/super-admin/{self.restaurant.id}/archive_tenant/', {}, format='json')
        self.assertEqual(archive.status_code, 200)
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.lifecycle_status, 'archived')

        restore = self.client.post(f'/api/super-admin/{self.restaurant.id}/restore_tenant/', {}, format='json')
        self.assertEqual(restore.status_code, 200)
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.lifecycle_status, 'active')

        terminate = self.client.post(f'/api/super-admin/{self.restaurant.id}/terminate_tenant/', {}, format='json')
        self.assertEqual(terminate.status_code, 200)
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.lifecycle_status, 'terminated')
        self.assertFalse(self.restaurant.is_active)

    def test_actions_are_audited(self):
        self.client.post(f'/api/super-admin/{self.restaurant.id}/archive_tenant/', {}, format='json')
        self.assertTrue(
            PlatformAuditLog.objects.filter(
                restaurant=self.restaurant,
                action='tenant_archive',
            ).exists()
        )
