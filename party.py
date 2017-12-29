# -*- coding: utf-8 -*-
"""
    party.py

    :copyright: (c) 2015 by Fulfil.IO Inc.
    :license: see LICENSE for more details.
"""
from trytond.pool import PoolMeta, Pool
from trytond.model import fields
from trytond.rpc import RPC
from trytond.exceptions import UserError

import braintree
from braintree.exceptions.braintree_error import BraintreeError

__metaclass__ = PoolMeta
__all__ = ['Address', 'PaymentProfile', 'Party']


class Address:
    __name__ = 'party.address'

    def get_address_for_braintree(self):
        """
        Return the address as a dictionary for Braintree
        """
        return {
            'first_name': (self.name or '').split(' ', 1)[0],
            'last_name': (self.name or '').rsplit(' ', 1)[-1],
            'street_address': self.street,
            'extended_address': self.streetbis,
            'locality': self.city,
            'postal_code': self.zip,
            'region': self.subdivision and self.subdivision.name,
            'country_code_alpha2': self.country and self.country.code,
        }


class PaymentProfile:
    __name__ = 'party.payment_profile'

    braintree_customer_id = fields.Char(
        'Braintree Customer ID', readonly=True
    )

    @classmethod
    def __setup__(cls):
        super(PaymentProfile, cls).__setup__()
        cls.__rpc__.update({
            'create_profile_using_braintree_token': RPC(
                instantiate=0, readonly=True
            ),
            'update_braintree': RPC(
                instantiate=0, readonly=False
            ),
        })

    def update_braintree(self):
        """
        Update this payment profile on the gateway (braintree)
        """
        assert self.gateway.provider == 'braintree'
        self.gateway.configure_braintree_client()

        try:
            card = braintree.CreditCard.update(
                self.provider_reference,
                {
                    'cardholder_name': self.name or self.party.name,
                    'expiration_month': self.expiry_month,
                    'expiration_year': self.expiry_year,
                    'billing_address': self.address.get_address_for_braintree(),
                }
            )
        except BraintreeError as exc:
            raise UserError(exc)

        if not card.is_success:
            for error in card.errors.deep_errors:
                raise UserError(error.message)

    @classmethod
    def create_profile_using_braintree_token(
        cls, user_id, gateway_id, token, address_id=None
    ):
        """
        Create a Payment Profile using token
        """
        Party = Pool().get('party.party')
        PaymentGateway = Pool().get('payment_gateway.gateway')
        PaymentProfile = Pool().get('party.payment_profile')

        party = Party(user_id)
        gateway = PaymentGateway(gateway_id)
        assert gateway.provider == 'braintree'
        gateway.configure_braintree_client()

        try:
            card = braintree.CreditCard.find(token)
        except BraintreeError as exc:
            raise UserError(exc)
        else:
            profile, = PaymentProfile.create([{
                'name': card.cardholder_name,
                'party': party.id,
                'address': address_id or party.addresses[0].id,
                'gateway': gateway.id,
                'last_4_digits': card.last_4,
                'expiry_month': card.expiration_month,
                'expiry_year': card.expiration_year,
                'provider_reference': card.token,
                'braintree_customer_id': card.customer_id,
            }])

            return profile.id


class Party:
    __name__ = 'party.party'

    def _get_braintree_customer_id(self, gateway):
        """
        Extracts and returns customer id from party's payment profile
        Return None if no customer id is found.

        :param gateway: Payment gateway to which the customer id is associated
        """
        PaymentProfile = Pool().get('party.payment_profile')

        payment_profiles = PaymentProfile.search([
            ('party', '=', self.id),
            ('braintree_customer_id', '!=', None),
            ('gateway', '=', gateway.id),
        ])
        if payment_profiles:
            return payment_profiles[0].braintree_customer_id
        return None

    def get_customer_for_braintree(self):
        return {
            'first_name': (self.name or '').split(' ', 1)[0],
            'last_name': (self.name or '').rsplit(' ', 1)[-1],
            'company': self.name,
            'email': self.email,
            'phone': self.phone,
        }
