# -*- coding: utf-8 -*-
"""
    transaction.py

    :copyright: (c) 2015 by Fulfil.IO Inc.
    :license: see LICENSE for more details.
"""
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, Bool, Not
from trytond.model import fields
from trytond.exceptions import UserError

import braintree
from braintree.exceptions.braintree_error import BraintreeError

__metaclass__ = PoolMeta
__all__ = [
    'PaymentGatewayBraintree', 'PaymentTransactionBraintree',
    'AddPaymentProfile', 'TransactionLog'
]


class PaymentGatewayBraintree:
    "Braintree Gateway Implementation"
    __name__ = 'payment_gateway.gateway'

    braintree_api_key = fields.Char(
        'Braintree API Key', states={
            'required': Eval('provider') == 'braintree',
            'invisible': Eval('provider') != 'braintree',
            'readonly': Not(Bool(Eval('active'))),
        }, depends=['provider', 'active']
    )
    braintree_merchant_id = fields.Char(
        'Braintree Merchant ID', states={
            'required': Eval('provider') == 'braintree',
            'invisible': Eval('provider') != 'braintree',
            'readonly': Not(Bool(Eval('active'))),
        }, depends=['provider', 'active']
    )
    braintree_currency = fields.Many2One(
        'currency.currency', 'Currency', states={
            'required': Eval('provider') == 'braintree',
            'invisible': Eval('provider') != 'braintree',
            'readonly': Not(Bool(Eval('active'))),
        }, depends=['provider', 'active'],
        help="Braintree needs separate merchant ids for each currency"
    )
    braintree_public_key = fields.Char(
        'Braintree Public Key', states={
            'required': Eval('provider') == 'braintree',
            'invisible': Eval('provider') != 'braintree',
            'readonly': Not(Bool(Eval('active'))),
        }, depends=['provider', 'active']
    )

    @classmethod
    def get_providers(cls, values=None):
        """
        Downstream modules can add to the list
        """
        rv = super(PaymentGatewayBraintree, cls).get_providers()
        braintree_record = ('braintree', 'Braintree')
        if braintree_record not in rv:
            rv.append(braintree_record)
        return rv

    def get_methods(self):
        if self.provider == 'braintree':
            return [
                ('credit_card', 'Credit Card - Braintree'),
            ]
        return super(PaymentGatewayBraintree, self).get_methods()

    @classmethod
    def view_attributes(cls):
        return super(PaymentGatewayBraintree, cls).view_attributes() + [(
            '//notebook/page[@id="braintree"]', 'states', {
                'invisible': Eval('provider') != 'braintree'
            }
        )]

    def configure_braintree_client(self):
        assert self.provider == 'braintree'
        if self.test:
            environment = braintree.Environment.Sandbox
        else:
            environment = braintree.Environment.Production
        braintree.Configuration.configure(
            environment,
            merchant_id=self.braintree_merchant_id,
            public_key=self.braintree_public_key,
            private_key=self.braintree_api_key,
        )


class PaymentTransactionBraintree:
    """
    Payment Transaction implementation for Braintree
    """
    __name__ = 'payment_gateway.transaction'

    def authorize_braintree(self, card_info=None):
        """
        Authorize using Braintree.
        """
        TransactionLog = Pool().get('payment_gateway.transaction.log')

        self.gateway.configure_braintree_client()

        charge_data = self.get_braintree_charge_data(card_info=card_info)
        # charge_data['todo'] = 'auth_%s' % self.uuid
        charge_data['options']['submit_for_settlement'] = False

        try:
            charge = braintree.Transaction.sale(charge_data)
        except BraintreeError as exc:
            self.state = 'failed'
            self.save()
            TransactionLog.serialize_and_create(self, exc)
        else:
            if charge.is_success:
                self.state = 'authorized'
                self.provider_reference = charge.transaction.id
            else:
                self.state = 'failed'
                TransactionLog.log_braintree_errors(self, charge)
            self.save()

    def settle_braintree(self):
        """
        Settle an authorized charge
        """
        TransactionLog = Pool().get('payment_gateway.transaction.log')

        assert self.state == 'authorized'

        self.gateway.configure_braintree_client()

        try:
            charge = braintree.Transaction.submit_for_settlement(
                self.provider_reference,
                self.amount
            )
        except BraintreeError as exc:
            self.state = 'failed'
            self.save()
            TransactionLog.serialize_and_create(self, exc)
        else:
            if charge.is_success:
                self.state = 'completed'
                self.provider_reference = charge.transaction.id
            else:
                self.state = 'failed'
                TransactionLog.log_braintree_errors(self, charge)
            self.save()
            self.safe_post()

    def capture_braintree(self, card_info=None):
        """
        Capture using Braintree.
        """
        TransactionLog = Pool().get('payment_gateway.transaction.log')

        self.gateway.configure_braintree_client()

        charge_data = self.get_braintree_charge_data(card_info=card_info)
        # charge_data['todo'] = 'capture_%s' % self.uuid
        charge_data['options']['submit_for_settlement'] = True
        try:
            charge = braintree.Transaction.sale(charge_data)
        except BraintreeError as exc:
            self.state = 'failed'
            self.save()
            TransactionLog.serialize_and_create(self, exc)
        else:
            if charge.is_success:
                self.state = 'completed'
                self.provider_reference = charge.transaction.id
            else:
                self.state = 'failed'
                TransactionLog.log_braintree_errors(self, charge)
            self.save()
            self.safe_post()

    def get_braintree_charge_data(self, card_info=None):
        """
        Downstream modules can modify this method to send extra data to
        braintree
        """
        charge_data = {
            "amount": self.amount,
            "options": {},
            "customer": {},
        }
        assert self.currency == self.gateway.braintree_currency

        if card_info:
            charge_data['credit_card'] = {
                'number': card_info.number,
                'expiration_month': card_info.expiry_month,
                'expiration_year': card_info.expiry_year,
                'cvv': card_info.csc,
                'cardholder_name': (
                    card_info.owner or
                    self.address.name or
                    self.party.name
                )[:175]
            }
            charge_data['billing'] = self.address.get_address_for_braintree()   # noqa
        elif self.payment_profile:
            charge_data['payment_method_token'] = self.payment_profile.provider_reference
        else:
            self.raise_user_error('no_card_or_profile')

        customer_id = self.party._get_braintree_customer_id(
            self.gateway
        )
        if not customer_id:
            charge_data['customer'] = self.party.get_customer_for_braintree()

        return charge_data

    def retry_braintree(self, credit_card=None):
        """
        Retry charge

        :param credit_card: An instance of CreditCardView
        """
        raise self.raise_user_error('feature_not_available')

    def update_braintree(self):
        """
        Update the status of the transaction from Braintree
        """
        raise self.raise_user_error('feature_not_available')

    def cancel_braintree(self):
        """
        Cancel this authorization or request
        """
        TransactionLog = Pool().get('payment_gateway.transaction.log')

        if self.state != 'authorized':
            self.raise_user_error('cancel_only_authorized')

        self.gateway.configure_braintree_client()

        try:
            charge = braintree.Transaction.void(self.provider_reference)
        except BraintreeError as exc:
            TransactionLog.serialize_and_create(self, exc)
        else:
            if charge.is_success:
                self.state = 'cancel'
                self.save()
            else:
                TransactionLog.log_braintree_errors(self, charge)

    def refund_braintree(self):
        TransactionLog = Pool().get('payment_gateway.transaction.log')

        self.gateway.configure_braintree_client()

        try:
            original_txn = braintree.Transaction.find(
                self.origin.provider_reference
            )
            if original_txn.status not in ('settled', 'settling') \
                    and original_txn.amount == self.amount:
                # Refunds can only be done on settled payments. before that
                # braintree required you to void. Since voiding can only be
                # done on full amount, we support voiding when the refund
                # amount is for the same amount as original transaction
                refund = braintree.Transaction.void(
                    self.origin.provider_reference
                )
            else:
                refund = braintree.Transaction.refund(
                    self.origin.provider_reference,
                    self.amount,
                )
        except BraintreeError as exc:
            self.state = 'failed'
            self.save()
            TransactionLog.serialize_and_create(self, exc)
        else:
            if refund.is_success:
                self.provider_reference = refund.transaction.id
                self.state = 'completed'
                self.save()
            else:
                TransactionLog.log_braintree_errors(self, refund)
            self.safe_post()


class AddPaymentProfile:
    """
    Add a payment profile
    """
    __name__ = 'party.party.payment_profile.add'

    def transition_add_braintree(self):
        """
        Handle the case if the profile should be added for Braintree
        """
        card_info = self.card_info

        card_info.gateway.configure_braintree_client()

        card_data = {
            'number': card_info.number,
            'expiration_month': card_info.expiry_month,
            'expiration_year': card_info.expiry_year,
            'cvv': card_info.csc,
            'cardholder_name': (
                card_info.owner or self.address.name or self.party.name
            ),
            'billing_address': card_info.address.get_address_for_braintree(),
        }

        customer_id = card_info.party._get_braintree_customer_id(
            card_info.gateway
        )
        if customer_id:
            card_data['customer_id'] = customer_id
        else:
            customer = braintree.Customer.create(
                card_info.party.get_customer_for_braintree()
            ).customer
            card_data['customer_id'] = customer.id

        try:
            card = braintree.CreditCard.create(card_data)
        except BraintreeError as exc:
            raise UserError(exc)

        if not card.is_success:
            for error in card.errors.deep_errors:
                raise UserError(error.message)

        return self.create_profile(
            card.credit_card.token,
            braintree_customer_id=card.credit_card.customer_id
        )


class TransactionLog:
    "Braintree Gateway Implementation"
    __name__ = 'payment_gateway.transaction.log'

    @classmethod
    def log_braintree_errors(cls, transaction, result):
        text = [result.message]
        for error in result.errors.deep_errors:
            text.append(error.message)
        print text
        return cls.create([{
            'transaction': transaction,
            'log': '\r\n'.join(text),
            'is_system_generated': True,
        }])
