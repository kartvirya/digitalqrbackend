"""
Payment gateway integration services for Nepal
Supports eSewa and Khalti payment methods for subscription billing
"""

import json
import hashlib
import requests
from datetime import datetime, timedelta
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from ..models import Restaurant, RestaurantSubscription, BillingInvoice, BillingTransaction


class BasePaymentGateway:
    """Base class for payment gateway integrations"""
    
    def __init__(self, config: dict):
        self.config = config
        self.test_mode = config.get('test_mode', True)
    
    def generate_signature(self, data: dict) -> str:
        """Generate signature for payment requests"""
        raise NotImplementedError
    
    def verify_signature(self, data: dict, signature: str) -> bool:
        """Verify payment response signature"""
        raise NotImplementedError
    
    def create_payment_request(self, invoice: BillingInvoice, **kwargs) -> dict:
        """Create payment request for invoice"""
        raise NotImplementedError
    
    def verify_payment(self, payment_data: dict) -> dict:
        """Verify payment completion"""
        raise NotImplementedError


class EsewaPaymentGateway(BasePaymentGateway):
    """eSewa payment gateway integration"""
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.merchant_code = config.get('merchant_code')
        self.merchant_secret = config.get('merchant_secret')
        self.success_url = config.get('success_url')
        self.failure_url = config.get('failure_url')
        
        # eSewa endpoints
        if self.test_mode:
            self.api_url = "https://uat.esewa.com.np/epay/main"
            self.verify_url = "https://uat.esewa.com.np/epay/transrec"
        else:
            self.api_url = "https://esewa.com.np/epay/main"
            self.verify_url = "https://esewa.com.np/epay/transrec"
    
    def generate_signature(self, data: dict) -> str:
        """Generate eSewa signature"""
        # eSewa uses a specific format for signature generation
        amount = str(data.get('amount', ''))
        product_code = self.merchant_code
        transaction_uuid = data.get('transaction_uuid', '')
        
        # Create signature string
        signature_string = f"{amount}:{product_code}:{transaction_uuid}"
        signature = hashlib.sha256(signature_string.encode()).hexdigest()
        
        return signature
    
    def create_payment_request(self, invoice: BillingInvoice, **kwargs) -> dict:
        """Create eSewa payment request"""
        if not self.merchant_code or not self.merchant_secret:
            raise ValueError("eSewa merchant credentials not configured")
        
        # Generate unique transaction ID
        transaction_uuid = f"TXN-{invoice.id}-{int(datetime.now().timestamp())}"
        
        # Prepare payment data
        payment_data = {
            'amt': float(invoice.total_amount),
            'txAmt': float(invoice.total_amount),  # Transaction amount (same as total for eSewa)
            'psc': 0,  # Service charge (0 for subscriptions)
            'pdc': 0,  # Delivery charge (0 for subscriptions)
            'tAmt': float(invoice.total_amount),  # Total amount
            'pid': transaction_uuid,  # Product ID
            'scd': self.merchant_code,  # Service/merchant code
            'su': self.success_url,  # Success URL
            'fu': self.failure_url,  # Failure URL
        }
        
        # Store payment data for verification
        invoice.payment_data = {
            'gateway': 'esewa',
            'transaction_uuid': transaction_uuid,
            'amount': float(invoice.total_amount),
            'created_at': timezone.now().isoformat(),
        }
        invoice.save(update_fields=['payment_data'])
        
        return {
            'payment_url': self.api_url,
            'method': 'POST',
            'data': payment_data,
            'transaction_uuid': transaction_uuid,
        }
    
    def verify_payment(self, payment_data: dict) -> dict:
        """Verify eSewa payment"""
        try:
            # Extract payment parameters
            amt = payment_data.get('amt')
            txAmt = payment_data.get('txAmt')
            psc = payment_data.get('psc')
            pdc = payment_data.get('pdc')
            tAmt = payment_data.get('tAmt')
            pid = payment_data.get('pid')
            scd = payment_data.get('scd')
            
            # Prepare verification request
            verify_data = {
                'amt': amt,
                'txAmt': txAmt,
                'psc': psc,
                'pdc': pdc,
                'tAmt': tAmt,
                'pid': pid,
                'scd': scd,
            }
            
            # Make verification request
            response = requests.post(self.verify_url, data=verify_data)
            response_text = response.text.strip()
            
            # Parse response
            if response_text.lower() == 'success':
                return {
                    'success': True,
                    'transaction_id': pid,
                    'amount': Decimal(amt),
                    'verified_at': timezone.now(),
                    'response_data': payment_data,
                }
            else:
                return {
                    'success': False,
                    'error': response_text,
                    'response_data': payment_data,
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'response_data': payment_data,
            }


class KhaltiPaymentGateway(BasePaymentGateway):
    """Khalti payment gateway integration"""
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.merchant_id = config.get('merchant_id')
        self.secret_key = config.get('secret_key')
        self.public_key = config.get('public_key')
        
        # Khalti endpoints
        if self.test_mode:
            self.initiate_url = "https://a.khalti.com/api/v2/epayment/initiate/"
            self.verify_url = "https://a.khalti.com/api/v2/epayment/lookup/"
        else:
            self.initiate_url = "https://khalti.com/api/v2/epayment/initiate/"
            self.verify_url = "https://khalti.com/api/v2/epayment/lookup/"
    
    def generate_signature(self, data: dict) -> str:
        """Generate Khalti signature"""
        # Khalti uses HMAC-SHA256 with secret key
        import hmac
        
        # Create signature string (sorted keys)
        signature_string = json.dumps(data, sort_keys=True, separators=(',', ':'))
        signature = hmac.new(
            self.secret_key.encode(),
            signature_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return signature
    
    def create_payment_request(self, invoice: BillingInvoice, **kwargs) -> dict:
        """Create Khalti payment request"""
        if not self.merchant_id or not self.secret_key:
            raise ValueError("Khalti merchant credentials not configured")
        
        # Generate unique transaction ID
        transaction_uuid = f"KTX-{invoice.id}-{int(datetime.now().timestamp())}"
        
        # Prepare payment data
        payment_data = {
            'return_url': kwargs.get('return_url', f"{settings.FRONTEND_URL}/payment/success"),
            'website_url': settings.FRONTEND_URL,
            'amount': int(float(invoice.total_amount) * 100),  # Khalti uses amount in paisa
            'purchase_order_id': transaction_uuid,
            'purchase_order_name': f"Subscription - {invoice.restaurant.name}",
            'customer_info': {
                'name': kwargs.get('customer_name', invoice.restaurant.name),
                'email': kwargs.get('customer_email', invoice.restaurant.email),
                'phone': kwargs.get('customer_phone', invoice.restaurant.phone),
            }
        }
        
        # Add merchant ID
        payment_data['merchant_id'] = self.merchant_id
        
        # Store payment data for verification
        invoice.payment_data = {
            'gateway': 'khalti',
            'transaction_uuid': transaction_uuid,
            'amount': float(invoice.total_amount),
            'amount_paisa': int(float(invoice.total_amount) * 100),
            'created_at': timezone.now().isoformat(),
        }
        invoice.save(update_fields=['payment_data'])
        
        try:
            # Make initiation request
            headers = {
                'Authorization': f'Key {self.secret_key}',
                'Content-Type': 'application/json',
            }
            
            response = requests.post(
                self.initiate_url,
                json=payment_data,
                headers=headers
            )
            
            if response.status_code == 200:
                response_data = response.json()
                if response_data.get('success'):
                    return {
                        'payment_url': response_data.get('payment_url'),
                        'method': 'GET',
                        'pidx': response_data.get('pidx'),
                        'transaction_uuid': transaction_uuid,
                        'expires_at': response_data.get('expires_at'),
                    }
                else:
                    return {
                        'success': False,
                        'error': response_data.get('message', 'Payment initiation failed'),
                    }
            else:
                return {
                    'success': False,
                    'error': f'HTTP {response.status_code}: {response.text}',
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
            }
    
    def verify_payment(self, payment_data: dict) -> dict:
        """Verify Khalti payment"""
        try:
            pidx = payment_data.get('pidx')
            if not pidx:
                return {
                    'success': False,
                    'error': 'Missing payment index (pidx)',
                }
            
            # Make verification request
            headers = {
                'Authorization': f'Key {self.secret_key}',
                'Content-Type': 'application/json',
            }
            
            response = requests.post(
                f"{self.verify_url}{pidx}",
                headers=headers
            )
            
            if response.status_code == 200:
                response_data = response.json()
                
                if response_data.get('status') == 'Completed':
                    return {
                        'success': True,
                        'transaction_id': response_data.get('idx'),
                        'amount': Decimal(response_data.get('total_amount', 0)) / 100,  # Convert from paisa
                        'verified_at': timezone.now(),
                        'response_data': response_data,
                    }
                else:
                    return {
                        'success': False,
                        'error': f"Payment status: {response_data.get('status')}",
                        'response_data': response_data,
                    }
            else:
                return {
                    'success': False,
                    'error': f'HTTP {response.status_code}: {response.text}',
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
            }


class PaymentGatewayService:
    """Service for managing payment gateway operations"""
    
    def __init__(self):
        self.esewa_config = {
            'merchant_code': getattr(settings, 'ESEWA_MERCHANT_CODE', ''),
            'merchant_secret': getattr(settings, 'ESEWA_MERCHANT_SECRET', ''),
            'success_url': getattr(settings, 'ESEWA_SUCCESS_URL', ''),
            'failure_url': getattr(settings, 'ESEWA_FAILURE_URL', ''),
            'test_mode': getattr(settings, 'ESEWA_TEST_MODE', True),
        }
        
        self.khalti_config = {
            'merchant_id': getattr(settings, 'KHALTI_MERCHANT_ID', ''),
            'secret_key': getattr(settings, 'KHALTI_SECRET_KEY', ''),
            'public_key': getattr(settings, 'KHALTI_PUBLIC_KEY', ''),
            'test_mode': getattr(settings, 'KHALTI_TEST_MODE', True),
        }
        
        self.esewa_gateway = EsewaPaymentGateway(self.esewa_config)
        self.khalti_gateway = KhaltiPaymentGateway(self.khalti_config)
    
    def get_gateway(self, gateway_name: str) -> BasePaymentGateway:
        """Get payment gateway instance"""
        if gateway_name.lower() == 'esewa':
            return self.esewa_gateway
        elif gateway_name.lower() == 'khalti':
            return self.khalti_gateway
        else:
            raise ValueError(f"Unsupported payment gateway: {gateway_name}")
    
    def create_payment_request(self, invoice: BillingInvoice, gateway: str, **kwargs) -> dict:
        """Create payment request for invoice"""
        payment_gateway = self.get_gateway(gateway)
        return payment_gateway.create_payment_request(invoice, **kwargs)
    
    def verify_payment(self, gateway: str, payment_data: dict) -> dict:
        """Verify payment completion"""
        payment_gateway = self.get_gateway(gateway)
        return payment_gateway.verify_payment(payment_data)
    
    def process_payment_success(self, invoice: BillingInvoice, gateway: str, payment_data: dict) -> BillingTransaction:
        """Process successful payment and create transaction record"""
        verification_result = self.verify_payment(gateway, payment_data)
        
        if verification_result['success']:
            # Create transaction record
            transaction = BillingTransaction.objects.create(
                invoice=invoice,
                gateway=gateway,
                transaction_id=verification_result['transaction_id'],
                amount=verification_result['amount'],
                status='completed',
                gateway_data=verification_result['response_data'],
                created_at=verification_result['verified_at'],
            )
            
            # Update invoice status
            invoice.status = 'paid'
            invoice.paid_at = verification_result['verified_at']
            invoice.save(update_fields=['status', 'paid_at'])
            
            # Update subscription if applicable
            if invoice.subscription:
                subscription = invoice.subscription
                subscription.status = 'active'
                subscription.paid_until = subscription.paid_until + timedelta(days=30)  # Monthly subscription
                subscription.save(update_fields=['status', 'paid_until'])
            
            return transaction
        else:
            # Create failed transaction record
            transaction = BillingTransaction.objects.create(
                invoice=invoice,
                gateway=gateway,
                amount=invoice.total_amount,
                status='failed',
                gateway_data=verification_result,
                error_message=verification_result.get('error', 'Payment verification failed'),
            )
            
            return transaction
    
    def get_available_gateways(self) -> list:
        """Get list of available payment gateways"""
        gateways = []
        
        if self.esewa_config.get('merchant_code') and self.esewa_config.get('merchant_secret'):
            gateways.append({
                'name': 'esewa',
                'display_name': 'eSewa',
                'description': 'Pay with eSewa wallet',
                'logo_url': '/static/images/esewa-logo.png',
            })
        
        if self.khalti_config.get('merchant_id') and self.khalti_config.get('secret_key'):
            gateways.append({
                'name': 'khalti',
                'display_name': 'Khalti',
                'description': 'Pay with Khalti wallet',
                'logo_url': '/static/images/khalti-logo.png',
            })
        
        return gateways
