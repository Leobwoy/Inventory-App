from flask_wtf import FlaskForm
from wtforms import (IntegerField, PasswordField, SelectField, StringField,
                     SubmitField, TextAreaField)
from wtforms.validators import DataRequired, Email, Length, NumberRange, Optional


class PlatformLoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Sign in')


class PaymentActionForm(FlaskForm):
    """One form for confirm and reject; the action is in the URL.

    A POST with CSRF rather than a link, because both outcomes change what a
    business has paid for and a GET would let either happen by someone merely
    following a URL.
    """
    note = TextAreaField('Note', validators=[Optional(), Length(max=500)])
    submit = SubmitField('Go')


class ChangePlanForm(FlaskForm):
    """Putting a business on a plan by hand.

    For what money cannot express: comping an early customer, correcting a
    mistake, extending someone whose payment went astray.
    """
    plan_code = SelectField('Plan', validators=[DataRequired()])
    status = SelectField('Status', choices=[
        ('active', 'Active'), ('trialing', 'Trialing'),
        ('free', 'Free'), ('cancelled', 'Cancelled'),
    ], validators=[DataRequired()])
    days = IntegerField('Paid for how many more days',
                        validators=[Optional(), NumberRange(min=0, max=3650)])
    # Required: a plan changed by hand with no stated reason is indistinguishable
    # later from a mistake.
    reason = StringField('Reason', validators=[DataRequired(), Length(max=200)])
    submit = SubmitField('Apply')
