from flask_wtf import FlaskForm
from wtforms import SelectField, IntegerField, DecimalField, StringField, DateField, SubmitField, FieldList, FormField
from wtforms.validators import DataRequired, NumberRange, Optional

class PurchaseOrderItemForm(FlaskForm):
    product_id = SelectField('Product', coerce=int, validators=[DataRequired()])
    quantity_ordered = IntegerField('Quantity Ordered', validators=[DataRequired(), NumberRange(min=1)])
    # Which unit the quantity and cost above are typed in. Storage is always base
    # units; this only says how to read what was entered (services/uom.py).
    order_unit = SelectField('Unit', choices=[('purchase', 'Cartons'), ('base', 'Pieces')],
                             default='purchase', validators=[Optional()])
    unit_cost = DecimalField('Unit Cost', validators=[DataRequired(), NumberRange(min=0)])

class PurchaseOrderForm(FlaskForm):
    supplier_id = SelectField('Supplier', coerce=int, validators=[Optional()])
    order_date = DateField('Order Date', validators=[DataRequired()])
    expected_date = DateField('Expected Date', validators=[Optional()])
    items = FieldList(FormField(PurchaseOrderItemForm), min_entries=1)
    submit = SubmitField('Create Purchase Order')

class GoodsReceiptForm(FlaskForm):
    batch_number = StringField('Batch Number', validators=[Optional()])
    quantity_received = IntegerField('Quantity Received', validators=[DataRequired(), NumberRange(min=0)])
    expiry_date = DateField('Expiry Date', validators=[Optional()])
    submit = SubmitField('Record Receipt') 