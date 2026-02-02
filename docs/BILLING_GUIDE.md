# Billing Engine Guide

Complete guide to using the billing engine for automated revenue collection.

## Setup

```bash
pip install stripe
export STRIPE_SECRET_KEY="sk_test_..."  # Get from dashboard.stripe.com
```

## Usage Tracking

Track every billable action your agent performs:

```python
from toolkit.billing_engine import UsageTracker

tracker = UsageTracker("my_business.db")

# Track API calls
tracker.track_event(
    customer_id="cust_techstartup",
    service="api_development",
    quantity=1,  # 1 API endpoint
    unit="endpoint",
    unit_price=500.00,
    metadata={"project": "user_auth_api"}
)

# Track compute time
tracker.track_event(
    customer_id="cust_dataco",
    service="data_processing",
    quantity=4.5,  # 4.5 hours
    unit="hours",
    unit_price=25.00,
    metadata={"dataset": "customer_analytics"}
)

# Track data volume
tracker.track_event(
    customer_id="cust_analytics",
    service="etl_pipeline",
    quantity=150,  # 150 GB processed
    unit="GB",
    unit_price=0.10
)
```

## Automatic Invoicing

Generate and send invoices automatically:

```python
from toolkit.billing_engine import BillingEngine

engine = BillingEngine("my_business.db")

# Generate invoice for the past 30 days
invoice = engine.generate_invoice(
    customer_id="cust_techstartup",
    customer_email="billing@techstartup.com",
    billing_period_days=30
)

print(f"Invoice created: {invoice['invoice_id']}")
print(f"Amount: ${invoice['amount_cents']/100:.2f}")
print(f"Payment URL: {invoice['payment_url']}")

# Email this URL to your customer
# They pay online via Stripe's hosted page
```

### Invoice Output

```json
{
  "invoice_id": "in_1234567890",
  "amount_cents": 150000,
  "line_items": {
    "api_development": {
      "quantity": 3,
      "unit": "endpoint",
      "unit_price": 500.0,
      "total": 1500.0
    }
  },
  "payment_url": "https://invoice.stripe.com/i/acct_...",
  "due_date": 1738454400
}
```

## Recurring Billing (Subscriptions)

For predictable monthly revenue:

```python
# Set up $199/month subscription
subscription = engine.setup_recurring_billing(
    customer_email="billing@startup.com",
    plan_amount_cents=19900,  # $199
    interval="month"
)

print(f"Subscription ID: {subscription['subscription_id']}")
print(f"Status: {subscription['status']}")

# Customer sets up payment method via client_secret
# Then charges happen automatically every month
```

## Hybrid Model: Base + Usage

Best of both worlds - predictable base + usage overage:

```python
# Monthly base: $99
# Usage charges: $0.01/API call over 10,000

# 1. Set up base subscription ($99/month)
subscription = engine.setup_recurring_billing(
    customer_email="billing@customer.com",
    plan_amount_cents=9900,
    interval="month"
)

# 2. Track usage events as they happen
for i in range(15000):  # Customer made 15k calls
    tracker.track_event(
        customer_id="cust_customer",
        service="api_calls",
        quantity=1,
        unit="call",
        unit_price=0.01 if i >= 10000 else 0  # Free up to 10k
    )

# 3. At end of month, invoice overage charges
overage_invoice = engine.generate_invoice(
    customer_id="cust_customer",
    customer_email="billing@customer.com"
)
# They pay $99 via subscription + $50 overage invoice
```

## Payment Verification

Check if invoices have been paid:

```python
status = engine.check_payment_status("in_1234567890")

if status["status"] == "paid":
    print(f"✓ Received ${status['amount_paid']/100:.2f}")
else:
    print(f"⏳ Waiting for payment: ${status['amount_due']/100:.2f}")
```

## Cost Projection (Before Pricing)

Never commit to pricing without knowing your margins:

```python
from toolkit.billing_engine import CostProjector

# Scenario: API service using OpenAI
projection = CostProjector.project_api_service(
    expected_calls_per_month=50000,
    api_cost_per_call=0.002,  # Your OpenAI cost
    proposed_price_per_1k=5.0  # What you'll charge customer
)

print(projection)
```

### Output:
```json
{
  "calls_per_month": 50000,
  "monthly_cost": 100.0,      // Your cost
  "monthly_revenue": 250.0,    // Customer pays
  "monthly_profit": 150.0,     // Your profit
  "margin_percent": 60.0,      // Healthy margin
  "recommendation": "Viable"
}
```

**Rule of thumb:**
- **API services:** 50%+ margin (you're reselling compute)
- **Custom code:** 70%+ margin (your time is the cost)
- **Data processing:** 60%+ margin (balance compute + complexity)

## Webhooks for Automation

Handle Stripe events automatically:

```python
# In your webhook endpoint (Flask/FastAPI/etc)
import stripe

@app.post("/stripe-webhook")
def handle_webhook(request):
    payload = request.body
    sig_header = request.headers['Stripe-Signature']
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
        
        if event['type'] == 'invoice.paid':
            invoice_id = event['data']['object']['id']
            # Mark as paid in your DB
            engine.check_payment_status(invoice_id)
            
        elif event['type'] == 'invoice.payment_failed':
            # Handle failed payment (retry, notify customer)
            pass
            
        return {'status': 'success'}
    
    except ValueError:
        return {'error': 'Invalid payload'}, 400
```

## Complete Example: API Service Business

```python
from toolkit.billing_engine import UsageTracker, BillingEngine, CostProjector

# Step 1: Project margins BEFORE building
projection = CostProjector.project_api_service(
    expected_calls_per_month=100000,
    api_cost_per_call=0.002,
    proposed_price_per_1k=10.0
)
print(f"Projected margin: {projection['margin_percent']}%")

if projection['margin_percent'] < 50:
    print("❌ Margins too thin - adjust pricing")
    exit(1)

# Step 2: Track usage as you provide service
tracker = UsageTracker()
engine = BillingEngine()

def process_api_request(customer_id: str):
    # Do the actual work...
    result = call_openai_api()
    
    # Track it
    tracker.track_event(
        customer_id=customer_id,
        service="api_calls",
        quantity=1,
        unit="call",
        unit_price=0.01  # $10 per 1k calls
    )
    
    return result

# Step 3: Invoice monthly
def monthly_billing_job():
    customers = ["cust_001", "cust_002", "cust_003"]
    
    for customer_id in customers:
        # Get customer email from your DB
        email = get_customer_email(customer_id)
        
        # Generate and send invoice
        invoice = engine.generate_invoice(
            customer_id=customer_id,
            customer_email=email,
            billing_period_days=30
        )
        
        if "error" not in invoice:
            print(f"✓ Invoiced {customer_id}: ${invoice['amount_cents']/100:.2f}")
            # Send email with invoice['payment_url']
        else:
            print(f"⚠ No charges for {customer_id}")
```

## Best Practices

### 1. Always Track Usage Immediately
```python
# ✅ Good: Track right after work
result = do_work()
tracker.track_event(...)

# ❌ Bad: Track later from logs (easy to miss events)
```

### 2. Include Metadata for Debugging
```python
tracker.track_event(
    customer_id="cust_123",
    service="api_dev",
    quantity=1,
    unit="endpoint",
    unit_price=500,
    metadata={
        "project": "auth_api",
        "started": "2026-01-15",
        "completed": "2026-01-20",
        "github_pr": "https://github.com/..."
    }
)
```

### 3. Test in Stripe Test Mode First
```bash
# Use test keys for development
export STRIPE_SECRET_KEY="sk_test_..."

# Switch to live keys only when ready for real money
export STRIPE_SECRET_KEY="sk_live_..."
```

### 4. Set Up Webhook Monitoring
- Use Stripe CLI for local development: `stripe listen --forward-to localhost:3000/webhook`
- Monitor webhook delivery in Stripe dashboard
- Implement retry logic for failed webhooks

### 5. Handle Edge Cases
```python
# Customer disputes invoice?
# Stripe handles this - just check the dashboard

# Usage spike detection
total = tracker.calculate_total("cust_123")
if total > 1000:  # Over $1000 unbilled
    # Send warning email before invoicing
    notify_customer_of_upcoming_bill(customer_id, total)
```

## What's Next

- **SLA Monitoring** - Track uptime, latency, error rates
- **Auto-refunds** - If SLA breached, refund automatically
- **Multi-currency** - Support EUR, GBP, etc.
- **Tax compliance** - Sales tax, VAT handling (Stripe Tax)

---

**This is production-ready code.** Thousands of SaaS businesses use this exact Stripe workflow. You're not reinventing payments - you're using the industry standard.
