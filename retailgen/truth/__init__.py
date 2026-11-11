"""Builds the complete clean 'truth' world, then checks it is internally consistent.

Defects are only added later, by the source emulators, so these checks prove that every
inconsistency in the output files was put there deliberately (and is in the manifest).
"""
from dataclasses import dataclass

import pandas as pd

from .masterdata import generate_fx, generate_stores, generate_catalog, generate_promotions
from .customers import generate_customers, generate_crm_changes
from .online import generate_online
from .pos import generate_pos
from .web import generate_clickstream
from .inventory import generate_inventory


@dataclass
class Truth:
    fx: pd.DataFrame
    stores: pd.DataFrame
    store_events: list
    categories: pd.DataFrame
    suppliers: pd.DataFrame
    products: pd.DataFrame
    price_history: pd.DataFrame
    promotions: pd.DataFrame
    customers: pd.DataFrame
    addresses: pd.DataFrame
    customer_events: pd.DataFrame
    address_events: pd.DataFrame
    deleted_customers: set
    orders: pd.DataFrame
    order_lines: pd.DataFrame
    payments: pd.DataFrame
    shipments: pd.DataFrame
    returns: pd.DataFrame
    pos_lines: pd.DataFrame
    clickstream: pd.DataFrame
    inventory: pd.DataFrame


def build_truth(cfg, rng, log=print) -> Truth:
    log("truth: master data")
    fx = generate_fx(cfg, rng)
    stores, store_events = generate_stores(cfg, rng)
    categories, suppliers, products, price_history = generate_catalog(cfg, rng)
    promotions = generate_promotions(cfg)
    log("truth: customers")
    customers, addresses = generate_customers(cfg, rng)
    log("truth: online orders")
    orders, lines, payments, shipments, returns = generate_online(
        cfg, rng, customers, addresses, products, price_history, promotions, fx)
    log("truth: point of sale")
    pos = generate_pos(cfg, rng, stores, store_events, customers, products, price_history, promotions,
                       fx, orders, lines, returns)
    log("truth: CRM changes")
    last = pd.concat([orders[["customer_id", "order_ts"]].rename(columns={"order_ts": "ts"}),
                      pos[["customer_id", "utc_ts"]].rename(columns={"utc_ts": "ts"})]).dropna()
    last_activity = last.groupby("customer_id")["ts"].max()
    cust_ev, addr_ev, deleted = generate_crm_changes(cfg, rng, customers, addresses, last_activity)
    log("truth: clickstream")
    clicks = generate_clickstream(cfg, rng, orders, lines, customers, products, price_history)
    log("truth: inventory")
    inventory = generate_inventory(cfg, rng, stores, store_events, products)
    t = Truth(fx, stores, store_events, categories, suppliers, products, price_history, promotions,
              customers, addresses, cust_ev, addr_ev, deleted, orders, lines, payments, shipments,
              returns, pos, clicks, inventory)
    check_truth(t)
    return t


def check_truth(t: Truth):
    """Referential and arithmetic soundness of the clean world. Raises on any violation."""
    def need(cond, msg):
        if not cond:
            raise AssertionError(f"truth check failed: {msg}")

    cust = set(t.customers["customer_id"])
    skus = set(t.products["sku"])
    need(t.customers["customer_id"].is_unique, "customer ids unique")
    need(t.customers["email"].is_unique, "customer emails unique")
    need(t.customers[["first_name", "last_name", "email"]].notna().all().all(), "customer names present")
    need(set(t.addresses["customer_id"]) <= cust, "addresses -> customers")
    need(set(t.orders["customer_id"].dropna()) <= cust, "orders -> customers")
    need(set(t.order_lines["order_id"]) <= set(t.orders["order_id"]), "lines -> orders")
    need(set(t.order_lines["sku"]) <= skus, "lines -> products")
    need(set(t.pos_lines["sku"]) <= skus, "pos -> products")
    need(set(t.pos_lines["customer_id"].dropna()) <= cust, "pos -> customers")
    need(set(t.payments["order_id"]) <= set(t.orders["order_id"]), "payments -> orders")
    need(set(t.returns["order_id"]) <= set(t.orders["order_id"]), "returns -> orders")
    need(t.pos_lines["txn_id"].notna().all(), "pos txn ids assigned")
    need(not t.pos_lines.duplicated(["txn_id", "line_no"]).any(), "pos (txn, line) unique")
    need(t.order_lines["unit_price"].gt(0).all(), "online prices positive")
    sub = t.order_lines.groupby("order_id")["gross"].sum().round(2)
    need((sub.reindex(t.orders["order_id"]).to_numpy() - t.orders["subtotal"].to_numpy()).__abs__().max() < 0.011,
         "order subtotal = sum of line gross")
    comp = (t.orders["subtotal"] - t.orders["discount_total"] + t.orders["tax_total"] + t.orders["shipping_fee"]).round(2)
    need(((comp - t.orders["order_total"]).abs() < 0.011).all(), "order total = components")
    need((t.shipments["delivered_at"] >= t.shipments["shipped_at"]).all(), "delivered after shipped")
    ph = t.price_history.sort_values(["sku", "valid_from"])
    nxt = ph.groupby("sku")["valid_from"].shift(-1)
    need(((ph["valid_to"] == nxt) | (ph["valid_to"].isna() & nxt.isna())).all(), "price history contiguous")
    need(t.clickstream["event_id"].is_unique, "click event ids unique")
