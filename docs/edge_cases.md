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

- **GEN-11 The engine draws both channels day by day, so the byte baseline was reset again.** Some campaigns choose
  their audience from purchases already drawn, in either channel, so `DemandEngine.draw_all` loops the days once and
  draws online and store together (Story 771). The random draws come in a new order, and every landing file changes on
  purpose. `draw(channel)` remains for one channel on its own.
- **GEN-12 Campaign lifts are combined and credited.** Each campaign gives its treated customers a relative lift for
  the day; the engine combines them (the largest in full, the others damped), raises the day's expected total, and
  marks a purchase as caused by the campaign with the largest lift with probability (factor - 1) / factor. The answer
  key counts incremental purchases from those marks. Its realized lift is below the nominal one because each send's
  lift halves every half-life inside the window.
- **GEN-13 Win-back works through comebacks.** A churned customer has no buying weight to lift, so a win-back email
  brings a share of its churned audience back within 30 days; the answer key counts the comebacks. The early-2025
  win-backs reach almost no one: purchases before 2025 are not generated, so few customers have a long gap that early.
- **GEN-14 Paid flights move signups within their side of the cut-over and can add customers.** A flight pulls signups
  due in the 60 days after it into the flight, only where the old and new signup times fall on the same side of
  2026-10-01, so the CRM extract and the change feed stay consistent; addresses and signup-day join dates move with
  them. Some flights add new customers with full records and addresses (`add_customers`); ids continue after the
  highest existing one, so ids no longer follow signup order, and the customers are re-sorted by signup before the
  engine. Each flight's spend is set after the engine runs, from what its customers bought.
- **GEN-15 A campaign's promo code goes to its audience.** Orders by treated customers in the code's window use it;
  the answer key records every redemption by group (treated, holdout, others). Codes without a campaign behave as
  before.
- **GEN-16 Gain-loyalty emails are sent before the engine.** They change join dates, which the engine and the card
  scan need, so they run on the customers first; their sends appear in the email events but do not enter the
  per-customer send counts the other campaigns keep.
- **GEN-17 A purchase a campaign caused leans to the campaign's categories.** For a purchase the engine credits to a
  campaign with promoted categories, those categories weigh three times as much when its lines are picked; for the
  post-purchase email, the customer's second-favorite category weighs 1.5 times. Purchases no campaign caused are
  untouched.
- **GEN-18 The newsletter and the post-purchase email are measured per send.** Their audience changes with every
  send, so their window purchases count each recipient's own send window, cut short where the same customer's next
  send begins; no purchase counts twice.
- **GEN-19 Avro is written through a seam, and a run can leave one source out.** `retailgen/avro.py` writes with
  `fastavro` when it is installed and otherwise stops the run at the Braze source with one line naming the library.
  `generate.py --skip-source NAME` leaves a source out; `run.json` lists it, the end-of-run guard ignores that
  source's catalogue entries, and `validate.py` prints a SKIP line for its checks. Braze and ads run last, so leaving
  Braze out does not change any other source's files. The tests that run the generator leave Braze out when
  `fastavro` is not installed.
- **GEN-20 Email clicks open their own web session.** Each email click inside the tracking window opens a session
  with the newsletter source, the email medium and the campaign's tag, landing on the campaign page; a paid flight's
  customer's first signed-in session carries the agency source and the flight's tag.
- **GEN-21 Email unsubscribes reach the CRM opt-in through a sync table.** `consent_sync` in the answer key holds
  when each unsubscribe reached the CRM; the cut-over extract and the change feed take the opt-in from it.
- **GEN-23 The line-ending scan skips binary files.** `validate.py` looks for CRLF endings and a BOM in text files
  only. Parquet and Avro files are skipped, because compressed binary bytes can hold the pair CR LF by chance, which
  is not a line ending. The suffixes are in `BINARY_SUFFIXES`; the test is `tests/test_validate_line_endings.py`.

- **GEN-22 A planted problem is recorded only for rows that are written (Bug 579).** One emitter recorded a planted
  problem before later steps (a removed span of rows, rows delivered after the window) could drop the rows it was
  planted on, so the manifest could count a row that never reached the files. The record now comes after routing and
  keeps only the planted rows that are written. A written row that was not planted is not counted, so it cannot hide
  behind a matching total. No random draw moves, so the landing files are byte-identical; only that manifest entry
  changes. The test is `tests/test_inventory_manifest_written_rows.py`.

### Pusher

- **PSH-01 `next` records a day only after a clean push.** A day goes into the state file only when every file was
  sent or skipped; with any failed file the run exits 1 and records nothing, so the next run pushes the same day again
  (files already in the volume with the same size are skipped). A dry run records nothing either. The state file is
  written to a temporary file, flushed and synced to disk, then renamed over the old one, so a crash or power cut
  leaves the old or the new list, never an empty or partial one.
- **PSH-02 Only the newest pushed day can be unmarked.** The pushed days must stay an unbroken run from the first
  increment day, because the daily load in bronze refuses a day whose earlier days are not complete. Removing an older
  day while a later one stays recorded would leave a gap that `next` fills out of order, so `unmark` refuses it and
  names the day to unmark first. `unmark` changes only the state file; removing the day's files from the volume is a
  separate runbook step.
- **PSH-03 The increment days come from the data, and the state path has no default.** `next` reads the days from the
  `increments/day=` folders, so the feed ends wherever the generated data ends with no date in the code. The state
  path must be given: a default would let a run whose state folder was not mounted start again at the first day. A
  missing state folder, a state inside the landing folder, or a file that is not an unbroken run of increment days stops
  the run with exit 2.
- **PSH-04 One run at a time.** `next` and `unmark` hold a lock file beside the state while they run, created
  exclusively, so the daily timer and a manual run cannot both change the state. A second run exits 2 and names the lock.
  A lock left by a killed run is removed by hand, once no pusher is running; the run does not guess whether a lock is
  stale.
