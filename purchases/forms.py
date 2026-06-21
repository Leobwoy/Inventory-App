from flask_wtf import FlaskForm
from wtforms import SelectField, IntegerField, DecimalField, StringField, DateField, SubmitField
from wtforms.validators import DataRequired, NumberRange, Optional

class PurchaseForm(FlaskForm):
    product_id = SelectField('Product', coerce=int, validators=[DataRequired()])
    quantity = IntegerField('Quantity Purchased', validators=[DataRequired(), NumberRange(min=1)])
    purchase_price = DecimalField('Purchase Price', validators=[DataRequired(), NumberRange(min=0)])
    supplier_id = SelectField('Supplier', coerce=int, validators=[Optional()])
    purchase_date = DateField('Purchase Date', validators=[DataRequired()])
    submit = SubmitField('Record Purchase') 