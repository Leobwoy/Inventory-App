"""Backup and restore — F-03.

Previously HTTP Basic auth with a hardcoded username and a default password,
outside the permission system entirely: it pg_dumped every tenant into one file
and its restore path ran DROP DATABASE.
"""
import csv
import io
import json
import zipfile

import pytest

from products.models import Product


@pytest.fixture
def two_shops(register, make_product, app):
    _a, business_a = register(name='Alpha Beverages', email='a@x.example.com')
    _b, business_b = register(name='Beta Traders', email='b@x.example.com', c=app.test_client())
    make_product(business_a, sku='ALPHA-SKU-1', name='Alpha Water', stock=50)
    make_product(business_b, sku='BETA-SKU-1', name='Beta Water', stock=50)

    owner_a = app.test_client()
    owner_a.post('/auth/login', data={'email': 'a@x.example.com', 'password': 'Str0ngPass!23'},
                 follow_redirects=True)
    return owner_a, business_a, business_b


def test_anonymous_is_redirected(client):
    assert client.get('/backup_restore').status_code in (302, 401)


def test_non_owner_is_forbidden(register, make_staff):
    _client, business_id = register()
    staff = make_staff(business_id, 'Manager', 'mgr@x.example.com')
    assert staff.get('/backup_restore').status_code == 403


def test_owner_sees_the_page(two_shops):
    owner_a, _a, _b = two_shops
    response = owner_a.get('/backup_restore')
    assert response.status_code == 200
    # The page used to render blank: it defines {% block content %} while base.html
    # only emitted that block for an authenticated Flask-Login session.
    assert 'Export your data' in response.get_data(as_text=True)


def test_export_contains_only_the_callers_tenant(two_shops):
    owner_a, _a, _b = two_shops
    response = owner_a.post('/backup_restore', data={'backup': '1'})

    assert response.mimetype == 'application/zip'
    archive = zipfile.ZipFile(io.BytesIO(response.data))

    # Read the decompressed CSVs - searching the raw zip proves nothing, since
    # DEFLATE means neither tenant's plaintext appears in the bytes.
    contents = '\n'.join(archive.read(n).decode() for n in archive.namelist()
                         if n.endswith('.csv'))
    assert 'ALPHA-SKU-1' in contents
    assert 'BETA' not in contents

    manifest = json.loads(archive.read('manifest.json'))
    assert manifest['business']['name'] == 'Alpha Beverages'


def test_round_trip_preserves_data(two_shops):
    owner_a, business_a, business_b = two_shops
    archive = owner_a.post('/backup_restore', data={'backup': '1'}).data

    owner_a.post('/backup_restore', data={
        'restore': '1', 'confirm_restore': 'REPLACE',
        'restore_file': (io.BytesIO(archive), 'backup.zip'),
    }, content_type='multipart/form-data', follow_redirects=True)

    products = Product.query.filter_by(business_id=business_a).all()
    assert len(products) == 1
    assert products[0].sku == 'ALPHA-SKU-1'
    assert products[0].quantity_in_stock == 50
    assert Product.query.filter_by(business_id=business_b).count() == 1


def test_restore_requires_explicit_confirmation(two_shops):
    owner_a, _a, _b = two_shops
    archive = owner_a.post('/backup_restore', data={'backup': '1'}).data

    response = owner_a.post('/backup_restore', data={
        'restore': '1', 'confirm_restore': 'no',
        'restore_file': (io.BytesIO(archive), 'backup.zip'),
    }, content_type='multipart/form-data', follow_redirects=True)

    assert 'Type REPLACE' in response.get_data(as_text=True)


def test_garbage_upload_is_rejected_without_data_loss(two_shops):
    owner_a, business_a, _b = two_shops

    response = owner_a.post('/backup_restore', data={
        'restore': '1', 'confirm_restore': 'REPLACE',
        'restore_file': (io.BytesIO(b'not a zip'), 'junk.zip'),
    }, content_type='multipart/form-data', follow_redirects=True)

    assert 'not a valid TrackTrack backup' in response.get_data(as_text=True)
    assert Product.query.filter_by(business_id=business_a).count() == 1


def test_restore_writes_only_into_the_callers_tenant(two_shops, app):
    """An archive can never reach another business's rows."""
    owner_a, business_a, business_b = two_shops
    archive = owner_a.post('/backup_restore', data={'backup': '1'}).data

    beta_skus_before = {p.sku for p in Product.query.filter_by(business_id=business_b)}

    owner_b = app.test_client()
    owner_b.post('/auth/login', data={'email': 'b@x.example.com', 'password': 'Str0ngPass!23'},
                 follow_redirects=True)
    owner_b.post('/backup_restore', data={
        'restore': '1', 'confirm_restore': 'REPLACE',
        'restore_file': (io.BytesIO(archive), 'backup.zip'),
    }, content_type='multipart/form-data', follow_redirects=True)

    # Alpha's rows are untouched no matter how Beta's restore resolved. Asserting
    # `all(p.business_id == business_b for p in query.filter_by(business_id=business_b))`
    # would be a tautology - the filter guarantees it - so compare against what
    # Alpha actually held.
    assert Product.query.filter_by(sku='ALPHA-SKU-1', business_id=business_a).count() == 1
    assert Product.query.filter_by(business_id=business_a).count() == 1

    # Restore replaces Beta's data with the archive's, so Beta now holds Alpha's
    # SKU under Beta's own business_id - possible only because SKUs are unique
    # per tenant (F-17). The point is that it lands as Beta's row while Alpha
    # keeps its own, asserted above.
    beta_skus_after = {p.sku for p in Product.query.filter_by(business_id=business_b)}
    assert beta_skus_after == {'ALPHA-SKU-1'}
    assert beta_skus_after != beta_skus_before


def test_no_drop_database_remains_in_the_codebase():
    """The restore path used to destroy every tenant to restore one."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    # services/backup.py and the tests only mention these in prose explaining why
    # they are gone; migrations/ is historical record.
    exempt = ('services/backup.py', '/tests/', '/migrations/', '.venv')
    offenders = []
    for path in root.rglob('*.py'):
        posix = path.as_posix()
        if any(fragment in posix for fragment in exempt):
            continue
        text = path.read_text(encoding='utf-8', errors='ignore').lower()
        if 'drop database' in text or 'pg_dump' in text:
            offenders.append(path.name)
    assert offenders == []


# --- what a backup must not forget -------------------------------------------

def test_the_carton_price_survives_a_round_trip(two_shops, app):
    """It did not. `pack_price` and `sell_unit` were missing from the export
    spec, so every backup taken before this silently dropped the wholesale price
    and whether a product was sold by the carton.

    That was survivable while the single price was primary. It is not now: a
    restore would reprice an entire catalogue at bottle rates.
    """
    from decimal import Decimal
    from extensions import db

    owner_a, business_a, _b = two_shops
    product = Product.query.filter_by(business_id=business_a).one()
    product.base_uom = 'bottles'
    product.purchase_uom = 'carton'
    product.units_per_purchase_uom = 24
    product.pack_price = Decimal('1050.00')
    product.sell_unit = 'both'
    db.session.commit()

    archive = owner_a.post('/backup_restore', data={'backup': '1'}).data
    owner_a.post('/backup_restore', data={
        'restore': '1', 'confirm_restore': 'REPLACE',
        'restore_file': (io.BytesIO(archive), 'backup.zip'),
    }, content_type='multipart/form-data', follow_redirects=True)

    restored = Product.query.filter_by(business_id=business_a).one()
    assert restored.pack_price == Decimal('1050.00'), 'the wholesale price was lost'
    assert restored.sell_unit == 'both', 'how it is sold was lost'
    assert restored.units_per_purchase_uom == 24


def test_a_restored_sale_remembers_it_was_cartons(two_shops, app):
    """Without sell_unit and sold_quantity a restored sale forgets it was two
    cartons and reads as forty-eight bottles; without list_price every
    historical discount vanishes from the record."""
    import datetime
    from decimal import Decimal
    from extensions import db
    from sales.models import Sale, SaleItem

    owner_a, business_a, _b = two_shops
    product = Product.query.filter_by(business_id=business_a).one()

    sale = Sale(business_id=business_a, sale_date=datetime.date.today())
    db.session.add(sale)
    db.session.flush()
    db.session.add(SaleItem(sale_id=sale.id, product_id=product.id, quantity=48,
                            price_at_sale=Decimal('43.750000'),
                            list_price=Decimal('48.000000'),
                            sell_unit='purchase', sold_quantity=2))
    db.session.commit()

    archive = owner_a.post('/backup_restore', data={'backup': '1'}).data
    owner_a.post('/backup_restore', data={
        'restore': '1', 'confirm_restore': 'REPLACE',
        'restore_file': (io.BytesIO(archive), 'backup.zip'),
    }, content_type='multipart/form-data', follow_redirects=True)

    line = (SaleItem.query.join(Sale, Sale.id == SaleItem.sale_id)
            .filter(Sale.business_id == business_a).one())
    assert line.quantity == 48
    assert line.sold_quantity == 2, 'the sale forgot it was cartons'
    assert line.sell_unit == 'purchase'
    assert line.list_price == Decimal('48.000000'), 'the discount record was lost'


def test_an_archive_from_before_these_columns_still_imports(two_shops, app):
    """The other half of the change: adding columns to the export spec must not
    stop older archives being readable.

    This one passed before the fix too, and it is worth saying why rather than
    leaving it looking like proof. Absent columns used to be handed to the model
    as an explicit None, and that survived only because SQLAlchemy treats an
    explicitly-None attribute as unset and applies the column default - so
    sell_unit landed on 'base' by luck of it having a default. The restore path
    now leaves absent columns out of the insert instead of relying on that. What
    this test pins is the guarantee itself: an archive from before the carton
    columns existed still restores, and the defaults still apply.
    """
    owner_a, business_a, _b = two_shops
    archive = owner_a.post('/backup_restore', data={'backup': '1'}).data

    # Strip the new columns back out, exactly as an older backup would lack them.
    old = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(archive)) as src, zipfile.ZipFile(old, 'w') as dst:
        for name in src.namelist():
            data = src.read(name).decode('utf-8')
            if name.endswith('products.csv'):
                rows = list(csv.DictReader(io.StringIO(data)))
                keep = [c for c in (rows[0].keys() if rows else [])
                        if c not in ('pack_price', 'sell_unit')]
                out = io.StringIO()
                writer = csv.DictWriter(out, fieldnames=keep)
                writer.writeheader()
                for row in rows:
                    writer.writerow({k: row[k] for k in keep})
                data = out.getvalue()
            dst.writestr(name, data)

    response = owner_a.post('/backup_restore', data={
        'restore': '1', 'confirm_restore': 'REPLACE',
        'restore_file': (io.BytesIO(old.getvalue()), 'old-backup.zip'),
    }, content_type='multipart/form-data', follow_redirects=True)

    assert response.status_code == 200
    restored = Product.query.filter_by(business_id=business_a).one()
    assert restored.sell_unit == 'base', 'the model default did not apply'
    assert restored.pack_price is None
