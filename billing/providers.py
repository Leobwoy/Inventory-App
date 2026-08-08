"""How a payment gets from a customer to a confirmed subscription.

Every payment provider answers exactly one question - *did this money actually
arrive?* - and everything downstream of that answer is identical. So the answer
is the only thing that varies here.

Two implementations are anticipated:

- **ManualMomoProvider** (now). The customer sends mobile money straight to the
  platform's own MoMo wallet and types the transaction ID they were given. A
  human checks it against their own statement and confirms.

- **PaystackProvider** (later). Paystack calls a webhook, signed with the secret
  key, and the server verifies the signature and the amount.

Manual is not a stopgap chosen out of poverty, though that is how it started.
**Mobile money in Ghana cannot do recurring charges** - there is no reusable
authorisation the way there is for a card - so even a fully automated Paystack
integration needs the customer to actively pay again every month. The only
thing automation buys is who presses confirm. That is worth 1.95% eventually.
It is not worth blocking every customer on a company registration today.

The rule that makes this safe: **a customer's reference is a claim, never
proof.** Nothing is activated until someone with the money in front of them
says it arrived.
"""
import os


class PaymentProvider:
    """The shape every provider fills in."""

    code = None
    #: True when the provider confirms payments itself, without a human.
    automatic = False

    def instructions(self, plan, cycle):
        """What to show the customer so they can pay. Returns a dict."""
        raise NotImplementedError

    def verify(self, transaction, evidence):
        """Decide whether `transaction` has really been paid.

        Returns (confirmed, message). A provider that cannot answer on its own
        returns (False, reason) and leaves the transaction pending for a human.
        """
        raise NotImplementedError


class ManualMomoProvider(PaymentProvider):
    """Mobile money paid directly to the platform's wallet.

    The wallet details come from the environment, never the repository: it is a
    personal number in a public repo otherwise, and it changes without a deploy.
    """

    code = 'manual_momo'
    automatic = False

    @property
    def number(self):
        return os.environ.get('MOMO_NUMBER', '').strip()

    @property
    def account_name(self):
        return os.environ.get('MOMO_NAME', '').strip()

    @property
    def network(self):
        return os.environ.get('MOMO_NETWORK', 'MTN').strip()

    @property
    def configured(self):
        """Without a number there is nothing to tell the customer to pay."""
        return bool(self.number and self.account_name)

    def instructions(self, plan, cycle):
        price = plan.price_annual_ghs if cycle == 'annual' else plan.price_monthly_ghs
        return {
            'network': self.network,
            'number': self.number,
            'account_name': self.account_name,
            'amount': price,
            'cycle': cycle,
            'plan': plan,
        }

    def verify(self, transaction, evidence):
        """Always defers. A typed transaction ID is a claim about a payment,
        not the payment - anyone can type one. Only the wallet's own record
        settles it, and that is read by a person."""
        return False, 'Awaiting confirmation against the mobile money statement.'


#: Registered providers, by code.
PROVIDERS = {
    ManualMomoProvider.code: ManualMomoProvider(),
}

#: What new checkouts use. Becomes 'paystack' once a merchant account exists.
ACTIVE_PROVIDER = ManualMomoProvider.code


def active():
    return PROVIDERS[ACTIVE_PROVIDER]


def get(code):
    return PROVIDERS.get(code)
