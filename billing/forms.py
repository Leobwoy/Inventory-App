from flask_wtf import FlaskForm
from wtforms import RadioField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length


class MomoPaymentForm(FlaskForm):
    """What the customer types after paying.

    The transaction ID is the only field that matters, and it is a *claim*: it
    is checked against the wallet's own statement by a person before anything is
    activated. Free text because every network formats it differently and the
    reader is a human comparing two strings.
    """
    cycle = RadioField('Billing cycle', choices=[('monthly', 'Monthly'), ('annual', 'Annual')],
                       default='monthly')
    reference = StringField('Mobile money transaction ID',
                            validators=[DataRequired(), Length(min=4, max=120)])
    payer_note = StringField('Which number did you pay from?', validators=[Length(max=120)])
    submit = SubmitField('I have paid')


class ConfirmPaymentForm(FlaskForm):
    """Platform-side. Deliberately a POST form with CSRF rather than a link -
    confirming a payment grants a paid plan, and a GET would let it happen by
    someone following a URL."""
    note = TextAreaField('Note', validators=[Length(max=500)])
    submit = SubmitField('Confirm')


class RejectPaymentForm(FlaskForm):
    reason = StringField('Reason', validators=[DataRequired(), Length(max=200)])
    submit = SubmitField('Reject')
