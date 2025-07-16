from django.db import models


class PaymentManager(models.Manager):
    def create_payment(self):
        pass

    def sync_offline_payment(self):
        pass
