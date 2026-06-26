from app import create_app
from extensions import db
from sales.models import Sale
import sys

app = create_app()
app.config['TESTING'] = True
app.config['WTF_CSRF_ENABLED'] = False

with app.app_context():
    client = app.test_client()
    
    print("Verifying /reports/sales...")
    try:
        response = client.get('/reports/sales')
        if response.status_code == 200:
            print("SUCCESS: /reports/sales returned 200 OK")
        else:
            print(f"FAILURE: /reports/sales returned {response.status_code}")
            print(response.data.decode('utf-8')[:500])
            sys.exit(1)
    except Exception as e:
        print(f"CRASH: /reports/sales crashed with {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print("\nVerifying /sales/bulk_action (export_csv)...")
    sales = Sale.query.limit(1).all()
    if not sales:
        print("WARNING: No sales found to test bulk export. Skipping.")
    else:
        sale_id = sales[0].id
        try:
            response = client.post('/sales/bulk_action', data={
                'action': 'export_csv',
                'sale_ids': [sale_id]
            })
            if response.status_code == 200 and response.mimetype == 'text/csv':
                print("SUCCESS: /sales/bulk_action (export_csv) returned 200 OK and CSV mime type")
            else:
                print(f"FAILURE: /sales/bulk_action returned {response.status_code} mime {response.mimetype}")
                print(response.data.decode('utf-8')[:500])
                sys.exit(1)
        except Exception as e:
            print(f"CRASH: /sales/bulk_action crashed with {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

print("\nAll verifications passed.")
