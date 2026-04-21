from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Restaurant, SubscriptionPlan, RestaurantSubscription, menu_item, Floor, Table, TenantUsageSnapshot


class TenantIsolationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_model = get_user_model()
        self.restaurant_a = Restaurant.objects.create(name='A Cafe', slug='a-cafe')
        self.restaurant_b = Restaurant.objects.create(name='B Cafe', slug='b-cafe')
        self.user_a = self.user_model.objects.create_user(
            phone='9000000001',
            password='pass1234',
            restaurant=self.restaurant_a,
            cafe_manager=True,
        )
        menu_item.objects.create(
            restaurant=self.restaurant_a,
            name='A Pasta',
            category='Main',
            description='A',
            price='100.00',
        )
        menu_item.objects.create(
            restaurant=self.restaurant_b,
            name='B Pasta',
            category='Main',
            description='B',
            price='110.00',
        )

    def test_menu_list_is_tenant_scoped_for_restaurant_admin(self):
        self.client.force_login(self.user_a)
        response = self.client.get('/api/menu/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]['name'], 'A Pasta')


class SubscriptionGuardTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_model = get_user_model()
        self.restaurant = Restaurant.objects.create(
            name='Suspended Cafe',
            slug='suspended-cafe',
            is_active=False,
            subscription_status='suspended',
        )
        self.user = self.user_model.objects.create_user(
            phone='9000000002',
            password='pass1234',
            restaurant=self.restaurant,
            cafe_manager=True,
        )

    def test_write_request_blocked_when_tenant_suspended(self):
        self.client.force_login(self.user)
        response = self.client.post('/api/orders/', {}, format='json')
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.json()['code'], 'subscription_inactive')

    def test_plan_limit_guard_blocks_order_creation(self):
        self.restaurant.is_active = True
        self.restaurant.subscription_status = 'active'
        self.restaurant.save(update_fields=['is_active', 'subscription_status'])

        plan = SubscriptionPlan.objects.create(
            code='starter_limit_guard',
            name='Starter',
            max_monthly_orders=0,
            max_staff=100,
        )
        RestaurantSubscription.objects.create(
            restaurant=self.restaurant,
            plan=plan,
            status='active',
            is_active=True,
        )

        self.client.force_login(self.user)
        response = self.client.post('/api/orders/', {}, format='json')
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()['limit_type'], 'max_monthly_orders')


class TenantBootstrapAndSuperAdminTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_model = get_user_model()
        self.super_admin = self.user_model.objects.create_user(
            phone='9000000003',
            password='pass1234',
            is_super_admin=True,
            role='super_admin',
            is_staff=True,
        )

    def test_restaurant_bootstrap_creates_defaults(self):
        restaurant = Restaurant.objects.create(name='Bootstrap Cafe', slug='bootstrap-cafe')
        self.assertTrue(RestaurantSubscription.objects.filter(restaurant=restaurant, is_active=True).exists())
        self.assertTrue(TenantUsageSnapshot.objects.filter(restaurant=restaurant).exists())
        self.assertTrue(Floor.objects.filter(restaurant=restaurant).exists())
        self.assertEqual(Table.objects.filter(restaurant=restaurant).count(), 4)

    def test_super_admin_can_assign_plan_and_suspend(self):
        restaurant = Restaurant.objects.create(name='Ops Cafe', slug='ops-cafe')
        paid_plan = SubscriptionPlan.objects.create(
            code='pro_superadmin_test',
            name='Pro',
            max_monthly_orders=2000,
            max_staff=50,
            max_tables=120,
        )
        self.client.force_login(self.super_admin)
        assign_resp = self.client.post(
            f'/api/super-admin/{restaurant.id}/assign_plan/',
            {'plan_id': paid_plan.id, 'status': 'active'},
            format='json',
        )
        self.assertEqual(assign_resp.status_code, 201)
        restaurant.refresh_from_db()
        self.assertEqual(restaurant.subscription_status, 'active')

        suspend_resp = self.client.post(f'/api/super-admin/{restaurant.id}/suspend_tenant/', {}, format='json')
        self.assertEqual(suspend_resp.status_code, 200)
        restaurant.refresh_from_db()
        self.assertFalse(restaurant.is_active)
