from flask_wtf import FlaskForm
from wtforms import StringField, DecimalField, IntegerField, TextAreaField, FileField, SubmitField, SelectField
from wtforms.validators import DataRequired, Length, NumberRange, Optional
from flask_wtf.file import FileAllowed

class CategoryForm(FlaskForm):
    name = StringField('Category Name', validators=[DataRequired(), Length(max=100)])
    description = TextAreaField('Description')
    submit = SubmitField('Save Category')

class SupplierForm(FlaskForm):
    name = StringField('Supplier Name', validators=[DataRequired(), Length(max=100)])
    contact = StringField('Contact Person', validators=[Optional(), Length(max=100)])
    phone = StringField('Phone', validators=[Optional(), Length(max=50)])
    email = StringField('Email', validators=[Optional(), Length(max=100)])
    address = TextAreaField('Address', validators=[Optional()])
    submit = SubmitField('Save Supplier')

class ProductForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=100)])
    sku = StringField('SKU/Code', validators=[DataRequired(), Length(max=50)])
    description = TextAreaField('Description')
    unit_price = DecimalField('Unit Price', validators=[DataRequired(), NumberRange(min=0)])
    quantity_in_stock = IntegerField('Quantity in Stock', validators=[DataRequired(), NumberRange(min=0)])
    category_id = SelectField('Category', coerce=int, validators=[Optional()])
    min_stock_alert = IntegerField('Min Stock Alert', validators=[DataRequired(), NumberRange(min=0)])
    submit = SubmitField('Save')

class ProductUploadForm(FlaskForm):
    file = FileField('Excel File', validators=[DataRequired(), FileAllowed(['xls', 'xlsx'], 'Excel files only!')])
    submit = SubmitField('Upload') 