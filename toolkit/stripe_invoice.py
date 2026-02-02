#!/usr/bin/env python3
"""
Stripe Invoice Generator for AI Agents
Zero-setup invoice creation and payment link generation.
"""

import os
import sys
from datetime import datetime, timedelta

try:
    import stripe
except ImportError:
    print("Error: stripe package not installed")
    print("Install with: pip install stripe")
    sys.exit(1)


class AgentInvoice:
    """Simple invoice generator using Stripe API."""
    
    def __init__(self, api_key: str = None):
        """Initialize with Stripe API key (or from env)."""
        self.api_key = api_key or os.getenv("STRIPE_SECRET_KEY")
        if not self.api_key:
            raise ValueError("Stripe API key required (env: STRIPE_SECRET_KEY)")
        stripe.api_key = self.api_key
    
    def create_invoice(
        self,
        customer_email: str,
        line_items: list,
        due_days: int = 14,
        memo: str = None
    ) -> dict:
        """
        Create a Stripe invoice and return payment details.
        
        Args:
            customer_email: Client email address
            line_items: List of dicts with 'description', 'amount', 'quantity'
                       Example: [{"description": "API Development", "amount": 150000, "quantity": 1}]
                       (amount in cents: $1500.00 = 150000)
            due_days: Days until invoice is due (default 14)
            memo: Optional note to include
        
        Returns:
            dict with invoice_id, payment_url, total_amount, due_date
        """
        # Create or retrieve customer
        try:
            customer = stripe.Customer.create(email=customer_email)
        except stripe.error.StripeError as e:
            # Customer might already exist
            customers = stripe.Customer.list(email=customer_email, limit=1)
            if customers.data:
                customer = customers.data[0]
            else:
                raise e
        
        # Create invoice
        invoice = stripe.Invoice.create(
            customer=customer.id,
            collection_method='send_invoice',
            days_until_due=due_days,
            description=memo
        )
        
        # Add line items
        for item in line_items:
            stripe.InvoiceItem.create(
                customer=customer.id,
                invoice=invoice.id,
                description=item['description'],
                amount=item['amount'],
                quantity=item.get('quantity', 1)
            )
        
        # Finalize invoice
        invoice = stripe.Invoice.finalize_invoice(invoice.id)
        
        return {
            'invoice_id': invoice.id,
            'payment_url': invoice.hosted_invoice_url,
            'total_amount': invoice.total / 100,  # Convert cents to dollars
            'due_date': datetime.fromtimestamp(invoice.due_date).strftime('%Y-%m-%d'),
            'status': invoice.status
        }
    
    def create_payment_link(
        self,
        description: str,
        amount: int,
        currency: str = 'usd'
    ) -> str:
        """
        Create a simple payment link for one-time payment.
        
        Args:
            description: What the payment is for
            amount: Amount in cents ($100.00 = 10000)
            currency: Currency code (default 'usd')
        
        Returns:
            Payment link URL
        """
        price = stripe.Price.create(
            unit_amount=amount,
            currency=currency,
            product_data={'name': description}
        )
        
        link = stripe.PaymentLink.create(
            line_items=[{'price': price.id, 'quantity': 1}]
        )
        
        return link.url


def main():
    """CLI usage example."""
    if len(sys.argv) < 4:
        print("Usage: stripe_invoice.py <customer_email> <description> <amount_usd>")
        print("Example: stripe_invoice.py client@example.com 'API Development' 1500")
        sys.exit(1)
    
    email = sys.argv[1]
    description = sys.argv[2]
    amount_usd = float(sys.argv[3])
    amount_cents = int(amount_usd * 100)
    
    invoicer = AgentInvoice()
    
    # Option 1: Payment link (simplest)
    print(f"\n🔗 Payment Link Method:")
    link = invoicer.create_payment_link(description, amount_cents)
    print(f"   Send this link to client: {link}")
    
    # Option 2: Formal invoice (for tracking)
    print(f"\n📄 Invoice Method:")
    invoice = invoicer.create_invoice(
        customer_email=email,
        line_items=[{
            'description': description,
            'amount': amount_cents,
            'quantity': 1
        }],
        due_days=14
    )
    print(f"   Invoice ID: {invoice['invoice_id']}")
    print(f"   Payment URL: {invoice['payment_url']}")
    print(f"   Amount: ${invoice['total_amount']:.2f}")
    print(f"   Due: {invoice['due_date']}")
    print(f"   Status: {invoice['status']}")


if __name__ == '__main__':
    main()
