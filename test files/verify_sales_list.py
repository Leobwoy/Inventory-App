from app import create_app
from sales.models import Sale
import sys

app = create_app()
app.config['TESTING'] = True

with app.app_context():
    client = app.test_client()
    print("Verifying /sales/...")
    response = client.get('/sales/')
    content = response.data.decode('utf-8')
    
    if response.status_code == 200:
        if '<th>Customer</th>' in content:
            print("SUCCESS: Customer column header found.")
        else:
            print("FAILURE: Customer column header NOT found.")
            sys.exit(1)
            
        # Optional: check if data is present
        # print(content[:500]) 
    else:
        print(f"FAILURE: /sales/ returned {response.status_code}")
        sys.exit(1)

print("\nSales list verification passed.")
