# Larchwood Supply Co. — source system interface notes

Compiled from each owning team's handover notes for the data platform project. Each section
is what that team told us. Where they were unsure, it says so. Nobody has checked these
notes against the actual files, so treat them as claims, not facts.

Larchwood is a Canadian outdoor/apparel/home retailer with stores in BC, AB, SK, MB, ON, QC,
NS and a few in Washington and Oregon, plus a website and a mobile app.

**Cut-over:** the history load is a backfill up to and including **2026-09-30**. From
**2026-10-01** each system drops files daily.

**Landing layout** (after the pusher delivers them): `landing/<source>/<entity>/<file>`, one folder per entity. History
and increments of an entity share the folder.

---

## 1. CRM (`crm`) — owner: Customer Care Systems

Legacy CRM, nightly CSV export. Column names are the CRM's own.

### `crm/customers` — full extract, `customers_full_20260930.csv`
| column | meaning |
|---|---|
| CUST_ID | customer key, `C` + 7 digits |
| FIRST_NM, LAST_NM | name |
| EMAIL_ADDR | login email, unique per customer |
| PHONE | phone number |
| DOB | date of birth (optional) |
| LOYALTY_NO | loyalty card number (`L` + 9 digits) if enrolled |
| OPT_IN | marketing consent flag (Y/N) |
| CREATED_DT | account creation timestamp (UTC) |
| LAST_MOD_DT | last modification timestamp (UTC) |

### `crm/customers_cdc` — daily change files, `customers_cdc_YYYYMMDD.csv`
Same columns, plus:
| column | meaning |
|---|---|
| OP | `I` insert, `U` update, `D` delete |
| SEQ_NO | monotonically increasing change sequence number |
| CHANGE_TS | when the change happened (UTC, ISO-8601) |

Updates carry the full row image. Deletes carry only the key (privacy requests).
"We're adding loyalty tier to the export sometime in October."

### `crm/customer_addresses` and `crm/customer_addresses_cdc`
| column | meaning |
|---|---|
| ADDR_ID | address key |
| CUST_ID | owning customer |
| ADDR_TYPE | `B` billing, `S` shipping |
| LINE1, LINE2, CITY, PROV, POSTAL, COUNTRY | the address |
| DEFAULT_FLG | `Y` for the customer's current default |

The CDC version adds OP / SEQ_NO / CHANGE_TS as above.

---

## 2. PIM / merchandising (`pim`) — owner: Merch Ops

JSON Lines, one object per line.

- `pim/categories/categories.jsonl` — `category_id`, `category_name`, `parent_id` (null for a
  department). Two levels: department → category.
- `pim/suppliers/suppliers.jsonl` — `supplier_id`, `supplier_name`, `country`.
- `pim/products/products_full_20260930.jsonl` — full catalogue at cut-over. After that,
  `products_delta_YYYYMMDD.jsonl` carries new and changed products. Shape:
  ```json
  {"sku": "004512", "title": "...", "category": {"id": 23, "name": "...", "department": "..."},
   "supplier": {"id": "SUP-007", "name": "..."}, "attributes": {"color": "...", "size": "M"},
   "pricing": {"list_price": 49.99, "currency": "CAD"}, "status": "active",
   "launch_date": "2025-04-01", "updated_at": "..."}
  ```
  SKU is a 6-character string and the key everywhere in the business. "Products are always
  set up in PIM before they go on sale."
- `pim/price_history/price_history_full_20260930.jsonl` — `sku`, `price`, `currency`,
  `effective_from`, `effective_to` (null = current). One open-ended row per SKU, no overlaps.
- `pim/price_changes/price_changes_YYYYMMDD.jsonl` — after cut-over, price changes come as
  notifications: `sku`, `new_price`, `currency`, `effective_from`, `change_reason`.
  These are sent on the day the change takes effect.

---

## 3. Store operations (`storeops`) — owner: Retail Ops

`storeops/stores/stores_YYYYMMDD.csv` — a **full snapshot of all stores**, sent every
morning. Columns: `store_id`, `store_code`, `store_name`, `city`, `province`, `country`,
`timezone`, `sqft`, `open_date`, `close_date` (blank while open), `extracted_at`.
`store_id` never changes. "Store codes are permanent too, in practice."

---

## 4. E-commerce OMS (`oms`) — owner: Digital Commerce

Parquet. All timestamps are UTC. Currency is per order (`CAD` or `USD` for US shipping).

- `oms/orders` — **one row per order version**: every status change (`placed` → `shipped` →
  `delivered`, or `cancelled`) re-sends the whole order row with a new `updated_at`. History
  files hold the latest version of each order as of cut-over, split by order month.
  Columns: `order_id`, `customer_id` (null for guest checkout), `guest_email`, `order_ts`,
  `channel` (`web`/`app`), `currency`, `ship_city`, `ship_province`, `ship_postal`,
  `ship_country`, `status`, `subtotal`, `discount_total`, `tax_total`, `shipping_fee`,
  `order_total`, `coupon_code`, `updated_at`.
  `order_total = subtotal - discount_total + tax_total + shipping_fee`.
- `oms/order_lines` — written once when the order is placed: `order_id`, `line_number`,
  `sku`, `quantity` (integer), `unit_price`, `discount_amount`, `line_total`.
- `oms/payments` — immutable payment gateway events: `payment_event_id`, `order_id`,
  `payment_method`, `card_brand`, `event_type` (`failed`, `authorize`, `capture`, `void`,
  `refund`), `amount`, `currency`, `event_ts`. Captures happen at shipment.
- `oms/shipments` — versioned like orders (`in_transit`, then `delivered`):
  `shipment_id`, `order_id`, `carrier`, `tracking_number`, `shipped_at`, `delivered_at`,
  `status`, `updated_at`.
- `oms/returns` — mail-in returns: `return_id`, `order_id`, `line_no`, `sku`, `qty`,
  `refund_amount` (incl. tax), `reason`, `returned_at`. Online orders can also be returned
  in store; the OMS doesn't see those.

---

## 5. Point of sale (`pos`) — owner: Store Systems

CSV, one row per basket line. History is consolidated monthly (`pos_YYYY-MM.csv`). From
cut-over each store's back-office PC uploads `pos_<STORE_CODE>_<YYYYMMDD>.csv` nightly.

| column | meaning |
|---|---|
| TXN_ID | basket id |
| STORE_CODE | store |
| REGISTER_NO | till number |
| TXN_DATETIME | when the basket was rung up |
| CASHIER | employee id |
| LOYALTY_CARD | loyalty card scanned, blank if none |
| LINE_NO | line within basket |
| SKU | product SKU |
| DESCRIPTION | receipt text |
| QTY | quantity (negative = return) |
| UNIT_PRICE_CENTS, DISC_CENTS, TAX_CENTS, LINE_TOTAL_CENTS | money in **CAD cents** |
| TENDER | payment type |
| ORIG_TXN_ID | for returns: original basket |
| ORIG_ORDER_REF | for returns of online orders: the OMS order id |
| PROMO | promotion applied to the line |

Files are UTF-8.

---

## 6. Promotions (`promo`) — owner: Marketing

- `promo/promotions/promotions.json` — the full promotion master, sent as one JSON array
  whenever it changes (`promotions_YYYYMMDD.json`). Fields: `promoId`, `code`, `type`
  (`PERCENT` or `FIXED_AMOUNT`), `value`, `minSpend`, `startDate`, `endDate` (null =
  evergreen), `channels` (`web`, `app`, `pos`).
- `promo/coupon_redemptions` — JSON Lines, one per online order that used a code:
  `redemptionId`, `orderId`, `code`, `discountAmount`, `redeemedAt` (epoch milliseconds).

---

## 7. Web analytics (`web`) — owner: Growth

`web/events/events_*.jsonl.gz` — gzipped JSON Lines from the tag manager and the app SDK.
Tracking went live **2026-01-01**. Only visitors who accept analytics cookies are tracked.

```json
{"event_id": "...", "event_name": "product_view", "ts": 1767312000123,
 "session": {"id": "...", "channel": "web", "app_version": "4.0.2"},
 "user": {"customer_id": null, "anonymous_id": "..."},
 "device": {"type": "mobile", "os": "iOS", "browser": "Safari", "user_agent": "..."},
 "page": {"path": "/p/004512", "referrer": null},
 "product": {"sku": "004512", "price": 49.99},
 "ecommerce": {"order_id": "ORD-..."},
 "utm": {"source": "newsletter", "medium": "email"}}
```
`event_name`: `page_view`, `product_view`, `add_to_cart`, `begin_checkout`, `purchase`.
`ts` is epoch milliseconds. `event_id` is unique. `product`, `ecommerce` and `utm` appear
only when relevant.

---

## 8. Inventory (`inventory`) — owner: Supply Chain

`inventory/snapshots/*.parquet` — weekly stock position for the tracked SKU range in every
open store, taken Sunday night and delivered Monday: `snapshot_date`, `store_id`, `sku`,
`on_hand`, `on_order`, `reorder_point`. Exactly one row per store/SKU/week.

---

## 9. Finance (`finance`) — owner: Treasury

`finance/fx_rates` — daily USD→CAD rate (CAD per 1 USD): `rate_date`, `from_ccy`, `to_ccy`,
`rate`. History in `fx_rates_history.csv`, then `fx_rates_YYYYMMDD.csv` per business day.
