# -*- coding: utf-8 -*-
"""
    __init__.py

    :copyright: (c) 2015 by Fulfil.IO Inc.
    :license: see LICENSE for details.
"""
from trytond.pool import Pool
from party import Address, PaymentProfile, Party
from transaction import PaymentGatewayBraintree, PaymentTransactionBraintree, \
    AddPaymentProfile, TransactionLog


def register():
    Pool.register(
        Address,
        PaymentProfile,
        PaymentGatewayBraintree,
        PaymentTransactionBraintree,
        Party,
        TransactionLog,
        module='payment_gateway_braintree', type_='model'
    )
    Pool.register(
        AddPaymentProfile,
        module='payment_gateway_braintree', type_='wizard'
    )
