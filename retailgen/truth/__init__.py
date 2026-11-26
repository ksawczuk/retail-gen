"""Builds the complete clean 'truth' world, then checks it is internally consistent.

Defects are only added later, by the source emulators, so these checks prove that every
inconsistency in the output files was put there deliberately (and is in the manifest).
"""
from dataclasses import dataclass

import pandas as pd

from .masterdata import generate_fx, generate_stores, generate_catalog, generate_promotions
from .customers import generate_customers, generate_crm_changes
from .online import generate_online, online_channel
from .pos import generate_pos, store_channel
from .web import generate_clickstream
from .inventory import generate_inventory
from .baskets import BasketBuilder
from .demand import DemandEngine
from .lifecycle import CustomerLifecycle
from .seasonality import Seasonality
from .campaigns import CampaignContext, calendar, email_campaigns
from .campaign_truth import (assignment_table, campaigns_table, code_audiences, email_clicks, groups_by_campaign,
                             prospect_customers_table, prospect_tags, truth_table)
from .engagement import engagement_events
from .signups import apply_signup_campaigns


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
    campaigns: pd.DataFrame
    campaign_assignment: pd.DataFrame
    campaign_truth: pd.DataFrame
    prospect_customers: pd.DataFrame
    engagement_events: pd.DataFrame


def build_truth(cfg, rng, log=print) -> Truth:
    log("truth: master data")
    fx = generate_fx(cfg, rng)
    stores, store_events = generate_stores(cfg, rng)
    categories, suppliers, products, price_history = generate_catalog(cfg, rng)
    promotions = generate_promotions(cfg)
    log("truth: customers")
    customers, addresses = generate_customers(cfg, rng)
    log("truth: signup campaigns")
    specs = calendar()
    customers, addresses, signup = apply_signup_campaigns(cfg, rng, customers, addresses, specs)
    log("truth: lifecycle, campaigns and demand")
    engine, baskets, ctx = build_demand(cfg, rng, customers, products, categories, specs)
    online, store = online_channel(cfg), store_channel(cfg)
    purchases = engine.draw_all([online, store])
    ids = customers["customer_id"].to_numpy()
    audiences = code_audiences(specs, groups_by_campaign(ctx, ids))
    log("truth: online orders")
    orders, lines, payments, shipments, returns = generate_online(
        cfg, rng, customers, addresses, price_history, promotions, fx, engine.days, purchases[online.name], baskets,
        audiences)
    log("truth: point of sale")
    pos = generate_pos(cfg, rng, stores, store_events, customers, price_history, promotions,
                       fx, orders, lines, returns, engine.days, purchases[store.name], baskets)
    log("truth: CRM changes")
    last = pd.concat([orders[["customer_id", "order_ts"]].rename(columns={"order_ts": "ts"}),
                      pos[["customer_id", "utc_ts"]].rename(columns={"utc_ts": "ts"})]).dropna()
    last_activity = last.groupby("customer_id")["ts"].max()
    cust_ev, addr_ev, deleted = generate_crm_changes(cfg, rng, customers, addresses, last_activity)
    log("truth: email events")
    engagement = engagement_events(rng, engine.days, ids, ctx.sends, signup.sends)
    campaign_rows = campaigns_table(specs)
    prospects = prospect_customers_table(signup)
    log("truth: clickstream")
    clicks = generate_clickstream(cfg, rng, orders, lines, customers, products, price_history, engine,
                                  email_clicks(engagement, campaign_rows), prospect_tags(prospects, campaign_rows))
    log("truth: inventory")
    inventory = generate_inventory(cfg, rng, stores, store_events, products)
    log("truth: campaign answer key")
    assignment = assignment_table(ctx, ids, engine.days, signup)
    effects = truth_table(rng, specs, ctx, signup, purchases, engine.days, ids, orders, pos)
    t = Truth(fx, stores, store_events, categories, suppliers, products, price_history, promotions,
              customers, addresses, cust_ev, addr_ev, deleted, orders, lines, payments, shipments,
              returns, pos, clicks, inventory, campaign_rows, assignment, effects, prospects, engagement)
    check_truth(t)
    return t


def build_demand(cfg, rng, customers, products, categories, specs=()):
    """Wire the lifecycle, seasonality, email campaigns, demand engine and basket builder for the whole window.
    Called by build_truth after the signup campaigns; returns (engine, baskets, campaign context)."""
    days = pd.date_range(cfg.history_start, cfg.increment_end, freq="D")
    category_names = categories.loc[categories["level"] == 2, "category_name"].tolist()
    seasons = Seasonality(days, category_names)
    lifecycle = CustomerLifecycle.build(rng, customers, len(category_names))
    ctx = CampaignContext(rng, days, customers["created_at"].to_numpy().astype("datetime64[ns]"),
                          customers["marketing_opt_in"].to_numpy(bool),
                          customers["loyalty_join_at"].to_numpy().astype("datetime64[ns]"), lifecycle)
    modifiers = email_campaigns(specs, ctx)
    engine = DemandEngine(rng, days, customers["created_at"], customers["activity"], lifecycle, seasons, modifiers)
    promoted = {s.campaign_id: s.categories for s in specs if s.categories}
    cross_sell = [s.campaign_id for s in specs if s.kind == "canvas"]
    baskets = BasketBuilder(products, seasons, lifecycle.preferences, lifecycle.basket_mult, promoted, cross_sell)
    return engine, baskets, ctx


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
    need(set(t.campaign_assignment["customer_id"]) <= cust, "campaign audiences -> customers")
    need(set(t.prospect_customers["customer_id"]) <= cust, "Prospects customers -> customers")
    need(set(t.engagement_events["customer_id"]) <= cust, "email events -> customers")
