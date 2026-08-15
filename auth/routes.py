from flask import (Blueprint, Response, abort, current_app, flash, jsonify,
                   redirect, render_template, request, url_for)
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from auth.models import User, Business, Role, AuditLog
from sqlalchemy.orm import joinedload
from auth.forms import (BusinessSettingsForm, RegistrationForm, ChangePasswordForm,
                        UserForm)
from auth.decorators import permission_required, requires_feature
from auth.permissions import ALL as ALL_PERMISSION_CODES, GROUP_ORDER, PERMISSIONS
from products.models import Brand, ItemGroup
from services import audit, limits
from billing.models import Plan, Subscription
from billing.plans import TRIAL_DAYS
from datetime import timedelta
from extensions import db
from sqlalchemy import func
from datetime import datetime
from urllib.parse import urlparse

auth_bp = Blueprint('auth', __name__)

@auth_bp.before_app_request
def enforce_password_change():
    """Hold a staff member on the password page until they have set their own.

    Their password was typed for them by whoever created the account, so until
    it is changed the person who typed it can sign in as them.
    """
    if not (current_user.is_authenticated
            and getattr(current_user, 'must_change_password', False)):
        return

    if (request.endpoint in ('auth.change_password', 'auth.logout', 'static')
            or request.path.startswith('/static/')):
        return

    # Background fetches get an answer they can read, not a redirect to a login
    # form they would try to parse as JSON.
    if request.blueprint == 'api' or request.path.startswith('/api/'):
        return jsonify({'error': 'Set your password first.',
                        'code': 'password_change_required'}), 403

    # Deliberately no flash. The badge counter fetches on every page, and it is
    # blocked here too - so flashing queued one message per background request,
    # left them in the session, and the banner arrived two and three at a time.
    # The page itself says why they are on it, which cannot pile up.
    return redirect(url_for('auth.change_password'))

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''

        # Email is globally unique, so an address resolves to exactly one account.
        user = User.query.filter(func.lower(User.email) == email).first()

        # Check is_active before revealing anything about the password, so a
        # deactivated account cannot be used as a password oracle.
        if user and not user.is_active:
            flash("Your account is deactivated. Contact your administrator.", "danger")
            return render_template('login.html')

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            user.last_login_at = datetime.utcnow()
            db.session.commit()

            # Only follow relative next targets - an absolute URL here is an open redirect.
            next_page = request.args.get('next')
            if not next_page or urlparse(next_page).netloc or not next_page.startswith('/'):
                next_page = url_for('index')
            return redirect(next_page)

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
        # 1. Email identifies a person globally, so it may only back one account
        existing_user = User.query.filter(
            func.lower(User.email) == (form.email.data or '').strip().lower()
        ).first()
        if existing_user:
            flash('That email address is already registered. Sign in instead.', 'danger')
            return render_template('auth/register.html', form=form)

        # 2. Get Owner role - the person registering the business owns it
        owner_role = Role.query.filter_by(name='Owner').first()
        if not owner_role:
            flash('System error: Owner role not found. Please run database migrations.', 'danger')
            return render_template('auth/register.html', form=form)
            
        # 2. Create Business with branding
        new_business = Business(
            name=form.business_name.data,
            address=form.business_address.data,
            contact_number=form.business_contact.data
        )
        db.session.add(new_business)
        db.session.flush() # get new_business.id

        # 3. Create User (must_change_password=False for a self-registered Owner)
        new_user = User(
            business_id=new_business.id,
            name=form.user_name.data,
            email=form.email.data,
            password_hash=generate_password_hash(form.password.data),
            role_id=owner_role.id,
            must_change_password=False
        )
        db.session.add(new_user)
        db.session.flush()
        # Owners implicitly hold everything via User.can(), but write the rows too so
        # the permission grid renders correctly for them.
        new_user.apply_role_preset('Owner')

        # 4. Start the free trial. Full features for TRIAL_DAYS, then the
        # account downgrades to Free rather than locking - they keep their data
        # and keep working at the free tier's limits.
        trial_plan = Plan.query.filter_by(code='trial').first()
        if trial_plan:
            db.session.add(Subscription(
                business_id=new_business.id,
                plan_id=trial_plan.id,
                status='trialing',
                trial_ends_at=datetime.utcnow() + timedelta(days=TRIAL_DAYS),
            ))

        # 5. Seed catalogue fallbacks. Product.brand_id and item_group_id are NOT NULL,
        # so without these the business cannot save a single product.
        db.session.add(Brand(business_id=new_business.id, name='Generic'))
        db.session.add(ItemGroup(business_id=new_business.id, name='Uncategorized'))

        db.session.commit()
        
        # 6. Log them in
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
    # standalone=True, or base.html renders the signed-in layout and this
    # template's auth_content block is never emitted - which is what happened:
    # the page came back with a sidebar, the banner, and no form on it at all.
    return render_template('auth/change_password.html', form=form, standalone=True)

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
            allowed, message = limits.can_add_user()
            if not allowed:
                # A plan ceiling is a sales conversation, not a 403.
                flash(message, 'warning')
                return render_template('auth/add_user.html', form=form, roles=roles)

            existing_user = User.query.filter(
                func.lower(User.email) == (form.email.data or '').strip().lower()
            ).first()
            if existing_user:
                flash('That email address already has a TrackTrack account.', 'danger')
                return render_template('auth/add_user.html', form=form, roles=roles)
                
            role = Role.query.get(role_id)
            if not role or role.name == 'Owner':
                # Owner is the account that registered the business; it is not
                # assignable, or a staff member could be handed the whole tenant.
                flash('Select a valid role.', 'danger')
                return render_template('auth/add_user.html', form=form, roles=roles)

            new_user = User(
                business_id=current_user.business_id,
                name=form.name.data,
                email=form.email.data,
                password_hash=generate_password_hash(form.password.data),
                role_id=role.id,
                must_change_password=True  # Force reset for staff created by admin
            )
            db.session.add(new_user)
            db.session.flush()

            # The role seeds a starting set; the Owner tunes it per person afterwards.
            new_user.apply_role_preset(role.name)
            audit.log('user.create', entity_type='user', entity_id=new_user.id,
                      email=new_user.email, name=new_user.name, preset=role.name,
                      permissions=sorted(new_user.permission_codes()))
            db.session.commit()
            flash(f'{new_user.name} added. Review their permissions, and note they must '
                  'change their password on first login.', 'success')
            return redirect(url_for('auth.edit_user_permissions', user_id=new_user.id))

    return render_template('auth/add_user.html', form=form, roles=roles)


@auth_bp.route('/users/<int:user_id>/permissions', methods=['GET', 'POST'])
@login_required
@permission_required('users.manage')
def edit_user_permissions(user_id):
    """Per-person permission grid. UserPermission is the authority, not Role."""
    user = User.query.filter_by(id=user_id, business_id=current_user.business_id).first_or_404()

    if user.is_owner:
        flash("The Owner always holds every permission and cannot be restricted.", 'info')
        return redirect(url_for('auth.users_list'))

    if request.method == 'POST':
        submitted = set(request.form.getlist('permissions'))
        # Ignore anything not in the catalogue - never trust posted codes.
        before = user.permission_codes()
        user.set_permissions(submitted & ALL_PERMISSION_CODES)
        after = user.permission_codes()
        if before != after:
            audit.log('user.permissions_change', entity_type='user', entity_id=user.id,
                      email=user.email,
                      granted=sorted(after - before), revoked=sorted(before - after))
        db.session.commit()
        flash(f"Permissions updated for {user.name}.", 'success')
        return redirect(url_for('auth.users_list'))

    granted = user.permission_codes()
    grouped = {}
    for code, (description, group) in PERMISSIONS.items():
        grouped.setdefault(group, []).append((code, description, code in granted))
    ordered = [(g, grouped[g]) for g in GROUP_ORDER if g in grouped]

    return render_template('auth/user_permissions.html', user=user, grouped=ordered,
                           roles=Role.query.filter(Role.name != 'Owner').all())


@auth_bp.route('/users/<int:user_id>/apply_preset', methods=['POST'])
@login_required
@permission_required('users.manage')
def apply_user_preset(user_id):
    """Reset a user's permissions to a role preset, as a starting point."""
    user = User.query.filter_by(id=user_id, business_id=current_user.business_id).first_or_404()
    if user.is_owner:
        flash("The Owner's permissions cannot be changed.", 'warning')
        return redirect(url_for('auth.users_list'))

    role = Role.query.filter(Role.id == request.form.get('role_id', type=int),
                             Role.name != 'Owner').first()
    if not role:
        flash('Select a valid role.', 'danger')
        return redirect(url_for('auth.edit_user_permissions', user_id=user.id))

    before = user.permission_codes()
    user.role_id = role.id
    user.apply_role_preset(role.name)
    audit.log('user.preset_applied', entity_type='user', entity_id=user.id,
              email=user.email, preset=role.name,
              granted=sorted(user.permission_codes() - before),
              revoked=sorted(before - user.permission_codes()))
    db.session.commit()
    flash(f"{user.name} reset to the {role.name} preset. Adjust individual permissions below.", 'success')
    return redirect(url_for('auth.edit_user_permissions', user_id=user.id))


def _as_date(value):
    """A yyyy-mm-dd filter value, or None. A bad one must not take the page down."""
    try:
        return datetime.strptime(value, '%Y-%m-%d').date() if value else None
    except (TypeError, ValueError):
        return None


@auth_bp.route('/audit')
@login_required
@permission_required('audit.view')
@requires_feature('audit_log')
def audit_log():
    """Who did what, and when. Filterable by person, kind of action and date."""
    page = request.args.get('page', 1, type=int)
    action = request.args.get('action', '').strip()
    user_id = request.args.get('user_id', type=int)
    start, end = request.args.get('start_date'), request.args.get('end_date')

    query = AuditLog.query.filter_by(business_id=current_user.business_id) \
        .options(joinedload(AuditLog.user))
    if action:
        query = query.filter(AuditLog.action == action)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    # Parsed, not passed through. These are raw query strings compared against a
    # timestamp column: on PostgreSQL `?start_date=abc` raises a DataError and
    # returns 500, which anyone holding audit.view can trigger from the URL bar.
    start_on, end_on = _as_date(start), _as_date(end)
    if start_on:
        query = query.filter(AuditLog.timestamp >= start_on)
    if end_on:
        # Whole day inclusive, built from a real date rather than string-glued.
        query = query.filter(AuditLog.timestamp < end_on + timedelta(days=1))

    pagination = query.order_by(AuditLog.timestamp.desc()).paginate(
        page=page, per_page=50, error_out=False)

    # Only offer filters for actions this business has actually recorded.
    actions = [row[0] for row in db.session.query(AuditLog.action)
               .filter_by(business_id=current_user.business_id)
               .distinct().order_by(AuditLog.action).all()]

    return render_template(
        'auth/audit.html',
        entries=pagination.items, pagination=pagination, actions=actions,
        users=User.query.filter_by(business_id=current_user.business_id).order_by(User.name).all(),
        filters=request.args,
    )


@auth_bp.route('/users/<int:user_id>/toggle_active', methods=['POST'])
@login_required
@permission_required('users.manage')
def toggle_user_active(user_id):
    """Suspend or reinstate a staff member. Never hard-delete - it breaks the audit trail."""
    user = User.query.filter_by(id=user_id, business_id=current_user.business_id).first_or_404()
    if user.is_owner:
        flash('The Owner account cannot be suspended.', 'warning')
    elif user.id == current_user.id:
        flash('You cannot suspend your own account.', 'warning')
    else:
        user.is_active = not user.is_active
        audit.log('user.reinstate' if user.is_active else 'user.suspend',
                  entity_type='user', entity_id=user.id, email=user.email)
        db.session.commit()
        flash(f"{user.name} {'reinstated' if user.is_active else 'suspended'}.", 'success')
    return redirect(url_for('auth.users_list'))


@auth_bp.route('/tour/done', methods=['POST'])
@login_required
def tour_seen():
    """Record that this person has been shown the app. Idempotent.

    Both endings count: finishing the tour and closing it on the second step are
    equally an answer, and offering it again tomorrow would be ignoring the one
    we were given.

    204 rather than a redirect - the caller is a `fetch` from the page the user
    is still reading, and it has nothing to do with a body.
    """
    # A conditional UPDATE rather than reading the attribute and then writing it.
    # This is a read-then-write on a shared row (invariant 8): two requests - a
    # double click, a retry, the same person finishing on two devices - would
    # both see None, both write, and both audit. Letting the database decide who
    # got there first makes the check and the write one operation.
    #
    # synchronize_session=False leaves `current_user` stale in this session,
    # which is harmless: nothing below reads it and the response carries no body.
    updated = (User.query
               .filter(User.id == current_user.id, User.tour_seen_at.is_(None))
               .update({'tour_seen_at': datetime.utcnow()},
                       synchronize_session=False))
    if updated == 1:
        audit.log('user.tour_seen', entity_type='user', entity_id=current_user.id,
                  reason=(request.form.get('reason') or 'completed')[:32])
    db.session.commit()
    return '', 204


@auth_bp.route('/theme', methods=['POST'])
@login_required
def set_theme():
    """Record which theme this person wants. Not permission-gated, on purpose.

    Settings is behind `settings.manage` and is a business-wide form, so a
    control living only there would be unreachable for a Sales Staff member -
    and the clerk standing in a market doorway in full sun is exactly who needs
    to switch to light.

    204 rather than a redirect: the caller is a fetch from the page they are
    still reading, and the browser has already applied the change locally.
    """
    wanted = (request.form.get('theme') or '').strip()
    if wanted not in User.THEMES:
        return jsonify({'error': 'Unknown theme.'}), 400

    # Conditional UPDATE, and the audit entry follows the rowcount rather than
    # the in-memory value. `current_user` can be stale - a second device, or a
    # double tap whose first request has not committed - and an entry written
    # for an UPDATE that changed nothing is a record of a decision nobody made.
    changed = (User.query
               .filter(User.id == current_user.id, User.theme_pref != wanted)
               .update({'theme_pref': wanted}, synchronize_session=False))
    if changed == 1:
        audit.log('user.theme_changed', entity_type='user',
                  entity_id=current_user.id, theme=wanted)
    db.session.commit()
    return '', 204


@auth_bp.route('/users/<int:user_id>/reset_password', methods=['POST'])
@login_required
@permission_required('users.manage')
def reset_user_password(user_id):
    """Issue a staff member a new temporary password.

    The everyday case, and the reason this is not only a console feature: a sales
    clerk who forgets their password on a Saturday should not need the vendor.

    The password is shown once and never stored in plain text. Whoever runs this
    knows it for as long as it takes to relay, and the account is held on the
    change-password page until the holder replaces it.
    """
    from services import passwords

    user = User.query.filter_by(id=user_id,
                                business_id=current_user.business_id).first_or_404()

    if user.id == current_user.id:
        # Not forbidden so much as pointless, and confusing: it would hand you a
        # password you already have a page for changing directly.
        flash('To change your own password, use Change Password.', 'warning')
        return redirect(url_for('auth.users_list'))

    temporary = passwords.reset(user)
    db.session.commit()

    flash(f'Temporary password for {user.name}: {temporary} — give it to them '
          f'now, it will not be shown again. They must change it when they '
          f'sign in.', 'success')
    return redirect(url_for('auth.users_list'))


MAX_LOGO_BYTES = 512 * 1024


@auth_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@permission_required('settings.manage')
def business_settings():
    """Business-level configuration.

    Every field here already existed on the Business row with no way to change
    it. max_discount_percent matters most: it defaults to 0, so until this page
    existed the whole discount system - the sales.discount permission, the
    ceiling, the never-below-cost floor - was finished code no business could
    switch on.
    """
    business = Business.query.get_or_404(current_user.business_id)
    form = BusinessSettingsForm(obj=business)

    if form.validate_on_submit():
        before = {
            'name': business.name,
            'max_discount_percent': str(business.max_discount_percent),
            'expiry_alert_days': business.expiry_alert_days,
        }
        business.name = form.name.data.strip()
        business.address = (form.address.data or '').strip() or None
        business.contact_number = (form.contact_number.data or '').strip() or None
        business.expiry_alert_days = form.expiry_alert_days.data
        business.max_discount_percent = form.max_discount_percent.data

        upload = form.logo.data
        if form.remove_logo.data:
            business.logo_data = None
            business.logo_mimetype = None
        elif upload:
            blob = upload.read()
            if len(blob) > MAX_LOGO_BYTES:
                flash(f'That logo is {len(blob) // 1024}KB. Keep it under '
                      f'{MAX_LOGO_BYTES // 1024}KB so pages stay quick on mobile data.',
                      'danger')
                return render_template('auth/settings.html', form=form, business=business)
            business.logo_data = blob
            business.logo_mimetype = upload.mimetype

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('saving business settings failed')
            flash('Something went wrong and the settings were not saved.', 'danger')
            return render_template('auth/settings.html', form=form, business=business)

        # The discount ceiling is a money control, so a change to it is worth
        # being able to find later.
        audit.log('settings.update', entity_type='business', entity_id=business.id,
                  before=before,
                  after={'name': business.name,
                         'max_discount_percent': str(business.max_discount_percent),
                         'expiry_alert_days': business.expiry_alert_days})
        db.session.commit()
        flash('Settings saved.', 'success')
        return redirect(url_for('auth.business_settings'))

    return render_template('auth/settings.html', form=form, business=business)


@auth_bp.route('/business/logo')
@login_required
def business_logo():
    """Serve this business's logo. Scoped to the caller, so an id cannot be
    tampered with to read another tenant's branding."""
    business = Business.query.get_or_404(current_user.business_id)
    if not business.has_logo:
        abort(404)
    return Response(business.logo_data,
                    mimetype=business.logo_mimetype or 'image/png',
                    headers={'Cache-Control': 'private, max-age=300'})
