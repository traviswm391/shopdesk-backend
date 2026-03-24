import stripe
from app.config import settings

stripe.api_key = settings.stripe_secret_key

PRICE_ID = None  # Set after creating price in Stripe

MONTHLY_PRICE = 29900  # $299.00 in cents


def create_customer(email: str, name: str) -> str:
    customer = stripe.Customer.create(email=email, name=name)
    return customer.id


def create_checkout_session(customer_id: str, shop_id: str, success_url: str, cancel_url: str) -> str:
    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": _get_or_create_price().id, "quantity": 1}],
        mode="subscription",
        success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=cancel_url,
        metadata={"shop_id": shop_id},
        subscription_data={"metadata": {"shop_id": shop_id}}
    )
    return session.url


def _get_or_create_price():
    products = stripe.Product.list(active=True)
    for product in products.data:
        if product.name == "ShopDesk AI Monthly":
            prices = stripe.Price.list(product=product.id, active=True)
            if prices.data:
                return prices.data[0]
    product = stripe.Product.create(name="ShopDesk AI Monthly")
    return stripe.Price.create(product=product.id, unit_amount=MONTHLY_PRICE, currency="usd", recurring={"interval": "month"})


def create_billing_portal_session(customer_id: str, return_url: str) -> str:
    session = stripe.billing_portal.Session.create(customer=customer_id, return_url=return_url)
    return session.url


def cancel_subscription(subscription_id: str):
    stripe.Subscription.cancel(subscription_id)


def construct_webhook_event(payload: bytes, sig_header: str):
    return stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
