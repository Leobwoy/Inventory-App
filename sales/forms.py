from datetime import date

from flask_wtf import FlaskForm
from wtforms import SelectField, IntegerField, DecimalField, DateField, SubmitField, StringField, TextAreaField, FieldList, FormField
from wtforms.validators import DataRequired, NumberRange, Optional, Length

class CustomerForm(FlaskForm):
    name = StringField('Customer Name', validators=[DataRequired(), Length(max=100)])
    phone = StringField('Phone', validators=[Optional(), Length(max=50)])
    email = StringField('Email', validators=[Optional(), Length(max=100)])
    address = TextAreaField('Address', validators=[Optional()])
    submit = SubmitField('Save Customer')

class SaleItemForm(FlaskForm):
    product_id = SelectField('Product', coerce=str, validators=[DataRequired()])
    quantity = IntegerField('Quantity', validators=[DataRequired(), NumberRange(min=1)])
    # Optional: the server resolves the price from the product and treats anything
    # submitted here as a request, subject to the discount policy (F-07).
    price_at_sale = DecimalField('Unit Price', validators=[Optional(), NumberRange(min=0)])
    # Which unit the quantity and price above are in. The server re-decides it
    # against the plan and the product, exactly as the purchase order does -
    # this only says what was asked for.
    sell_unit = SelectField('Sold by', coerce=str, default='base',
                            choices=[('base', 'Single'), ('purchase', 'Carton')],
                            validators=[Optional()])

class SaleForm(FlaskForm):
    items = FieldList(FormField(SaleItemForm), min_entries=1, max_entries=20)
    # `date.today`, not `date.today()`: called per form, not once when this
    # module is imported. A server that stays up for a week would otherwise
    # keep offering the day it started on.
    #
    # It needs a default at all because DataRequired renders `required`, so the
    # browser refused to submit until someone picked today's date by hand -
    # on a page used sixty times a day, from a phone.
    sale_date = DateField('Sale Date', default=date.today, validators=[DataRequired()])
    customer_id = SelectField('Customer', coerce=str, validators=[Optional()])
    customer_name = StringField('Customer Name (optional)', validators=[Optional(), Length(max=100)])
    # A walk-in buying on credit has no customer record to hold a number, and a
    # debt you cannot phone is a debt you do not collect.
    customer_phone = StringField('Phone (optional)', validators=[Optional(), Length(max=50)])

    # Wholesale runs on credit, so how the sale was settled is part of recording
    # it. 'paid' writes a payment for the full amount; 'partial' writes whatever
    # was handed over; 'credit' writes none and the sale sits on the ageing report.
    settlement = SelectField('Payment', coerce=str, default='paid', validators=[Optional()],
                             choices=[('paid', 'Paid in full'),
                                      ('partial', 'Part payment'),
                                      ('credit', 'On credit')])
    amount_paid = DecimalField('Amount received', places=2,
                               validators=[Optional(), NumberRange(min=0)])
    payment_method = SelectField('Method', coerce=str, default='cash', validators=[Optional()],
                                 choices=[('cash', 'Cash'), ('momo', 'Mobile Money'),
                                          ('bank', 'Bank transfer'), ('cheque', 'Cheque')])
    payment_reference = StringField('Reference', validators=[Optional(), Length(max=120)])
    submit = SubmitField('Record Sale') 