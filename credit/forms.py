from decimal import Decimal

from flask_wtf import FlaskForm
from wtforms import DateField, DecimalField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import InputRequired, Length, NumberRange, Optional

from credit.models import PAYMENT_METHODS


class PaymentForm(FlaskForm):
    amount = DecimalField('Amount received', places=2,
                          validators=[InputRequired(), NumberRange(min=Decimal('0.01'))])
    method = SelectField('How was it paid?', choices=PAYMENT_METHODS, default='momo')
    # The MoMo transaction ID the customer forwards, or a cheque/bank reference.
    reference = StringField('Reference', validators=[Optional(), Length(max=120)],
                            description='Mobile money transaction ID, cheque or bank reference.')
    paid_on = DateField('Date received', validators=[InputRequired()])
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Record payment')
