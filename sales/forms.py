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

class SaleForm(FlaskForm):
    items = FieldList(FormField(SaleItemForm), min_entries=1, max_entries=20)
    sale_date = DateField('Sale Date', validators=[DataRequired()])
    customer_id = SelectField('Customer', coerce=str, validators=[Optional()])
    customer_name = StringField('Customer Name (optional)', validators=[Optional(), Length(max=100)])

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