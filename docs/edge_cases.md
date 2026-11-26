# Edge cases: generator output

Scenarios the generator handles on purpose, and why. One entry per case; code comments carry only the ID.

- **GEN-01 Parquet timestamps are written in microseconds.** pandas holds timestamps in nanoseconds, and Parquet files
  written that way carry `TIMESTAMP(NANOS)`, which some Spark versions cannot read. `Output.parquet` therefore floors
  every timestamp column to microseconds and writes the file with the microsecond unit. The generator does produce
  sub-microsecond parts (for example from adding a fractional delta), so the floor loses at most one microsecond per
  value; Spark itself holds no finer precision. The change alters the bytes of every Parquet file on purpose; the rerun
  test compares two runs of the same code, so it needs no new baseline. The truth tables written by `generate.py` are
  floored and written the same way, so landing and truth agree. A test at scale 0.01 checks that flooring creates no
  new ties: for each Parquet entity and timestamp column, the number of distinct (key, timestamp) pairs is the same
  before and after.

- **GEN-02 A small run still reaches every guarded POS step.** Two steps in the POS emitter ran only when a given store
  had a nightly file on a given increment day, so at a small scale some seeds never reached one and the end-of-run
  guard stopped the run (Bug 553). Each step now runs on the first day from its usual day that the store has a file,
  with a fallback if it has none. At the usual seed and scale the store has a file on the usual day, so each step runs
  there as before, no random draw moves, and the files are byte-identical (checked by hashing every file at scales
  0.01 and 0.05 before and after).
- **GEN-03 A run that fails the guard is not marked finished.** The guard message names the scale and seed and never a
  defect id; the ids go to `answer_key/unrecorded_defects.txt`. `generate.py` writes `run.json` last, after the guard,
  so a failed run has none, and `validate.py` refuses output without it. The slow small-scale regression test is in
  `tests/test_small_scale.py` and runs only with `RETAILGEN_SLOW=1`.

- **GEN-04 Each guaranteed store is placed without removing the other.** The store generator guarantees at least one
  QC store and one US store. The US guarantee picks the first slot from 1 up that does not hold the only QC store, so at
  the smallest scale (6 stores) the two never cancel and the run no longer stops in the store generator (Bug 677). A
  slot differs from the old choice only where the old choice removed the only QC store, which stopped the run, so no run
  that finished before changes (checked by hashing every file at scales 0.01 and 0.05 before and after). The seed list
  test is `tests/test_store_slots.py`.

- **GEN-05 One demand engine draws every purchase, so the byte baseline was reset.** Online orders, store baskets and
  signed-in browsing all come from `DemandEngine` (Story 770), which uses the random generator in a new order, and the
  increments now run to 2026-12-31 (92 days). Every landing file changes on purpose. The determinism test compares two
  runs of the same code, so it needs no stored baseline; it also checks the 92 increment folders end at 2026-12-31.
  Volumes stay at today's: the day's expected total is the base rate (600 online, 600 store at full scale) times the
  seasonality, the same curve as before except the gifting windows (GEN-10). At scale 0.1 the totals over the window
  were within 1.1% of that expectation. The longer window also moves the random stream before the store draw, so the
  GEN-04 case (no US store, the only QC store at slot 1) moved from seed 13 to seed 28 at scale 0.01;
  `tests/test_store_slots.py` now finds that seed by the draw's shape instead of naming it.
- **GEN-06 Every store basket has a true customer; the card scan decides what the POS shows.** The truth carries
  `true_customer_id` on every sale. `customer_id` is filled only when the true customer is a loyalty member who had
  joined by the sale and the card was scanned (`SCAN_RATE` 0.73), which keeps about 40% of baskets scanned, as before.
  A staff sale is always scanned. Store returns of online orders carry the order's customer as both.
- **GEN-07 Loyalty members join over time, and the CRM shows a member from their join date.** About 35% of all
  customers join at signup and the rest of the 65% join at a random time up to the end of the window, so membership
  rises toward 65%. Tier follows activity among members (top 12% Gold, next 28% Silver) instead of being random. The
  CRM extract at cut-over blanks the number and tier of members who join later; the change feed carries an update at
  each join, and a new signup carries loyalty only if they joined at signup. A random "tier" change no longer turns a
  non-member into a member, because joining is its own event.
- **GEN-08 Lifecycle delays are capped at 100 years.** Churn and comeback delays are exponential, and a long tail could
  pass the end of the nanosecond calendar (2262), wrap to a past date and make a customer look reactivated. Both delays
  are capped at 36,500 days, far beyond the window, so nothing inside it changes.
- **GEN-09 A staff sale names an employee who had already signed up.** Before Story 770 a staff sale picked any
  employee, so a card could appear in the POS before the employee's account existed. The pick is now limited to
  employees created before the sale day, and a day with none has no staff sale.
- **GEN-10 Mother's Day and Father's Day raise demand for ten days.** The shared curve is multiplied by 1.25 in the ten
  days before each holiday, and that holiday's categories by 1.5 to 1.8 within baskets. May and June totals therefore
  run up to about 9% above the old curve; the volume checks compare against the curve with the peaks included. The
  validator's future-order cut-off moved from 2026-11-01 to 2027-01-01 with the new increment end; the planted
  future-dated orders land in mid-2027.

- **GEN-11 The engine draws both channels day by day, so the byte baseline was reset again.** Win-back audiences and
  the post-purchase email depend on purchases already drawn, in either channel, so `DemandEngine.draw_all` loops the
  days once and draws online and store together (Story 771). The random draws come in a new order, and every landing
  file changes on purpose. `draw(channel)` remains for one channel on its own.
- **GEN-12 Campaign lifts are combined, damped and credited.** Each campaign gives its treated customers a relative
  lift for the day. The largest lift counts in full and every other one at 70%; a pull-forward campaign's negative
  lift after its window adds as it is. The day's expected total rises with the combined weights, and a purchase is
  marked as caused by the campaign with the largest lift with probability (factor - 1) / factor, so the answer key
  counts incremental purchases from the drawn rows. The realized lift (incremental over baseline purchases in the
  window) is below the nominal lift because each send's lift halves every half-life inside the window.
- **GEN-13 Win-back works through comebacks.** A churned customer has no buying weight to lift, so a win-back email
  brings a share of its churned audience back, setting their comeback within 30 days; the answer key counts the
  comebacks. The August 2025 win-back calls 45 days lapsed, so its audience is mostly active and its true effect is
  zero. The early-2025 win-backs reach almost no one: purchases before 2025 are not generated, so few customers have a
  180-day gap that early.
- **GEN-14 Prospects flights move signups within their side of the cut-over and add real customers.** A flight pulls
  15% more signups into itself from customers due in the 60 days after it, and only those whose new and old signup
  times fall on the same side of 2026-10-01, so the CRM extract and the change feed stay consistent. Their addresses
  and, when they joined at signup, their join dates move with them. Three flights also add new customers with full
  records and addresses (`add_customers`), created in the flight; ids continue after the highest existing one, so ids
  no longer follow signup order, and the customers are re-sorted by signup before the engine. Spend for those flights
  is 2 to 3 times the new customers' purchases (at least 50 per customer), and the others are priced like them, so
  every flight costs more per incremental customer than that customer is worth.
- **GEN-15 A campaign's promo code goes to its audience.** Orders by treated customers in the code's window use it
  (40% of them); a leaking code also reaches the holdout and everyone else as 3% and 6% of all its redemptions. A
  campaign without a holdout leaks only outside. Codes without a campaign behave as before.
- **GEN-16 Gain-loyalty emails are sent before the engine.** They change join dates, which the engine and the card
  scan need, so they run on the customers first; their sends count in the email events but not in fatigue or
  unsubscribes.
- **GEN-17 A purchase a campaign caused leans to the campaign's categories.** For a purchase the engine credits to a
  campaign with promoted categories (Mother's Day, Father's Day, Fall, Summer 2026 Outerwear), those categories weigh
  three times as much when its lines are picked; for the Canvas, the customer's second-favorite category weighs 1.5
  times. Purchases no campaign caused are untouched, so the baseline mix stays as it was. A category promoted out of
  season (Outerwear in July) still has its low season weight, so the campaign moves little.
