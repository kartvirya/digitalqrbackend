"""
Payment processing views for subscription billing
Handles eSewa and Khalti payment gateway integrations
"""

import json
import logging
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.views import View
from django.shortcuts import get_object_or_404
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import Restaurant, BillingInvoice, BillingTransaction, RestaurantSubscription
from ..services.payment_gateways import PaymentGatewayService
from ..permissions import IsSuperAdminOrOwner

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
class PaymentInitiationView(View):
    """Handle payment initiation requests"""
    
    def post(self, request):
        """Initiate payment for an invoice"""
        try:
            # Parse request data
            data = json.loads(request.body)
            invoice_id = data.get('invoice_id')
            gateway = data.get('gateway')
            return_url = data.get('return_url')
            
            if not invoice_id or not gateway:
                return JsonResponse({
                    'success': False,
                    'error': 'Missing invoice_id or gateway'
                }, status=400)
            
            # Get invoice
            invoice = get_object_or_404(BillingInvoice, id=invoice_id)
            
            # Check permissions
            if not request.user.is_superuser and invoice.restaurant != request.user.restaurant:
                return JsonResponse({
                    'success': False,
                    'error': 'Permission denied'
                }, status=403)
            
            # Check invoice status
            if invoice.status == 'paid':
                return JsonResponse({
                    'success': False,
                    'error': 'Invoice already paid'
                }, status=400)
            
            # Initialize payment gateway service
            payment_service = PaymentGatewayService()
            
            # Create payment request
            payment_request = payment_service.create_payment_request(
                invoice=invoice,
                gateway=gateway,
                return_url=return_url,
                customer_name=invoice.restaurant.name,
                customer_email=invoice.restaurant.email,
                customer_phone=invoice.restaurant.phone,
            )
            
            if 'payment_url' in payment_request:
                return JsonResponse({
                    'success': True,
                    'payment_url': payment_request['payment_url'],
                    'method': payment_request.get('method', 'GET'),
                    'data': payment_request.get('data', {}),
                    'transaction_id': payment_request.get('transaction_uuid') or payment_request.get('pidx'),
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': payment_request.get('error', 'Payment initiation failed')
                }, status=500)
                
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid JSON data'
            }, status=400)
        except Exception as e:
            logger.error(f"Payment initiation error: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': 'Internal server error'
            }, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class PaymentVerificationView(View):
    """Handle payment verification callbacks"""
    
    def post(self, request, gateway):
        """Verify payment completion"""
        try:
            # Get payment data based on gateway
            if gateway.lower() == 'esewa':
                payment_data = {
                    'amt': request.POST.get('amt'),
                    'txAmt': request.POST.get('txAmt'),
                    'psc': request.POST.get('psc'),
                    'pdc': request.POST.get('pdc'),
                    'tAmt': request.POST.get('tAmt'),
                    'pid': request.POST.get('pid'),
                    'scd': request.POST.get('scd'),
                }
            elif gateway.lower() == 'khalti':
                payment_data = json.loads(request.body)
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Unsupported payment gateway'
                }, status=400)
            
            # Initialize payment gateway service
            payment_service = PaymentGatewayService()
            
            # Verify payment
            verification_result = payment_service.verify_payment(gateway, payment_data)
            
            if verification_result['success']:
                # Find invoice by transaction ID
                transaction_id = verification_result['transaction_id']
                
                # Try to find invoice from payment data
                invoice = None
                if gateway.lower() == 'esewa':
                    # Extract invoice ID from PID
                    pid = payment_data.get('pid', '')
                    if pid.startswith('TXN-'):
                        invoice_id = pid.split('-')[1]
                        try:
                            invoice = BillingInvoice.objects.get(id=invoice_id)
                        except BillingInvoice.DoesNotExist:
                            pass
                elif gateway.lower() == 'khalti':
                    # Extract invoice ID from purchase_order_id
                    purchase_order_id = payment_data.get('purchase_order_id', '')
                    if purchase_order_id.startswith('KTX-'):
                        invoice_id = purchase_order_id.split('-')[1]
                        try:
                            invoice = BillingInvoice.objects.get(id=invoice_id)
                        except BillingInvoice.DoesNotExist:
                            pass
                
                if not invoice:
                    return JsonResponse({
                        'success': False,
                        'error': 'Invoice not found'
                    }, status=404)
                
                # Process payment
                transaction = payment_service.process_payment_success(
                    invoice=invoice,
                    gateway=gateway,
                    payment_data=payment_data
                )
                
                return JsonResponse({
                    'success': True,
                    'transaction_id': transaction.id,
                    'invoice_id': invoice.id,
                    'amount': float(transaction.amount),
                    'status': transaction.status,
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': verification_result.get('error', 'Payment verification failed')
                }, status=400)
                
        except Exception as e:
            logger.error(f"Payment verification error: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': 'Internal server error'
            }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def payment_gateways_view(request):
    """Get available payment gateways"""
    try:
        payment_service = PaymentGatewayService()
        gateways = payment_service.get_available_gateways()
        
        return Response({
            'success': True,
            'gateways': gateways
        })
    except Exception as e:
        logger.error(f"Error getting payment gateways: {str(e)}")
        return Response({
            'success': False,
            'error': 'Failed to get payment gateways'
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSuperAdminOrOwner])
def invoice_payment_status_view(request, invoice_id):
    """Get payment status for an invoice"""
    try:
        invoice = get_object_or_404(BillingInvoice, id=invoice_id)
        
        # Check permissions
        if not request.user.is_superuser and invoice.restaurant != request.user.restaurant:
            return Response({
                'success': False,
                'error': 'Permission denied'
            }, status=403)
        
        # Get latest transaction
        latest_transaction = invoice.transactions.order_by('-created_at').first()
        
        response_data = {
            'success': True,
            'invoice_id': invoice.id,
            'status': invoice.status,
            'total_amount': float(invoice.total_amount),
            'due_date': invoice.due_date.isoformat() if invoice.due_date else None,
            'paid_at': invoice.paid_at.isoformat() if invoice.paid_at else None,
            'payment_data': invoice.payment_data or {},
        }
        
        if latest_transaction:
            response_data.update({
                'latest_transaction': {
                    'id': latest_transaction.id,
                    'gateway': latest_transaction.gateway,
                    'transaction_id': latest_transaction.transaction_id,
                    'amount': float(latest_transaction.amount),
                    'status': latest_transaction.status,
                    'created_at': latest_transaction.created_at.isoformat(),
                    'error_message': latest_transaction.error_message,
                }
            })
        
        return Response(response_data)
        
    except Exception as e:
        logger.error(f"Error getting invoice payment status: {str(e)}")
        return Response({
            'success': False,
            'error': 'Failed to get payment status'
        }, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSuperAdminOrOwner])
def retry_payment_view(request, invoice_id):
    """Retry payment for an invoice"""
    try:
        invoice = get_object_or_404(BillingInvoice, id=invoice_id)
        
        # Check permissions
        if not request.user.is_superuser and invoice.restaurant != request.user.restaurant:
            return Response({
                'success': False,
                'error': 'Permission denied'
            }, status=403)
        
        # Check if invoice can be retried
        if invoice.status == 'paid':
            return Response({
                'success': False,
                'error': 'Invoice already paid'
            }, status=400)
        
        gateway = request.data.get('gateway')
        if not gateway:
            return Response({
                'success': False,
                'error': 'Gateway is required'
            }, status=400)
        
        # Initialize payment gateway service
        payment_service = PaymentGatewayService()
        
        # Create new payment request
        payment_request = payment_service.create_payment_request(
            invoice=invoice,
            gateway=gateway,
            return_url=request.data.get('return_url'),
            customer_name=invoice.restaurant.name,
            customer_email=invoice.restaurant.email,
            customer_phone=invoice.restaurant.phone,
        )
        
        if 'payment_url' in payment_request:
            return Response({
                'success': True,
                'payment_url': payment_request['payment_url'],
                'method': payment_request.get('method', 'GET'),
                'data': payment_request.get('data', {}),
                'transaction_id': payment_request.get('transaction_uuid') or payment_request.get('pidx'),
            })
        else:
            return Response({
                'success': False,
                'error': payment_request.get('error', 'Payment initiation failed')
            }, status=500)
            
    except Exception as e:
        logger.error(f"Error retrying payment: {str(e)}")
        return Response({
            'success': False,
            'error': 'Failed to retry payment'
        }, status=500)


# Payment callback URLs (for eSewa/Khalti redirects)
@require_http_methods(["GET", "POST"])
@csrf_exempt
def esewa_success_view(request):
    """Handle eSewa success callback"""
    try:
        # Extract payment data
        payment_data = {
            'amt': request.GET.get('amt') or request.POST.get('amt'),
            'txAmt': request.GET.get('txAmt') or request.POST.get('txAmt'),
            'psc': request.GET.get('psc') or request.POST.get('psc'),
            'pdc': request.GET.get('pdc') or request.POST.get('pdc'),
            'tAmt': request.GET.get('tAmt') or request.POST.get('tAmt'),
            'pid': request.GET.get('pid') or request.POST.get('pid'),
            'scd': request.GET.get('scd') or request.POST.get('scd'),
        }
        
        # Process payment verification
        verification_view = PaymentVerificationView()
        response = verification_view.post(request, 'esewa')
        
        if response.status_code == 200:
            response_data = json.loads(response.content)
            if response_data.get('success'):
                # Redirect to success page
                return HttpResponse(f"""
                    <html>
                        <head><title>Payment Successful</title></head>
                        <body>
                            <h2>Payment Successful!</h2>
                            <p>Transaction ID: {response_data.get('transaction_id')}</p>
                            <p>Amount: NPR {response_data.get('amount')}</p>
                            <p>You will be redirected shortly...</p>
                            <script>
                                setTimeout(() => {{
                                    window.location.href = '{settings.FRONTEND_URL}/billing/success?invoice_id={response_data.get("invoice_id")}';
                                }}, 3000);
                            </script>
                        </body>
                    </html>
                """)
        
        # Handle failure
        return HttpResponse(f"""
            <html>
                <head><title>Payment Failed</title></head>
                <body>
                    <h2>Payment Failed</h2>
                    <p>There was an issue processing your payment. Please try again.</p>
                    <script>
                        setTimeout(() => {{
                            window.location.href = '{settings.FRONTEND_URL}/billing/failed';
                        }}, 3000);
                    </script>
                </body>
            </html>
        """)
        
    except Exception as e:
        logger.error(f"eSewa success callback error: {str(e)}")
        return HttpResponse("Payment verification failed", status=500)


@require_http_methods(["GET", "POST"])
@csrf_exempt
def esewa_failure_view(request):
    """Handle eSewa failure callback"""
    return HttpResponse(f"""
        <html>
            <head><title>Payment Cancelled</title></head>
            <body>
                <h2>Payment Cancelled</h2>
                <p>You have cancelled the payment. You can try again anytime.</p>
                <script>
                    setTimeout(() => {{
                        window.location.href = '{settings.FRONTEND_URL}/billing/cancelled';
                    }}, 3000);
                </script>
            </body>
        </html>
    """)
