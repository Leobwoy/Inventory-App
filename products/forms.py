from flask_wtf import FlaskForm
from wtforms import BooleanField, StringField, DecimalField, IntegerField, TextAreaField, FileField, SubmitField, SelectField
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Optional
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
    # Off by default. Most of what this market sells does not meaningfully
    # expire, and warning about all of it teaches people to ignore warnings.
    track_expiry = BooleanField('Warn me when this group nears its expiry date')
    submit = SubmitField('Save Item Group')

class ProductForm(FlaskForm):
    # Only name, prices, brand and item group are genuinely required. Everything else
    # defaults, so adding a product is a short form rather than a 12-field wall - the
    # single biggest cause of onboarding abandonment for a wholesaler with 400 SKUs.
    name = StringField('Name', validators=[DataRequired(), Length(max=100)])
    sku = StringField('SKU/Code', validators=[Optional(), Length(max=50)],
                      description='Leave blank to generate one automatically.')
    barcode = StringField('Barcode', validators=[Optional(), Length(max=100)])
    description = TextAreaField('Description')

    # InputRequired, not DataRequired: DataRequired treats 0 as missing, which makes a
    # zero price or a zero stock threshold impossible to save.
    cost_price = DecimalField('Cost price, per single', validators=[InputRequired(), NumberRange(min=0)])
    unit_price = DecimalField('Price per single', validators=[InputRequired(), NumberRange(min=0)])
    quantity_in_stock = IntegerField('Quantity in Stock (Read Only)', render_kw={'readonly': True})

    category_id = SelectField('Category', coerce=int, validators=[Optional()])
    brand_id = SelectField('Brand', coerce=int, validators=[InputRequired()])
    item_group_id = SelectField('Item Group', coerce=int, validators=[InputRequired()])

    variant_label = StringField('Variant Label (e.g. 750ml)', validators=[Optional(), Length(max=100)])
    size_value = DecimalField('Size Value', validators=[Optional(), NumberRange(min=0)])
    size_unit = StringField('Size Unit', validators=[Optional(), Length(max=20)])

    # Labels in the words a shopkeeper uses, not the words a database uses. The
    # field *names* are unchanged on purpose: tests/test_audit.py posts this exact
    # set, and renaming them would be a schema-shaped change dressed as wording.
    #
    # "Base UoM / Purchase UoM / Units per Purchase UoM" is jargon that sat three
    # rows above two price boxes which never said which unit they meant, and an
    # owner typing a carton price into `unit_price` got a product listing at 24x
    # with nothing to catch it.
    base_uom = StringField('What is one called?', validators=[Optional(), Length(max=20)],
                           default='pcs',
                           description='The single item you sell - bottle, sachet, can.')
    purchase_uom = StringField('What is a pack called?',
                               validators=[Optional(), Length(max=20)],
                               description='Carton, crate, box. Leave blank if you do not sell packs.')
    units_per_purchase_uom = IntegerField('How many in a pack?',
                                          validators=[Optional(), NumberRange(min=1)], default=1)

    # The number that cannot be derived. A carton of 24 at 1,050 is 43.75 a
    # bottle against 48 singly, and that gap is the whole reason a shop buys a
    # carton. Optional: blank means a pack is simply count x the single price.
    pack_price = DecimalField('Price per pack', validators=[Optional(), NumberRange(min=0)])
    sell_unit = SelectField('What do you sell it by?', coerce=str, default='base',
                            choices=[('base', 'Singles only'),
                                     ('purchase', 'Packs only'),
                                     ('both', 'Both')],
                            validators=[Optional()])

    min_stock_alert = IntegerField('Min Stock Alert', validators=[Optional(), NumberRange(min=0)], default=0)
    submit = SubmitField('Save')

class ProductUploadForm(FlaskForm):
    file = FileField('Excel File', validators=[DataRequired(), FileAllowed(['xls', 'xlsx'], 'Excel files only!')])
    submit = SubmitField('Upload') 