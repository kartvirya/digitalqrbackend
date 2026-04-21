from abc import ABC, abstractmethod


class BillingProvider(ABC):
    @abstractmethod
    def initiate_payment(self, *, invoice, success_url: str, failure_url: str):
        raise NotImplementedError

    @abstractmethod
    def verify_payment(self, *, transaction, payload):
        raise NotImplementedError
