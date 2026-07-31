from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from auth.models import User, Business, Role
from auth.forms import RegistrationForm, ChangePasswordForm, UserForm
from auth.decorators import permission_required
from products.models import Brand, ItemGroup
from extensions import db

auth_bp = Blueprint('auth', __name__)

@auth_bp.before_app_request
def enforce_password_change():
    # Only enforce for logged-in users who need to change password
    if current_user.is_authenticated and getattr(current_user, 'must_change_password', False):
        # Allow them to access the logout, change password, and static files
        if request.endpoint not in ['auth.change_password', 'auth.logout', 'static'] and not request.path.startswith('/static/'):
            flash('You must change your temporary password before accessing the system.', 'warning')
            return redirect(url_for('auth.change_password'))

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            if not user.is_active:
                flash("Your account is deactivated.", "danger")
                return redirect(url_for('auth.login'))
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        flash("Invalid email or password", "danger")
    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    form = RegistrationForm()
    if form.validate_on_submit():
        # 1. Validate global email uniqueness
        existing_user = User.query.filter_by(email=form.email.data).first()
        if existing_user:
            flash('Email address is already in use.', 'danger')
            return render_template('auth/register.html', form=form)
        
        # 2. Get Admin role
        admin_role = Role.query.filter_by(name='Admin').first()
        if not admin_role:
            flash('System error: Admin role not found. Please run database migrations.', 'danger')
            return render_template('auth/register.html', form=form)
            
        # 3. Create Business with branding
        new_business = Business(
            name=form.business_name.data,
            address=form.business_address.data,
            contact_number=form.business_contact.data
        )
        db.session.add(new_business)
        db.session.flush() # get new_business.id

        # 4. Create User (must_change_password=False for self-registered Admin)
        new_user = User(
            business_id=new_business.id,
            name=form.user_name.data,
            email=form.email.data,
            password_hash=generate_password_hash(form.password.data),
            role_id=admin_role.id,
            must_change_password=False
        )
        db.session.add(new_user)

        # 5. Seed catalogue fallbacks. Product.brand_id and item_group_id are NOT NULL,
        # so without these the business cannot save a single product.
        db.session.add(Brand(business_id=new_business.id, name='Generic'))
        db.session.add(ItemGroup(business_id=new_business.id, name='Uncategorized'))

        db.session.commit()
        
        # 5. Log them in
        login_user(new_user)
        flash('Registration successful! Welcome to TrackTrack.', 'success')
        return redirect(url_for('index'))
        
    return render_template('auth/register.html', form=form)

@auth_bp.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        current_user.password_hash = generate_password_hash(form.new_password.data)
        current_user.must_change_password = False
        db.session.commit()
        flash('Password updated successfully. You now have access to the system.', 'success')
        return redirect(url_for('index'))
    return render_template('auth/change_password.html', form=form)

@auth_bp.route('/users')
@login_required
@permission_required('users.manage')
def users_list():
    users = User.query.filter_by(business_id=current_user.business_id).all()
    return render_template('auth/users.html', users=users)

@auth_bp.route('/users/add', methods=['GET', 'POST'])
@login_required
@permission_required('users.manage')
def add_user():
    form = UserForm()
    # Populate role choices
    roles = Role.query.all()
    # Exclude system roles from being reassigned if necessary, or just list all
    # Using dynamic form choices instead of creating a SelectField in forms.py to avoid app context issues
    if request.method == 'POST':
        role_id = request.form.get('role_id')
        if not role_id:
            flash('Please select a role.', 'danger')
            return render_template('auth/add_user.html', form=form, roles=roles)
            
        if form.validate_on_submit():
            existing_user = User.query.filter_by(email=form.email.data).first()
            if existing_user:
                flash('Email address is already in use globally.', 'danger')
                return render_template('auth/add_user.html', form=form, roles=roles)
                
            new_user = User(
                business_id=current_user.business_id,
                name=form.name.data,
                email=form.email.data,
                password_hash=generate_password_hash(form.password.data),
                role_id=role_id,
                must_change_password=True  # Force reset for staff created by admin
            )
            db.session.add(new_user)
            db.session.commit()
            flash(f'User {new_user.name} added successfully. They must change their password on first login.', 'success')
            return redirect(url_for('auth.users_list'))
            
    return render_template('auth/add_user.html', form=form, roles=roles)
