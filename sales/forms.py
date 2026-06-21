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
    price_at_sale = DecimalField('Unit Price', validators=[DataRequired(), NumberRange(min=0)])

class SaleForm(FlaskForm):
    items = FieldList(FormField(SaleItemForm), min_entries=1, max_entries=20)
    sale_date = DateField('Sale Date', validators=[DataRequired()])
    customer_id = SelectField('Customer', coerce=str, validators=[Optional()])
    customer_name = StringField('Customer Name (optional)', validators=[Optional(), Length(max=100)])
    submit = SubmitField('Record Sale') 