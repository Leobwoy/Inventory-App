from datetime import date

from flask_wtf import FlaskForm
from wtforms import SelectField, IntegerField, DecimalField, StringField, DateField, SubmitField, FieldList, FormField
from wtforms.validators import DataRequired, NumberRange, Optional

class PurchaseOrderItemForm(FlaskForm):
    product_id = SelectField('Product', coerce=int, validators=[DataRequired()])
    quantity_ordered = IntegerField('Quantity Ordered', validators=[DataRequired(), NumberRange(min=1)])
    # There is no order_unit field any more. It asked a question with one
    # answer: stock arrives in crates and cartons, so an order for a product
    # with a pack is placed in packs. purchases/routes.py derives it, and a
    # value posted by hand cannot change what a line means.
    unit_cost = DecimalField('Unit Cost', validators=[DataRequired(), NumberRange(min=0)])

class PurchaseOrderForm(FlaskForm):
    supplier_id = SelectField('Supplier', coerce=int, validators=[Optional()])
    # The callable, not date.today(): evaluated per form rather than once at
    # import. Without a default DataRequired renders `required`, and the browser
    # silently refuses to submit until someone types today's date by hand.
    order_date = DateField('Order Date', default=date.today, validators=[DataRequired()])
    expected_date = DateField('Expected Date', validators=[Optional()])
    items = FieldList(FormField(PurchaseOrderItemForm), min_entries=1)
    submit = SubmitField('Create Purchase Order')

class GoodsReceiptForm(FlaskForm):
    batch_number = StringField('Batch Number', validators=[Optional()])
    quantity_received = IntegerField('Quantity Received', validators=[DataRequired(), NumberRange(min=0)])
    expiry_date = DateField('Expiry Date', validators=[Optional()])
    submit = SubmitField('Record Receipt') 