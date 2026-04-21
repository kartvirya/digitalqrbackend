from .base import BillingProvider


class EsewaBillingProvider(BillingProvider):
    def initiate_payment(self, *, invoice, success_url: str, failure_url: str):
        tx_ref = f"ESEWA-{invoice.id}"
        payload = {
            "amount": str(invoice.amount),
            "tax_amount": "0",
            "total_amount": str(invoice.amount),
            "transaction_uuid": tx_ref,
            "product_code": "digitalqr_saas",
            "success_url": success_url,
            "failure_url": failure_url,
        }
        return {"transaction_ref": tx_ref, "payload": payload}

    def verify_payment(self, *, transaction, payload):
        status = str(payload.get('status', '')).lower()
        if status in ('complete', 'success', 'paid'):
            return {'success': True, 'status': 'success'}
        return {'success': False, 'status': 'failed'}
