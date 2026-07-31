from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length

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
