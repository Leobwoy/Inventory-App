"""Per-tenant logical export and import.

Replaces the previous implementation, which shelled out to pg_dump across the
whole cluster (handing any caller every tenant's data in one file) and whose
restore path ran DROP DATABASE, destroying every tenant to restore one.

Everything here is scoped to a single business_id. Import only ever writes into
the caller's own tenant, remapping primary keys so an archive can never
overwrite or reference another business's rows.
"""
import csv
import io
import json
import zipfile
from datetime import datetime, date
from decimal import Decimal

from extensions import db
from auth.models import Business
from products.models import Category, Brand, ItemGroup, Product, Supplier
from sales.models import Customer, Sale, SaleItem
from purchases.models import PurchaseOrder, PurchaseOrderItem, StockBatch

SCHEMA_VERSION = 1

# Ordered parents-first. Import walks this forwards, wipe walks it backwards,
# so foreign keys are always satisfied.
EXPORT_SPEC = [
    ('categories',            Category,          ['id', 'name', 'description']),
    ('brands',                Brand,             ['id', 'name']),
    ('item_groups',           ItemGroup,         ['id', 'name', 'category_id']),
    ('suppliers',             Supplier,          ['id', 'name', 'contact', 'phone', 'email', 'address']),
    ('customers',             Customer,          ['id', 'name', 'phone', 'email', 'address']),
    # pack_price and sell_unit were missing here until now, so every backup
    # taken before this line silently dropped the wholesale price and whether a
    # product was sold by the carton. That is the *primary* price now, and a
    # restore that loses it would reprice a whole catalogue at bottle rates.
    ('products',              Product,           ['id', 'name', 'sku', 'description', 'unit_price',
                                                  'cost_price', 'pack_price', 'sell_unit',
                                                  'quantity_in_stock', 'min_stock_alert',
                                                  'category_id', 'item_group_id', 'brand_id',
                                                  'variant_label', 'size_value', 'size_unit', 'barcode',
                                                  'base_uom', 'purchase_uom', 'units_per_purchase_uom',
                                                  'is_active']),
    ('purchase_orders',       PurchaseOrder,     ['id', 'supplier_id', 'status', 'order_date',
                                                  'expected_date']),
    ('purchase_order_items',  PurchaseOrderItem, ['id', 'po_id', 'product_id', 'quantity_ordered',
                                                  'quantity_received', 'unit_cost']),
    ('stock_batches',         StockBatch,        ['id', 'product_id', 'po_item_id', 'batch_number',
                                                  'quantity_received', 'quantity_remaining',
                                                  'received_date', 'expiry_date']),
    ('sales',                 Sale,              ['id', 'sale_date', 'customer_id']),
    # Likewise: without sell_unit and sold_quantity a restored sale forgets it
    # was two cartons and reads as forty-eight bottles, and without list_price
    # every historical discount vanishes from the record.
    ('sale_items',            SaleItem,          ['id', 'sale_id', 'product_id', 'quantity',
                                                  'price_at_sale', 'list_price',
                                                  'sell_unit', 'sold_quantity']),
]

# Which columns are foreign keys, and which exported table they point at.
FK_TARGETS = {
    'category_id': 'categories',
    'item_group_id': 'item_groups',
    'brand_id': 'brands',
    'supplier_id': 'suppliers',
    'customer_id': 'customers',
    'product_id': 'products',
    'po_id': 'purchase_orders',
    'po_item_id': 'purchase_order_items',
    'sale_id': 'sales',
}

# Tables reached through a parent rather than carrying business_id themselves.
_CHILD_FILTERS = {
    PurchaseOrderItem: lambda q: q.join(PurchaseOrder, PurchaseOrderItem.po_id == PurchaseOrder.id),
    SaleItem: lambda q: q.join(Sale, SaleItem.sale_id == Sale.id),
}


def _rows_for(model, business_id):
    """All rows of `model` belonging to `business_id`, direct or via their parent."""
    query = model.query
    if model in _CHILD_FILTERS:
        parent = PurchaseOrder if model is PurchaseOrderItem else Sale
        query = _CHILD_FILTERS[model](query).filter(parent.business_id == business_id)
    else:
        query = query.filter_by(business_id=business_id)
    return query.all()


def _serialize(value):
    if value is None:
        return ''
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bool):
        return '1' if value else '0'
    return str(value)


def export_business(business_id):
    """Return (BytesIO zip, filename) holding this business's data as CSVs."""
    business = Business.query.get(business_id)
    if business is None:
        raise ValueError('Business not found')

    buffer = io.BytesIO()
    counts = {}
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for table_name, model, columns in EXPORT_SPEC:
            rows = _rows_for(model, business_id)
            counts[table_name] = len(rows)
            sheet = io.StringIO()
            writer = csv.writer(sheet, lineterminator='\n')
            writer.writerow(columns)
            for row in rows:
                writer.writerow([_serialize(getattr(row, c, None)) for c in columns])
            archive.writestr(f'{table_name}.csv', sheet.getvalue())

        archive.writestr('manifest.json', json.dumps({
            'schema_version': SCHEMA_VERSION,
            'exported_at': datetime.utcnow().isoformat(),
            'business': {
                'id': business.id,
                'name': business.name,
                'address': business.address,
                'contact_number': business.contact_number,
            },
            'row_counts': counts,
        }, indent=2))

    buffer.seek(0)
    stamp = datetime.utcnow().strftime('%Y%m%d-%H%M')
    slug = ''.join(ch for ch in (business.name or 'business') if ch.isalnum() or ch in '-_') or 'business'
    return buffer, f'tracktrack-{slug}-{stamp}.zip'


def _coerce(model, column, raw):
    """Turn a CSV string back into the type the column expects."""
    if raw == '':
        return None
    attr = getattr(model, column, None)
    col_type = None
    if attr is not None and hasattr(attr, 'type'):
        col_type = attr.type.__class__.__name__
    if col_type == 'Integer':
        return int(raw)
    if col_type == 'Numeric':
        return Decimal(raw)
    if col_type == 'Boolean':
        return raw in ('1', 'true', 'True')
    if col_type == 'Date':
        return date.fromisoformat(raw)
    if col_type == 'DateTime':
        return datetime.fromisoformat(raw)
    return raw


def wipe_business_data(business_id):
    """Delete this business's operational rows, children first.

    Leaves the Business row, its users and its audit log intact - a restore
    replaces inventory and transactions, never the account itself.
    """
    for table_name, model, _cols in reversed(EXPORT_SPEC):
        for row in _rows_for(model, business_id):
            db.session.delete(row)
    db.session.flush()


def import_business(business_id, file_storage, replace=True):
    """Load an archive into `business_id`. Returns a per-table count of rows written.

    Primary keys from the archive are discarded and remapped, so imported rows
    can only ever reference other rows from the same import. Raises ValueError
    on a malformed archive; the caller owns the transaction.
    """
    try:
        archive = zipfile.ZipFile(file_storage)
    except zipfile.BadZipFile:
        raise ValueError('That file is not a valid TrackTrack backup (expected a .zip archive).')

    names = set(archive.namelist())
    if 'manifest.json' not in names:
        raise ValueError('Backup is missing manifest.json - it may not be a TrackTrack export.')

    manifest = json.loads(archive.read('manifest.json').decode('utf-8'))
    version = manifest.get('schema_version')
    if version != SCHEMA_VERSION:
        raise ValueError(f'Backup schema version {version} is not supported (expected {SCHEMA_VERSION}).')

    if replace:
        wipe_business_data(business_id)

    id_map = {table: {} for table, _m, _c in EXPORT_SPEC}
    written = {}

    for table_name, model, columns in EXPORT_SPEC:
        csv_name = f'{table_name}.csv'
        written[table_name] = 0
        if csv_name not in names:
            continue

        text = archive.read(csv_name).decode('utf-8')
        for record in csv.DictReader(io.StringIO(text)):
            old_id = record.get('id')
            values = {}
            skip = False
            for column in columns:
                if column == 'id':
                    continue
                # Absent and blank are not the same thing. `.get(column) or ''`
                # made them identical, and _coerce turns '' into None, so an
                # archive taken before a column existed passed None explicitly
                # for it. That happens to survive today only because SQLAlchemy
                # treats an explicitly-None attribute as unset and fires the
                # column default anyway - verified, sell_unit arrives as 'base'.
                # Leaning on that is a trap: it rescues defaulted columns and
                # nothing else, so the day a NOT NULL column without a default
                # is added, every older archive stops importing. Leave a column
                # the archive does not carry out of the insert entirely.
                if column not in record:
                    continue
                raw = (record.get(column) or '').strip()
                if column in FK_TARGETS:
                    if raw == '':
                        values[column] = None
                        continue
                    mapped = id_map[FK_TARGETS[column]].get(raw)
                    if mapped is None:
                        # Parent row absent from the archive. Drop the reference if the
                        # column is optional, otherwise skip the orphaned row entirely.
                        col = getattr(model, column, None)
                        if col is not None and getattr(col, 'nullable', True) is False:
                            skip = True
                            break
                        values[column] = None
                    else:
                        values[column] = mapped
                else:
                    values[column] = _coerce(model, column, raw)
            if skip:
                continue

            values['business_id'] = business_id
            # SaleItem and PurchaseOrderItem reach their tenant through a parent
            if not hasattr(model, 'business_id'):
                values.pop('business_id', None)

            row = model(**values)
            db.session.add(row)
            db.session.flush()  # assign the new primary key
            if old_id:
                id_map[table_name][old_id] = row.id
            written[table_name] += 1

    return written
