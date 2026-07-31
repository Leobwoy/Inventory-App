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

class BrandForm(FlaskForm):
    name = StringField('Brand Name', validators=[DataRequired(), Length(max=100)])
    submit = SubmitField('Save Brand')

class ItemGroupForm(FlaskForm):
    name = StringField('Item Group Name', validators=[DataRequired(), Length(max=100)])
    category_id = SelectField('Category', coerce=int, validators=[Optional()])
    submit = SubmitField('Save Item Group')

class ProductForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=100)])
    sku = StringField('SKU/Code', validators=[DataRequired(), Length(max=50)])
    barcode = StringField('Barcode', validators=[Optional(), Length(max=100)])
    description = TextAreaField('Description')
    
    cost_price = DecimalField('Cost Price', validators=[DataRequired(), NumberRange(min=0)])
    unit_price = DecimalField('Unit Price', validators=[DataRequired(), NumberRange(min=0)])
    quantity_in_stock = IntegerField('Quantity in Stock (Read Only)', render_kw={'readonly': True})
    
    category_id = SelectField('Category', coerce=int, validators=[Optional()])
    brand_id = SelectField('Brand', coerce=int, validators=[DataRequired()])
    item_group_id = SelectField('Item Group', coerce=int, validators=[DataRequired()])
    
    variant_label = StringField('Variant Label (e.g. 750ml)', validators=[Optional(), Length(max=100)])
    size_value = DecimalField('Size Value', validators=[Optional(), NumberRange(min=0)])
    size_unit = StringField('Size Unit', validators=[Optional(), Length(max=20)])
    
    base_uom = StringField('Base UoM', validators=[DataRequired(), Length(max=20)])
    purchase_uom = StringField('Purchase UoM', validators=[DataRequired(), Length(max=20)])
    units_per_purchase_uom = IntegerField('Units per Purchase UoM', validators=[DataRequired(), NumberRange(min=1)])
    
    min_stock_alert = IntegerField('Min Stock Alert', validators=[DataRequired(), NumberRange(min=0)])
    submit = SubmitField('Save')

class ProductUploadForm(FlaskForm):
    file = FileField('Excel File', validators=[DataRequired(), FileAllowed(['xls', 'xlsx'], 'Excel files only!')])
    submit = SubmitField('Upload') 