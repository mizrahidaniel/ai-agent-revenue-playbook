"""
Billing Engine - Usage tracking, invoicing, and payment collection for AI agents.

Supports:
- Usage metering (API calls, compute time, data processed)
- Automatic invoice generation
- Recurring billing (monthly, usage-based, hybrid)
- Payment retry logic
- Cost projection
"""

import os
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import stripe

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "sk_test_...")


class UsageTracker:
    """Track billable usage events with SQLite backend."""
    
    def __init__(self, db_path: str = "usage.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialize usage tracking database."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id TEXT NOT NULL,
                service TEXT NOT NULL,
                quantity REAL NOT NULL,
                unit TEXT NOT NULL,
                unit_price REAL NOT NULL,
                metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id TEXT NOT NULL,
                stripe_invoice_id TEXT,
                amount_cents INTEGER NOT NULL,
                status TEXT NOT NULL,
                period_start TIMESTAMP,
                period_end TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                paid_at TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
    
    def track_event(self, customer_id: str, service: str, quantity: float, 
                   unit: str, unit_price: float, metadata: Dict = None):
        """Record a billable usage event.
        
        Examples:
        - track_event("cust_123", "api_calls", 1000, "calls", 0.01)
        - track_event("cust_456", "compute_time", 3.5, "hours", 15.00)
        """
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO usage_events 
            (customer_id, service, quantity, unit, unit_price, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (customer_id, service, quantity, unit, unit_price, 
              json.dumps(metadata) if metadata else None))
        conn.commit()
        conn.close()
    
    def get_unbilled_usage(self, customer_id: str, 
                          start_date: Optional[datetime] = None) -> List[Dict]:
        """Get all unbilled usage for a customer."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if start_date:
            cursor.execute("""
                SELECT id, service, quantity, unit, unit_price, created_at
                FROM usage_events
                WHERE customer_id = ? AND created_at >= ?
                ORDER BY created_at
            """, (customer_id, start_date.isoformat()))
        else:
            cursor.execute("""
                SELECT id, service, quantity, unit, unit_price, created_at
                FROM usage_events
                WHERE customer_id = ?
                ORDER BY created_at
            """, (customer_id,))
        
        events = []
        for row in cursor.fetchall():
            events.append({
                "id": row[0],
                "service": row[1],
                "quantity": row[2],
                "unit": row[3],
                "unit_price": row[4],
                "created_at": row[5],
                "line_total": row[2] * row[4]
            })
        
        conn.close()
        return events
    
    def calculate_total(self, customer_id: str, 
                       start_date: Optional[datetime] = None) -> float:
        """Calculate total unbilled amount for a customer."""
        events = self.get_unbilled_usage(customer_id, start_date)
        return sum(e["line_total"] for e in events)


class BillingEngine:
    """Automated billing with Stripe integration."""
    
    def __init__(self, db_path: str = "usage.db"):
        self.tracker = UsageTracker(db_path)
    
    def generate_invoice(self, customer_id: str, customer_email: str,
                        billing_period_days: int = 30) -> Dict:
        """Generate invoice for usage in billing period.
        
        Returns:
        {
            "invoice_id": "in_...",
            "amount_cents": 15000,
            "line_items": [...],
            "payment_url": "https://invoice.stripe.com/i/..."
        }
        """
        period_end = datetime.now()
        period_start = period_end - timedelta(days=billing_period_days)
        
        # Get usage events
        events = self.tracker.get_unbilled_usage(customer_id, period_start)
        
        if not events:
            return {"error": "No unbilled usage found"}
        
        # Aggregate by service
        line_items = {}
        for event in events:
            service = event["service"]
            if service not in line_items:
                line_items[service] = {
                    "quantity": 0,
                    "unit": event["unit"],
                    "unit_price": event["unit_price"],
                    "total": 0
                }
            line_items[service]["quantity"] += event["quantity"]
            line_items[service]["total"] += event["line_total"]
        
        # Create Stripe invoice
        try:
            # Get or create customer
            customers = stripe.Customer.list(email=customer_email, limit=1)
            if customers.data:
                stripe_customer = customers.data[0]
            else:
                stripe_customer = stripe.Customer.create(
                    email=customer_email,
                    metadata={"agent_customer_id": customer_id}
                )
            
            # Create invoice
            invoice = stripe.Invoice.create(
                customer=stripe_customer.id,
                auto_advance=False,  # Don't auto-finalize
                collection_method="send_invoice",
                days_until_due=14
            )
            
            # Add line items
            for service, item in line_items.items():
                stripe.InvoiceItem.create(
                    customer=stripe_customer.id,
                    invoice=invoice.id,
                    amount=int(item["total"] * 100),  # Convert to cents
                    currency="usd",
                    description=f"{service}: {item['quantity']} {item['unit']} @ ${item['unit_price']}/{item['unit']}"
                )
            
            # Finalize and send
            invoice = stripe.Invoice.finalize_invoice(invoice.id)
            invoice = stripe.Invoice.send_invoice(invoice.id)
            
            # Record in local DB
            conn = sqlite3.connect(self.tracker.db_path)
            conn.execute("""
                INSERT INTO invoices 
                (customer_id, stripe_invoice_id, amount_cents, status, period_start, period_end)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (customer_id, invoice.id, invoice.amount_due, invoice.status,
                  period_start.isoformat(), period_end.isoformat()))
            conn.commit()
            conn.close()
            
            return {
                "invoice_id": invoice.id,
                "amount_cents": invoice.amount_due,
                "line_items": line_items,
                "payment_url": invoice.hosted_invoice_url,
                "due_date": invoice.due_date
            }
        
        except stripe.error.StripeError as e:
            return {"error": str(e)}
    
    def setup_recurring_billing(self, customer_email: str, 
                               plan_amount_cents: int,
                               interval: str = "month") -> Dict:
        """Set up subscription for recurring monthly billing.
        
        Args:
            customer_email: Customer's email
            plan_amount_cents: Monthly subscription amount (e.g., 5000 = $50)
            interval: "month" or "year"
        """
        try:
            # Get or create customer
            customers = stripe.Customer.list(email=customer_email, limit=1)
            if customers.data:
                stripe_customer = customers.data[0]
            else:
                stripe_customer = stripe.Customer.create(email=customer_email)
            
            # Create price
            price = stripe.Price.create(
                unit_amount=plan_amount_cents,
                currency="usd",
                recurring={"interval": interval},
                product_data={"name": f"Agent Service - ${plan_amount_cents/100}/{interval}"}
            )
            
            # Create subscription
            subscription = stripe.Subscription.create(
                customer=stripe_customer.id,
                items=[{"price": price.id}],
                payment_behavior="default_incomplete",
                payment_settings={"save_default_payment_method": "on_subscription"},
                expand=["latest_invoice.payment_intent"]
            )
            
            return {
                "subscription_id": subscription.id,
                "client_secret": subscription.latest_invoice.payment_intent.client_secret,
                "status": subscription.status
            }
        
        except stripe.error.StripeError as e:
            return {"error": str(e)}
    
    def check_payment_status(self, invoice_id: str) -> Dict:
        """Check if invoice has been paid."""
        try:
            invoice = stripe.Invoice.retrieve(invoice_id)
            
            # Update local DB if paid
            if invoice.status == "paid":
                conn = sqlite3.connect(self.tracker.db_path)
                conn.execute("""
                    UPDATE invoices 
                    SET status = ?, paid_at = ?
                    WHERE stripe_invoice_id = ?
                """, ("paid", datetime.now().isoformat(), invoice_id))
                conn.commit()
                conn.close()
            
            return {
                "invoice_id": invoice.id,
                "status": invoice.status,
                "amount_paid": invoice.amount_paid,
                "amount_due": invoice.amount_due
            }
        
        except stripe.error.StripeError as e:
            return {"error": str(e)}


class CostProjector:
    """Project costs and margins before committing to pricing."""
    
    @staticmethod
    def project_api_service(expected_calls_per_month: int,
                           api_cost_per_call: float,
                           proposed_price_per_1k: float) -> Dict:
        """Project margins for API-based service.
        
        Example:
        project_api_service(
            expected_calls_per_month=50000,
            api_cost_per_call=0.002,  # $0.002 per OpenAI call
            proposed_price_per_1k=5.0  # Charge $5/1k calls
        )
        """
        monthly_cost = expected_calls_per_month * api_cost_per_call
        monthly_revenue = (expected_calls_per_month / 1000) * proposed_price_per_1k
        monthly_profit = monthly_revenue - monthly_cost
        margin_percent = (monthly_profit / monthly_revenue * 100) if monthly_revenue > 0 else 0
        
        return {
            "calls_per_month": expected_calls_per_month,
            "monthly_cost": round(monthly_cost, 2),
            "monthly_revenue": round(monthly_revenue, 2),
            "monthly_profit": round(monthly_profit, 2),
            "margin_percent": round(margin_percent, 1),
            "recommendation": "Viable" if margin_percent >= 50 else "Thin margins - increase price or reduce costs"
        }
    
    @staticmethod
    def project_compute_service(hours_per_month: int,
                               compute_cost_per_hour: float,
                               hourly_rate: float) -> Dict:
        """Project margins for compute-intensive service."""
        monthly_cost = hours_per_month * compute_cost_per_hour
        monthly_revenue = hours_per_month * hourly_rate
        monthly_profit = monthly_revenue - monthly_cost
        margin_percent = (monthly_profit / monthly_revenue * 100) if monthly_revenue > 0 else 0
        
        return {
            "hours_per_month": hours_per_month,
            "monthly_cost": round(monthly_cost, 2),
            "monthly_revenue": round(monthly_revenue, 2),
            "monthly_profit": round(monthly_profit, 2),
            "margin_percent": round(margin_percent, 1),
            "recommendation": "Viable" if margin_percent >= 60 else "Increase hourly rate or optimize compute"
        }


# Example usage
if __name__ == "__main__":
    # Usage tracking
    tracker = UsageTracker()
    tracker.track_event("cust_001", "api_calls", 5000, "calls", 0.01)
    tracker.track_event("cust_001", "data_processing", 2.5, "GB", 5.00)
    
    print("Unbilled usage:", tracker.get_unbilled_usage("cust_001"))
    print("Total amount:", tracker.calculate_total("cust_001"))
    
    # Cost projection
    projection = CostProjector.project_api_service(
        expected_calls_per_month=100000,
        api_cost_per_call=0.002,
        proposed_price_per_1k=10.0
    )
    print("\nAPI Service Projection:", json.dumps(projection, indent=2))
    
    # Billing (requires Stripe API key)
    # engine = BillingEngine()
    # invoice = engine.generate_invoice("cust_001", "customer@example.com")
    # print("\nInvoice:", json.dumps(invoice, indent=2))
