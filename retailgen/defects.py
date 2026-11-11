"""The defect catalogue: every defect the generator can inject, declared once.

Emitters do the injecting and call `man.record(defect_id, count, keys=..., **detail)`; the
metadata (source, entity, category, description, systemic) lives here. `detail` fills the
`{placeholders}` in a description with run-specific values such as a store id or a date.

This file is as much a spoiler as `answer_key/`: don't read it while working the pipeline.

    systemic=True   a property of the whole feed (a format, a convention), not a sample of rows
"""
import string
from dataclasses import dataclass

CATEGORIES = {
    "business_rule", "cdc", "completeness", "disguised_null", "duplicate", "encoding", "file",
    "format", "identity", "junk", "late_arriving", "referential", "schema_drift", "scd",
    "semantics", "timezone",
}


@dataclass(frozen=True)
class Defect:
    id: str
    source: str
    entity: str
    category: str
    description: str
    systemic: bool = False

    @property
    def placeholders(self) -> set:
        return {f for _, f, _, _ in string.Formatter().parse(self.description) if f}

    def describe(self, **detail) -> str:
        """The description with its placeholders filled; the detail names must match exactly."""
        if set(detail) != self.placeholders:
            raise ValueError(f"{self.id}: description needs {sorted(self.placeholders)}, got {sorted(detail)}")
        return self.description.format(**detail)


def _per_entity(source, entities, name, category, description, systemic=False):
    """The same defect injected into several entities of one source (e.g. full extract and CDC)."""
    return [Defect(f"{source}.{e}.{name}", source, e, category, description, systemic) for e in entities]


CRM_CUSTOMERS = ("customers", "customers_cdc")
CRM_ADDRESSES = ("customer_addresses", "customer_addresses_cdc")

_DEFECTS = [
    # ---------------- CRM: customers (full extract and CDC share one frame builder)
    *_per_entity("crm", CRM_CUSTOMERS, "phone_disguised_null", "disguised_null",
                 "PHONE holds '', 'N/A', 'null' or '-' instead of a number"),
    *_per_entity("crm", CRM_CUSTOMERS, "dob_placeholder", "disguised_null",
                 "unknown DOB written as '', '0000-00-00' or '1900-01-01'", systemic=True),
    *_per_entity("crm", CRM_CUSTOMERS, "dob_mixed_formats", "format",
                 "DOB mixes YYYY-MM-DD, MM/DD/YYYY and DD-Mon-YYYY", systemic=True),
    *_per_entity("crm", CRM_CUSTOMERS, "email_case_whitespace", "format",
                 "EMAIL_ADDR with upper case or stray spaces"),
    *_per_entity("crm", CRM_CUSTOMERS, "opt_in_variants", "format",
                 "OPT_IN uses Y/Yes/1/y and N/No/0/blank", systemic=True),
    *_per_entity("crm", CRM_CUSTOMERS, "created_dt_local_time", "timezone",
                 "CREATED_DT/LAST_MOD_DT are Pacific local time with no offset (docs claim UTC)", systemic=True),
    # CRM: full extract only
    Defect("crm.mojibake_names", "crm", "customers", "encoding",
           "accented names double-encoded (UTF-8 read as Latin-1, e.g. 'ZoÃ«')"),
    Defect("crm.near_duplicate_customers", "crm", "customers", "identity",
           "same real person under two CUST_IDs (nickname, typo, other email, later signup)", systemic=True),
    Defect("crm.employee_accounts", "crm", "customers", "junk",
           "staff accounts (@{domain}) mixed in with customers", systemic=True),
    Defect("crm.exact_duplicate_rows", "crm", "customers", "duplicate",
           "exact duplicate rows in the full extract"),
    Defect("crm.utf8_bom", "crm", "customers", "file", "full extract starts with a UTF-8 BOM"),
    # CRM: addresses
    *_per_entity("crm", CRM_ADDRESSES, "addr_unit_in_line1", "format",
                 "unit number folded into LINE1 with a comma ('Apt 12, 123 Main St')", systemic=True),
    *_per_entity("crm", CRM_ADDRESSES, "addr_embedded_newline", "file",
                 "LINE1 contains a newline inside a quoted CSV field"),
    *_per_entity("crm", CRM_ADDRESSES, "province_variants", "format",
                 "PROV mixes codes, abbreviations and full names", systemic=True),
    *_per_entity("crm", CRM_ADDRESSES, "postal_variants", "format",
                 "POSTAL lower-case / no space / dash variants", systemic=True),
    *_per_entity("crm", CRM_ADDRESSES, "country_variants", "format",
                 "COUNTRY mixes CA/Canada/CAN and US/USA/United States", systemic=True),
    Defect("crm.orphan_addresses", "crm", "customer_addresses", "referential",
           "addresses whose CUST_ID does not exist in any customer file"),
    # CRM: CDC
    Defect("crm.customers_cdc_late_events", "crm", "customers_cdc", "late_arriving",
           "CDC events delivered a day late, after events with higher SEQ_NO"),
    Defect("crm.addresses_cdc_late_events", "crm", "customer_addresses_cdc", "late_arriving",
           "CDC events delivered a day late, after events with higher SEQ_NO"),
    Defect("crm.customers_cdc_unordered", "crm", "customers_cdc", "cdc",
           "rows within each CDC file are not in SEQ_NO order", systemic=True),
    Defect("crm.addresses_cdc_unordered", "crm", "customer_addresses_cdc", "cdc",
           "rows within each CDC file are not in SEQ_NO order", systemic=True),
    Defect("crm.cdc_delete_unknown_key", "crm", "customers_cdc", "cdc",
           "D events for keys that were never inserted"),
    Defect("crm.cdc_multiple_changes_same_batch", "crm", "customers_cdc", "cdc",
           "the same key changes more than once in one daily file", systemic=True),
    Defect("crm.cdc_schema_drift_loyalty_tier", "crm", "customers_cdc", "schema_drift",
           "LOYALTY_TIER column appears from 2026-10-10 onward", systemic=True),

    # ---------------- PIM
    Defect("pim.category_name_noise", "pim", "categories", "format",
           "category names with odd casing or padding"),
    Defect("pim.duplicate_category", "pim", "categories", "identity",
           "category {dup_id} duplicates {src_id}; some products point at each"),
    Defect("pim.duplicate_supplier", "pim", "suppliers", "identity",
           "supplier {dup_id} is {src_id} re-keyed with a variant name"),
    Defect("pim.title_noise", "pim", "products", "format", "product titles with odd casing/padding"),
    Defect("pim.late_arriving_new_skus", "pim", "products", "late_arriving",
           "new SKUs sell 1-4 days before their product record arrives"),
    Defect("pim.price_overlap", "pim", "price_history", "business_rule",
           "price periods overlap: effective_to runs 7 days past the next period's start"),
    Defect("pim.price_inverted_interval", "pim", "price_history", "business_rule",
           "effective_to earlier than effective_from"),
    Defect("pim.price_as_text", "pim", "price_history", "format", "price sent as a '$1,234.56' string"),
    Defect("pim.open_end_tokens", "pim", "price_history", "disguised_null",
           "open-ended periods use null, '9999-12-31' or ''", systemic=True),
    Defect("pim.retroactive_price_changes", "pim", "price_changes", "late_arriving",
           "price change notices that arrive 2-5 days after their effective date"),

    # ---------------- Store ops
    Defect("storeops.missing_snapshot", "storeops", "stores", "file",
           "no store snapshot delivered for {day:%Y-%m-%d}"),
    Defect("storeops.duplicate_snapshot", "storeops", "stores", "file",
           "snapshot for {day:%Y-%m-%d} delivered twice (_retry)"),
    Defect("storeops.store_recoded", "storeops", "stores", "scd",
           "store_code and store_name change for store_id {store_id} on {day:%Y-%m-%d}"),
    Defect("storeops.store_closed", "storeops", "stores", "scd",
           "store closes for store_id {store_id} on {day:%Y-%m-%d}"),
    Defect("storeops.us_date_format", "storeops", "stores", "format",
           "open_date/close_date are MM/DD/YYYY", systemic=True),

    # ---------------- Finance
    Defect("finance.no_weekend_rates", "finance", "fx_rates", "completeness",
           "no rates on weekends/holidays", systemic=True),
    Defect("finance.inverted_rate", "finance", "fx_rates", "business_rule",
           "rate stored as CAD->USD although labelled USD->CAD"),
    Defect("finance.conflicting_duplicate_dates", "finance", "fx_rates", "duplicate",
           "the same date appears twice with different rates"),
    Defect("finance.date_format_drift", "finance", "fx_rates", "schema_drift",
           "daily files write rate_date as YYYY/MM/DD (history file uses YYYY-MM-DD)", systemic=True),

    # ---------------- Promotions
    Defect("promo.json_array_file", "promo", "promotions", "file",
           "promotions arrive as one pretty-printed JSON array (multiLine), re-sent in full on change",
           systemic=True),
    Defect("promo.value_as_text", "promo", "promotions", "format",
           "value is '15%' or '$20.00' text; type tells which", systemic=True),
    Defect("promo.mixed_date_formats", "promo", "promotions", "format",
           "startDate/endDate mix YYYY-MM-DD and MM/DD/YYYY", systemic=True),
    Defect("promo.redemption_on_cancelled_order", "promo", "coupon_redemptions", "business_rule",
           "redemptions not reversed when the order was cancelled"),
    Defect("promo.unknown_code_typo", "promo", "coupon_redemptions", "referential",
           "redeemed code not in the promotions master (a character dropped)"),
    Defect("promo.code_case_whitespace", "promo", "coupon_redemptions", "format",
           "codes with lower case or stray spaces", systemic=True),
    Defect("promo.amount_text_locale", "promo", "coupon_redemptions", "format",
           "discountAmount is text: '$5.00', '5.00', or Quebec '5,00'", systemic=True),

    # ---------------- OMS
    Defect("oms.test_orders", "oms", "orders", "junk",
           "QA test orders (qa+ emails, postal X0X 0X0, qty 9999 or $0.01 lines)"),
    Defect("oms.future_dated_orders", "oms", "orders", "junk",
           "order_ts about 400 days in the future (bad device clock); updated_at is correct"),
    Defect("oms.total_excludes_shipping", "oms", "orders", "business_rule", "order_total omits shipping_fee"),
    Defect("oms.total_off_by_a_cent", "oms", "orders", "business_rule",
           "order_total differs from its components by one cent (rounding)"),
    Defect("oms.lost_order_headers", "oms", "orders", "completeness",
           "orders whose header rows are never delivered at all (their lines are)"),
    Defect("oms.guest_customer_id", "oms", "orders", "disguised_null",
           "guest checkouts have customer_id '', '0', 'GUEST' or null", systemic=True),
    Defect("oms.channel_variants", "oms", "orders", "format",
           "channel spelled web/WEB/Web/app/APP/mobile_app", systemic=True),
    Defect("oms.address_code_variants", "oms", "orders", "format",
           "ship_province/ship_country/ship_postal spelling variants", systemic=True),
    Defect("oms.late_order_versions", "oms", "orders", "late_arriving",
           "order status changes delivered 1-4 days after they happened"),
    Defect("oms.exact_duplicate_orders", "oms", "orders", "duplicate", "exact duplicate rows in the history files"),
    Defect("oms.replayed_batch", "oms", "orders", "duplicate",
           "the {src_day:%Y-%m-%d} orders file is delivered again on {replay_day:%Y-%m-%d}"),
    Defect("oms.schema_drift_shipping_amount", "oms", "orders", "schema_drift",
           "shipping_fee renamed shipping_amount from {day:%Y-%m-%d}", systemic=True),
    Defect("oms.duplicate_order_lines", "oms", "order_lines", "duplicate", "exact duplicate line rows"),
    Defect("oms.orphan_order_lines", "oms", "order_lines", "referential",
           "delivered order lines with no delivered header (lost header, or header still in flight at window end)"),
    Defect("oms.schema_drift_quantity_string", "oms", "order_lines", "schema_drift",
           "quantity changes from int64 to string ('2.0') from {day:%Y-%m-%d}", systemic=True),
    Defect("oms.double_capture", "oms", "payments", "business_rule",
           "the same order captured twice (second capture event two minutes later)"),
    Defect("oms.orphan_payments", "oms", "payments", "referential", "payment events for order ids that don't exist"),
    Defect("oms.delivered_before_shipped", "oms", "shipments", "business_rule", "delivered_at earlier than shipped_at"),
    Defect("oms.carrier_variants", "oms", "shipments", "format", "carrier names spelled several ways", systemic=True),
    Defect("oms.refund_exceeds_charge", "oms", "returns", "business_rule",
           "refund_amount 2-3x what the returned units cost"),

    # ---------------- POS
    Defect("pos.sku_leading_zeros_dropped", "pos", "transactions", "format",
           "SKU lost its leading zeros ('004512' -> '4512')", systemic=True),
    Defect("pos.amounts_in_cents", "pos", "transactions", "semantics",
           "all money columns are integer cents", systemic=True),
    Defect("pos.currency_not_labelled", "pos", "transactions", "semantics",
           "US stores record USD but no currency column exists (docs say CAD)", systemic=True),
    Defect("pos.local_time_no_zone", "pos", "transactions", "semantics",
           "TXN_DATETIME is store-local wall time, no offset", systemic=True),
    Defect("pos.quebec_day_first_dates", "pos", "transactions", "format",
           "Quebec stores write DD/MM/YYYY", systemic=True),
    Defect("pos.returns_negative_qty", "pos", "transactions", "semantics",
           "returns are negative QTY lines in their own baskets", systemic=True),
    Defect("pos.cross_channel_returns", "pos", "transactions", "semantics",
           "in-store returns of online orders (ORIG_ORDER_REF)", systemic=True),
    Defect("pos.loyalty_blank_variants", "pos", "transactions", "semantics",
           "no card scanned is '', '0' or 'NONE'", systemic=True),
    Defect("pos.employee_purchases", "pos", "transactions", "semantics",
           "staff purchases (PROMO STAFF30)", systemic=True),
    Defect("pos.skus_never_in_pim", "pos", "transactions", "referential",
           "store-local SKUs that never appear in the PIM", systemic=True),
    Defect("pos.store_recode", "pos", "transactions", "scd",
           "store {store_id} sends STORE_CODE {store_code} from {day:%Y-%m-%d}", systemic=True),
    Defect("pos.training_transactions", "pos", "transactions", "junk",
           "training-mode baskets (REGISTER_NO 99, CASHIER TRAINING)"),
    Defect("pos.embedded_newline", "pos", "transactions", "file", "DESCRIPTION contains a quoted newline"),
    Defect("pos.offline_store_late_upload", "pos", "transactions", "late_arriving",
           "store {store} was offline; {d5:%m-%d} and {d6:%m-%d} sales arrive in its {d8:%m-%d} file"),
    Defect("pos.malformed_rows", "pos", "transactions", "file",
           "unquoted comma in DESCRIPTION shifts the row by one column"),
    Defect("pos.duplicate_file", "pos", "transactions", "duplicate", "{fname} delivered twice (also as _dup.csv)"),
    Defect("pos.empty_file_then_resend", "pos", "transactions", "file",
           "{fname} arrived empty (0 bytes); the real file is re-sent next day as _resend.csv"),
    Defect("pos.quebec_files_cp1252", "pos", "transactions", "encoding",
           "daily files from Quebec stores are Windows-1252, not UTF-8", systemic=True),

    # ---------------- Web analytics
    Defect("web.bot_sessions", "web", "events", "junk",
           "crawler sessions: dozens of product views seconds apart, bot user agents"),
    Defect("web.bot_events", "web", "events", "junk", "events belonging to bot sessions"),
    Defect("web.ts_in_seconds", "web", "events", "format",
           "events from app_version 4.1.0 send ts in epoch seconds, everyone else in milliseconds"),
    Defect("web.purchase_without_tracking", "web", "events", "completeness",
           "only ~65% of online orders have a tracked purchase event (consent)", systemic=True),
    Defect("web.duplicate_events", "web", "events", "duplicate",
           "the same event_id delivered twice (at-least-once delivery; 30% in the next file)"),
    Defect("web.schema_drift_consent", "web", "events", "schema_drift",
           "nested 'consent' object appears from {day:%Y-%m-%d}", systemic=True),
    Defect("web.truncated_lines", "web", "events", "file",
           "truncated JSON lines (cut off mid-record) spliced into files"),

    # ---------------- Inventory
    Defect("inventory.negative_on_hand", "inventory", "snapshots", "business_rule", "negative on_hand quantities"),
    Defect("inventory.missing_store_weeks", "inventory", "snapshots", "completeness",
           "store {store} has no snapshots for 3 consecutive weeks"),
    Defect("inventory.conflicting_snapshot", "inventory", "snapshots", "duplicate",
           "store {store} week {week:%Y-%m-%d} delivered twice with different on_hand values"),
]


def _build(defects) -> dict:
    registry = {}
    for d in defects:
        if d.id in registry:
            raise ValueError(f"defect id declared twice: {d.id}")
        if d.category not in CATEGORIES:
            raise ValueError(f"{d.id}: unknown category {d.category!r}")
        registry[d.id] = d
    return registry


REGISTRY: dict = _build(_DEFECTS)
