"""Temporary passwords, and the only way an account is currently recovered.

There is no self-service reset yet: sending email needs a provider, an API key
and ideally a domain, none of which this project has paid for (F-43). What exists
instead is a person who can already be trusted doing it by hand — an Owner for
their own staff, and the vendor for an Owner who is locked out of everything.

A reset reveals nothing about the old password and does not sign anyone in. It
writes a new random one, hands it to the person performing the reset exactly
once, and marks the account so `auth.enforce_password_change` holds the holder on
the change-password page until they have replaced it. The person doing the reset
therefore knows the password for as long as it takes to relay it, and not after.

Both callers go through `reset()`. Two implementations of "make a temporary
password" would drift, and the one that drifted would be the console — used
rarely, under pressure, by someone whose customer is currently locked out.
"""
import secrets

from werkzeug.security import generate_password_hash

from services import audit

#: Deliberately unambiguous. This gets read down a phone line or typed from a
#: WhatsApp message, so every character that is mistakable for another is gone:
#: no O or 0, no I or l or 1, no S or 5, no B or 8, no Z or 2. Uppercase only,
#: because mixed case is the other thing that goes wrong when dictating.
ALPHABET = 'ACDEFGHJKMNPQRTUVWXY34679'

GROUP_SIZE = 4
GROUPS = 3


def temporary_password():
    """A readable one-time password, e.g. `K7MQ-P4RT-9XVA`.

    Twelve characters from a 25-symbol alphabet is about 55 bits, which is far
    more than a password that survives one sign-in needs, and short enough to
    read out without losing your place.
    """
    chars = [secrets.choice(ALPHABET) for _ in range(GROUP_SIZE * GROUPS)]
    return '-'.join(''.join(chars[i:i + GROUP_SIZE])
                    for i in range(0, len(chars), GROUP_SIZE))


def reset(user, by=None):
    """Give `user` a new temporary password. Returns it in plain text, once.

    Does not commit — the caller owns the transaction.

    `by` names a platform admin when the reset comes from the vendor console. It
    changes who the audit entry is attributed to: a console reset is signed by
    nobody inside the business (`user_id=None`), because nobody inside the
    business did it. Attributing it to whichever tenant session happened to exist
    would credit a customer with a decision they did not make.

    Either way the entry is written into **the tenant's own activity log**, on
    purpose. Someone with the power to take over any account in the system should
    leave a mark the account's owner can see.
    """
    password = temporary_password()
    user.password_hash = generate_password_hash(password)
    # The gate does the rest. Without this the reset would hand out a password
    # that works indefinitely, which is worse than the lockout it fixes.
    user.must_change_password = True

    if by is None:
        audit.log('user.password_reset', entity_type='user', entity_id=user.id,
                  email=user.email)
    else:
        audit.log('user.password_reset', entity_type='user', entity_id=user.id,
                  business_id=user.business_id, user_id=None,
                  email=user.email, by=by, source='platform_console')

    return password
