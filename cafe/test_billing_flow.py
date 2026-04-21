from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import BillingInvoice, BillingTransaction, Restaurant, RestaurantSubscription, SubscriptionPlan


class BillingFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_model = get_user_model()
        self.restaurant = Restaurant.objects.create(name='Billing Cafe', slug='billing-cafe')
        self.plan = SubscriptionPlan.objects.create(
            code='billing-plan',
            name='Billing Plan',
            max_monthly_orders=1000,
            max_staff=20,
            max_tables=20,
            price='1499.00',
            currency='INR',
            modules={'qr_order': True, 'inventory': True, 'hr_system': False},
        )
        self.subscription = RestaurantSubscription.objects.create(
            restaurant=self.restaurant,
            plan=self.plan,
            status='pending_payment',
            is_active=True,
        )
        self.user = self.user_model.objects.create_user(
            phone='9111111111',
            password='pass1234',
            restaurant=self.restaurant,
            cafe_manager=True,
        )

    def test_pay_now_creates_invoice_and_transaction(self):
        self.client.force_login(self.user)
        response = self.client.post(
            f'/api/restaurant-subscriptions/{self.subscription.id}/pay_now/',
            {'success_url': 'http://test/s', 'failure_url': 'http://test/f'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(BillingInvoice.objects.filter(subscription=self.subscription).exists())
        self.assertTrue(BillingTransaction.objects.filter(invoice__subscription=self.subscription).exists())

    def test_verify_payment_marks_subscription_active(self):
        invoice = BillingInvoice.objects.create(
            restaurant=self.restaurant,
            subscription=self.subscription,
            plan=self.plan,
            invoice_number='INV-BILLING-1',
            amount='1499.00',
            currency='INR',
            status='pending_payment',
        )
        tx = BillingTransaction.objects.create(invoice=invoice, gateway='esewa', status='initiated')
        self.client.force_login(self.user)
        response = self.client.post(
            '/api/restaurant-subscriptions/verify_payment/',
            {'transaction_id': tx.id, 'status': 'success'},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.subscription.refresh_from_db()
        invoice.refresh_from_db()
        self.assertEqual(self.subscription.status, 'active')
        self.assertEqual(invoice.status, 'paid')
