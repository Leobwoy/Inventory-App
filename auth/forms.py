from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import (BooleanField, DecimalField, IntegerField, PasswordField,
                     StringField, SubmitField)
from wtforms.validators import (DataRequired, Email, EqualTo, InputRequired,
                                Length, NumberRange)

class RegistrationForm(FlaskForm):
    # Business Branding
    business_name = StringField('Business Name', validators=[DataRequired(), Length(max=100)])
    business_address = StringField('Business Address', validators=[Length(max=255)])
    business_contact = StringField('Contact Number', validators=[Length(max=50)])
    
    # User Details
    user_name = StringField('Your Name', validators=[DataRequired(), Length(max=100)])
    email = StringField('Email Address', validators=[DataRequired(), Email(), Length(max=100)])
    password = PasswordField('Password', validators=[
        DataRequired(), 
        Length(min=8, message='Password must be at least 8 characters long.')
    ])
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(), 
        EqualTo('password', message='Passwords must match.')
    ])
    
    submit = SubmitField('Register Business')

class ChangePasswordForm(FlaskForm):
    new_password = PasswordField('New Password', validators=[
        DataRequired(), 
        Length(min=8, message='Password must be at least 8 characters long.')
    ])
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(), 
        EqualTo('new_password', message='Passwords must match.')
    ])
    submit = SubmitField('Change Password')

class UserForm(FlaskForm):
    name = StringField('Full Name', validators=[DataRequired(), Length(max=100)])
    email = StringField('Email Address', validators=[DataRequired(), Email(), Length(max=100)])
    password = PasswordField('Temporary Password', validators=[
        DataRequired(),
        Length(min=8, message='Password must be at least 8 characters long.')
    ])
    # Role will be dynamic or hardcoded SelectField in the route
    submit = SubmitField('Add User')


class BusinessSettingsForm(FlaskForm):
    """Business-level configuration an Owner can change after registration."""
    name = StringField('Business Name', validators=[DataRequired(), Length(max=100)])
    address = StringField('Business Address', validators=[Length(max=255)])
    contact_number = StringField('Contact Number', validators=[Length(max=50)])
    logo = FileField('Logo', validators=[
        FileAllowed(['png', 'jpg', 'jpeg'], 'Images only: PNG or JPG.'),
    ])
    remove_logo = BooleanField('Remove the current logo')
    # InputRequired, not DataRequired: both of these are legitimately 0, and
    # DataRequired treats 0 as missing.
    expiry_alert_days = IntegerField('Warn me this many days before stock expires',
                                     validators=[InputRequired(), NumberRange(min=0, max=365)])
    max_discount_percent = DecimalField(
        'Largest discount staff may give (%)', places=2,
        validators=[InputRequired(), NumberRange(
            min=0, max=100,
            message='A discount ceiling must be between 0 and 100 percent.')])
    submit = SubmitField('Save settings')
