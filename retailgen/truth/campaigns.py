"""The marketing campaigns: their calendar, audiences, holdouts, true lifts and the business flaws, as demand modifiers.

Built by build_truth: the signup campaigns (gain loyalty, Prospects) change the customers before the demand engine
is built; the email campaigns are DemandModifiers the engine runs day by day.
"""
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .demand import DemandModifier

NS = "datetime64[ns]"
SEND_HOUR_UTC = 17
HOLDOUT_SHARE = 0.10
CONTAMINATED_SHARE = 0.35
FATIGUE_FREE_SENDS = 4
FATIGUE_STEP = 0.04
FATIGUE_FLOOR = 0.30
UNSUBSCRIBE = 0.0015
UNSUBSCRIBE_FATIGUED = 0.006
FATIGUED_SENDS = 10
NO_CONSENT_SHARE = 0.015
POST_UNSUBSCRIBE_SENDS = 300
CANVAS_DELAY_DAYS = 5
CANVAS_LIFT = 0.12
GAIN_LOYALTY_POINTS = 0.05
GAIN_LOYALTY_DAYS = 14
WINBACK_DAYS = 30
PROSPECT_PULL = 0.15
PROSPECT_EXTRA = 0.04
PROSPECT_REACH_DAYS = 60


@dataclass(frozen=True)
class Send:
    """One send of a campaign: its day and the lift that send adds on its own."""

    day: str
    lift: float = 0.0


@dataclass(frozen=True)
class CampaignSpec:
    """One campaign in the calendar. `holdout` is none, clean or contaminated."""

    campaign_id: str
    name: str
    kind: str
    sends: tuple
    window_days: int = 0
    half_life: float = 1.0
    pullback: float = 0.0
    pullback_days: int = 21
    holdout: str = "none"
    promo_code: str = None
    code_leaks: bool = False
    lapsed_days: int = 0
    no_consent_sends: bool = False
    parent: str = None
    categories: tuple = ()
    flight_days: int = 0
    adds_customers: bool = False


def _seasonal(cid, name, sends, lift, window, half_life, holdout="none", code=None, leaks=False, pullback=0.0,
              no_consent=False, categories=()):
    """A seasonal campaign whose first send carries `lift`; `sends` may give later sends their own lift."""
    first, *rest = sends
    send_list = (Send(first, lift),) + tuple(s if isinstance(s, Send) else Send(s) for s in rest)
    return CampaignSpec(cid, name, "seasonal", send_list, window, half_life, pullback=pullback, holdout=holdout,
                        promo_code=code, code_leaks=leaks, no_consent_sends=no_consent, categories=categories)


def utm_tag(spec):
    """The campaign's tracking tag: Prospects flights as prs_YYYY_MM, email campaigns as their name in snake case."""
    if spec.kind == "prospects":
        return "prs_" + spec.sends[0].day[:7].replace("-", "_")
    return re.sub(r"[^a-z0-9]+", "_", spec.name.lower().replace("'", "")).strip("_")


def calendar():
    """Every campaign in the client's history and the increments (plan on Task 766, section 2)."""
    c = []
    # Seasonal: 2025, 2026 history, 2026 increments
    c += [
        _seasonal("CMP-01", "TAKE20 February 2025", ["2025-02-03", "2025-02-14"], 0.12, 28, 28.0,
                  holdout="contaminated", code="TAKE20-25", pullback=0.12),
        _seasonal("CMP-02", "Spring 2025", ["2025-03-15", "2025-03-20"], 0.10, 14, 14.0, holdout="clean",
                  code="SPRING25"),
        _seasonal("CMP-03", "Mother's Day 2025", ["2025-05-01", "2025-05-06"], 0.25, 10, 4.0, holdout="clean",
                  categories=("Decor", "Kitchen", "Bedding", "Tops")),
        _seasonal("CMP-04", "May-June 2025", ["2025-05-15", "2025-05-28"], 0.08, 14, 7.0, code="SAVE10-25",
                  leaks=True),
        _seasonal("CMP-05", "Father's Day 2025", ["2025-06-05", "2025-06-10"], 0.25, 10, 4.0, holdout="clean",
                  categories=("Camping", "Cycling", "Audio", "Sneakers")),
        _seasonal("CMP-06", "Summer 2025", ["2025-07-01", "2025-07-08"], 0.10, 14, 14.0, holdout="contaminated",
                  code="SUMMER25", no_consent=True),
        _seasonal("CMP-07", "Fall 2025", ["2025-09-20", "2025-09-25"], 0.08, 10, 10.0, code="FALL25",
                  categories=("Outerwear", "Boots")),
        _seasonal("CMP-08", "Black Friday 2025", ["2025-11-24", Send("2025-11-29", 0.08)], 0.30, 5, 2.0,
                  code="BFRIDAY25", leaks=True),
        _seasonal("CMP-09", "Holiday gift guide 2025", ["2025-12-05", "2025-12-10"], 0.0, 7, 7.0, code="GIFT25"),
        _seasonal("CMP-10", "Boxing Day 2025", ["2025-12-26", "2025-12-29"], 0.12, 7, 7.0, code="BOXING25"),
        _seasonal("CMP-11", "TAKE20 February 2026", ["2026-02-02", "2026-02-13"], 0.12, 28, 28.0,
                  holdout="contaminated", code="TAKE20-26", pullback=0.12),
        _seasonal("CMP-12", "Spring 2026", ["2026-03-15", "2026-03-20"], 0.06, 14, 14.0, code="SPRING26",
                  pullback=0.10),
        _seasonal("CMP-13", "Mother's Day 2026", ["2026-04-30", "2026-05-05"], 0.25, 10, 4.0, holdout="clean",
                  categories=("Decor", "Kitchen", "Bedding", "Tops")),
        _seasonal("CMP-14", "May-June 2026", ["2026-05-15", "2026-05-28"], 0.05, 14, 7.0, code="SAVE10-26",
                  pullback=0.07),
        _seasonal("CMP-15", "Father's Day 2026", ["2026-06-11", "2026-06-16"], 0.25, 10, 4.0, holdout="clean",
                  categories=("Camping", "Cycling", "Audio", "Sneakers")),
        _seasonal("CMP-16", "Summer 2026 outerwear", ["2026-07-01", "2026-07-08"], 0.01, 14, 14.0,
                  holdout="contaminated", code="SUMMER26", leaks=True, no_consent=True, categories=("Outerwear",)),
        _seasonal("CMP-17", "Fall 2026", ["2026-09-20", "2026-09-25"], 0.08, 10, 10.0, code="FALL26",
                  categories=("Outerwear", "Boots")),
        _seasonal("CMP-18", "Halloween 2026", ["2026-10-24", "2026-10-28"], 0.10, 7, 7.0, code="HALLOWEEN26"),
        _seasonal("CMP-19", "Black Friday 2026", ["2026-11-20", Send("2026-11-25", 0.15)], 0.30, 5, 2.0,
                  holdout="clean", code="BFRIDAY26"),
        _seasonal("CMP-20", "Holiday gift guide 2026", ["2026-11-28", "2026-12-03"], 0.10, 7, 7.0, code="GIFT26"),
        _seasonal("CMP-21", "Boxing Day 2026", ["2026-12-26", "2026-12-29"], 0.12, 7, 7.0, holdout="clean",
                  code="BOXING26"),
    ]

    # The contaminated campaigns' reminders, sent to the treated and part of the holdout
    for parent in [x for x in c if x.holdout == "contaminated"]:
        day = (pd.Timestamp(parent.sends[0].day) + pd.Timedelta(days=3)).strftime("%Y-%m-%d")
        c.append(CampaignSpec(parent.campaign_id + "R", parent.name + " reminder", "reminder",
                              (Send(day, parent.sends[0].lift / 2),), parent.window_days, parent.half_life,
                              parent=parent.campaign_id))

    # Monthly newsletter to members, on the 10th
    months = pd.date_range("2025-01-01", "2026-12-01", freq="MS") + pd.Timedelta(days=9)
    c.append(CampaignSpec("CMP-NL", "Monthly newsletter", "newsletter",
                          tuple(Send(m.strftime("%Y-%m-%d"), 0.005) for m in months), 7, 3.0))

    # Win-back, one per quarter; August 2025 calls 45 days lapsed and reaches active customers
    for k, day in enumerate(["2025-02-10", "2025-05-12", "2025-08-11", "2025-11-10",
                             "2026-02-09", "2026-05-11", "2026-08-10", "2026-11-09"]):
        mistargeted = day == "2025-08-11"
        c.append(CampaignSpec(f"CMP-W{k + 1}", f"Win-back {day[:7]}", "winback",
                              (Send(day, 0.0 if mistargeted else 0.04),), WINBACK_DAYS,
                              lapsed_days=45 if mistargeted else 180))

    # Gain loyalty members
    for k, day in enumerate(["2025-03-20", "2025-06-20", "2025-09-20", "2026-01-20", "2026-04-20",
                             "2026-07-20", "2026-10-20"]):
        c.append(CampaignSpec(f"CMP-L{k + 1}", f"Join the loyalty program {day[:7]}", "gain_loyalty",
                              (Send(day, GAIN_LOYALTY_POINTS),), GAIN_LOYALTY_DAYS))

    # Post-purchase cross-sell Canvas
    c.append(CampaignSpec("CMP-CV", "Post-purchase cross-sell", "canvas", (), 14, 5.0))

    # Prospects: agency paid flights, no Braze data; flights 3, 5 and 7 also bring real new customers
    flights = [("2025-02-15", 28), ("2025-04-20", 21), ("2025-06-25", 35), ("2025-09-01", 28), ("2025-10-20", 42),
               ("2026-01-15", 28), ("2026-03-20", 35), ("2026-06-01", 28), ("2026-11-10", 42)]
    for k, (day, length) in enumerate(flights):
        c.append(CampaignSpec(f"PRS-{k + 1}", f"Prospects flight {k + 1}", "prospects", (Send(day, PROSPECT_PULL),),
                              flight_days=length, adds_customers=k in (2, 4, 6)))
    return c


@dataclass
class SendRecord:
    """One send: the day, the campaign, the recipients and their fatigue factor, and which went to someone who had
    unsubscribed or never consented."""

    day_index: int
    campaign_id: str
    customers: np.ndarray
    fatigue: np.ndarray
    after_unsubscribe: np.ndarray
    no_consent: np.ndarray
    unsubscribed: np.ndarray


@dataclass
class CampaignContext:
    """What every email campaign shares: the customers' consent and loyalty, unsubscribes, recent sends for
    fatigue, and the log of sends and audiences for the answer key."""

    rng: object
    days: pd.DatetimeIndex
    created_at: np.ndarray
    opted_in: np.ndarray
    joined_at: np.ndarray
    lifecycle: object
    unsubscribed: np.ndarray = None
    post_unsubscribe_left: int = POST_UNSUBSCRIBE_SENDS
    sends: list = field(default_factory=list)
    assignments: list = field(default_factory=list)
    reactivations: dict = field(default_factory=dict)
    _recent: np.ndarray = None
    _recent_log: list = field(default_factory=list)

    def __post_init__(self):
        """Start with no unsubscribes and no recent sends."""
        n = len(self.created_at)
        self.unsubscribed = np.zeros(n, bool)
        self._recent = np.zeros(n, int)

    def day(self, day_index):
        """The day's midnight as a datetime64."""
        return self.days[day_index].to_datetime64()

    def reachable(self, day_index):
        """Customers signed up before the day who opted in and have not unsubscribed."""
        return (self.created_at < self.day(day_index)) & self.opted_in & ~self.unsubscribed

    def members(self, day_index):
        """Customers who had joined the loyalty program before the day."""
        return self.joined_at < self.day(day_index)

    def send(self, day_index, campaign_id, recipients, extra_no_consent=None):
        """Send to the recipients (plus any planted wrong ones): log it, update fatigue and draw unsubscribes.
        Returns the fatigue factor per recipient."""
        recipients = np.asarray(recipients, dtype=int)

        # A few sends reach people who unsubscribed earlier; the rest of them stay suppressed
        unsub_pool = np.flatnonzero(self.unsubscribed & (self.created_at < self.day(day_index)))
        take = min(self.post_unsubscribe_left, int(round(len(unsub_pool) * 0.02)))
        late = self.rng.choice(unsub_pool, size=take, replace=False) if take else np.array([], dtype=int)
        self.post_unsubscribe_left -= take
        wrong = np.asarray(extra_no_consent if extra_no_consent is not None else [], dtype=int)
        everyone = np.concatenate([recipients, late, wrong])

        # Fatigue: sends in the trailing 30 days, this one included
        self._expire(day_index)
        count = self._recent[everyone] + 1
        fatigue = np.clip(1.0 - FATIGUE_STEP * np.maximum(count - FATIGUE_FREE_SENDS, 0), FATIGUE_FLOOR, 1.0)
        self._recent[everyone] += 1
        self._recent_log.append((day_index, everyone))

        # Unsubscribes, more likely for the over-sent
        p = np.where(count >= FATIGUED_SENDS, UNSUBSCRIBE_FATIGUED, UNSUBSCRIBE)
        quits = (self.rng.random(len(everyone)) < p) & ~self.unsubscribed[everyone]
        self.unsubscribed[everyone[quits]] = True

        flag_late = np.zeros(len(everyone), bool)
        flag_late[len(recipients):len(recipients) + len(late)] = True
        flag_wrong = np.zeros(len(everyone), bool)
        flag_wrong[len(recipients) + len(late):] = True
        self.sends.append(SendRecord(day_index, campaign_id, everyone, fatigue, flag_late, flag_wrong, quits))
        return dict(zip(everyone.tolist(), fatigue.tolist()))

    def assign(self, campaign_id, group, customers, day_index):
        """Record an audience group (treated, holdout or holdout_contaminated) for the answer key."""
        self.assignments.append((campaign_id, group, np.asarray(customers, dtype=int), day_index))

    def _expire(self, day_index):
        """Drop sends older than 30 days from the fatigue counts."""
        while self._recent_log and self._recent_log[0][0] <= day_index - 30:
            _, who = self._recent_log.pop(0)
            self._recent[who] -= 1


class EmailCampaign(DemandModifier):
    """A campaign that emails one audience, picked at the first send, and lifts treated customers' buying with a
    decaying kernel per send. Subclasses say who is eligible."""

    def __init__(self, spec, ctx):
        """Keep the spec and the shared context; resolve the send days to day positions."""
        self.spec = spec
        self.campaign_id = spec.campaign_id
        self._ctx = ctx
        self._send_index = [int(ctx.days.get_indexer([pd.Timestamp(s.day)])[0]) for s in spec.sends]
        self._treated = np.array([], dtype=int)
        self._fatigue = np.array([])
        self.holdout = np.array([], dtype=int)

    @property
    def treated(self):
        """The customers this campaign treats (positions in the customers' order)."""
        return self._treated

    def eligible(self, day_index, state):
        """Who may receive the campaign on its first send (opted-in customers by default)."""
        return np.flatnonzero(self._ctx.reachable(day_index))

    def start_day(self, day_index, state):
        """On the first send pick the audience and holdout; on every send, email the treated."""
        if day_index not in self._send_index:
            return
        if day_index == self._send_index[0]:
            self._choose_audience(day_index, state)
        recipients = self._treated[~self._ctx.unsubscribed[self._treated]]
        wrong = self._no_consent(day_index, len(recipients))
        fatigue = self._ctx.send(day_index, self.campaign_id, recipients, wrong)
        if day_index == self._send_index[0]:
            self._fatigue = np.array([fatigue.get(c, 1.0) for c in self._treated])

    def lift(self, day_index, state):
        """Each send's lift, decaying with the half-life inside the window, times the fatigue at the first send;
        after the window, the pull-forward deficit."""
        if not len(self._treated) or day_index < self._send_index[0]:
            return None
        start, end = self._send_index[0], self._send_index[0] + self.spec.window_days
        amount = 0.0
        for send, idx in zip(self.spec.sends, self._send_index):
            if idx <= day_index < idx + self.spec.window_days:
                amount += send.lift * 0.5 ** ((day_index - idx) / self.spec.half_life)
        if end <= day_index < end + self.spec.pullback_days and self.spec.pullback:
            amount -= self.spec.pullback
        if amount == 0.0:
            return None
        out = np.zeros(len(self._ctx.created_at))
        out[self._treated] = np.where(amount > 0, amount * self._fatigue, amount)
        return out

    def _choose_audience(self, day_index, state):
        """Split the eligible customers into treated and holdout as the spec says, and record both."""
        audience = self.eligible(day_index, state)
        if self.spec.holdout == "none" or len(audience) == 0:
            self._treated, self.holdout = audience, np.array([], dtype=int)
        else:
            held = self._ctx.rng.random(len(audience)) < HOLDOUT_SHARE
            self._treated, self.holdout = audience[~held], audience[held]
        self._ctx.assign(self.campaign_id, "treated", self._treated, day_index)
        if len(self.holdout):
            group = "holdout" if self.spec.holdout == "clean" else "holdout_contaminated"
            self._ctx.assign(self.campaign_id, group, self.holdout, day_index)

    def _no_consent(self, day_index, n_sends):
        """For the campaigns that do it, a share of extra sends to customers who never opted in."""
        if not self.spec.no_consent_sends:
            return None
        pool = np.flatnonzero((self._ctx.created_at < self._ctx.day(day_index)) & ~self._ctx.opted_in)
        k = min(len(pool), int(round(n_sends * NO_CONSENT_SHARE)))
        return self._ctx.rng.choice(pool, size=k, replace=False) if k else None


class SeasonalCampaign(EmailCampaign):
    """A seasonal promotion to every opted-in customer."""


class NewsletterCampaign(EmailCampaign):
    """The monthly newsletter: a fresh audience of opted-in members at every send, no holdout."""

    def start_day(self, day_index, state):
        """Pick that month's members and email them; the lift follows from this send."""
        if day_index not in self._send_index:
            return
        audience = np.flatnonzero(self._ctx.reachable(day_index) & self._ctx.members(day_index))
        self._ctx.assign(self.campaign_id, "treated", audience, day_index)
        fatigue = self._ctx.send(day_index, self.campaign_id, audience)
        self._treated = audience
        self._fatigue = np.array([fatigue.get(c, 1.0) for c in audience])
        self._last_send = day_index

    def lift(self, day_index, state):
        """The latest send's lift, decaying inside its window."""
        if not len(self._treated):
            return None
        since = day_index - self._last_send
        if not 0 <= since < self.spec.window_days:
            return None
        lift = self.spec.sends[self._send_index.index(self._last_send)].lift
        out = np.zeros(len(self._ctx.created_at))
        out[self._treated] = lift * 0.5 ** (since / self.spec.half_life) * self._fatigue
        return out


class ReminderCampaign(EmailCampaign):
    """A reminder of a contaminated campaign, sent to its treated customers and, by mistake, part of its holdout."""

    def __init__(self, spec, ctx, parent):
        """Keep the parent campaign whose audience the reminder reuses."""
        super().__init__(spec, ctx)
        self._parent = parent

    def eligible(self, day_index, state):
        """The parent's treated customers plus 35% of its holdout."""
        holdout = self._parent.holdout
        leaked = holdout[self._ctx.rng.random(len(holdout)) < CONTAMINATED_SHARE]
        self._ctx.assign(self.campaign_id, "contaminating", leaked, day_index)
        return np.concatenate([self._parent.treated, leaked])


class WinBackCampaign(EmailCampaign):
    """Win-back: emails customers with no purchase in `lapsed_days`; some who had stopped buying come back."""

    def eligible(self, day_index, state):
        """Opted-in customers who have bought before and not in the last `lapsed_days` days."""
        since = state.days_since_purchase(day_index)
        bought = since < day_index + 1
        return np.flatnonzero(self._ctx.reachable(day_index) & bought & (since >= self.spec.lapsed_days))

    def start_day(self, day_index, state):
        """Email the audience, then bring back a share of those who had churned, within 30 days."""
        if day_index != self._send_index[0]:
            return
        self._choose_audience(day_index, state)
        fatigue = self._ctx.send(day_index, self.campaign_id, self._treated)
        life = self._ctx.lifecycle
        today = self._ctx.day(day_index)
        churned = self._treated[life.churn_at[self._treated] <= today]
        chance = self.spec.sends[0].lift * np.array([fatigue.get(c, 1.0) for c in churned])
        back = churned[self._ctx.rng.random(len(churned)) < chance]
        when = today + (self._ctx.rng.random(len(back)) * WINBACK_DAYS * 86400).astype("timedelta64[s]")
        earlier = when.astype(NS) < life.reactivate_at[back]
        life.reactivate_at[back[earlier]] = when.astype(NS)[earlier]
        self._ctx.reactivations[self.campaign_id] = int(earlier.sum())

    def lift(self, day_index, state):
        """Win-back works through comebacks, not a lift on buying weight."""
        return None


class CanvasCampaign(EmailCampaign):
    """The post-purchase cross-sell Canvas: members who bought five days ago get an email, at most once per
    purchase day, and a decaying lift for 14 days. No holdout."""

    def __init__(self, spec, ctx):
        """Start with nobody in a Canvas window."""
        super().__init__(spec, ctx)
        self._since = np.full(len(ctx.created_at), -10_000)

    def start_day(self, day_index, state):
        """Email reachable members whose last purchase was five days ago."""
        due = (state.last_purchase == day_index - CANVAS_DELAY_DAYS)
        recipients = np.flatnonzero(due & self._ctx.reachable(day_index) & self._ctx.members(day_index))
        if not len(recipients):
            return
        self._ctx.send(day_index, self.campaign_id, recipients)
        self._ctx.assign(self.campaign_id, "treated", recipients, day_index)
        self._since[recipients] = day_index

    def lift(self, day_index, state):
        """+12% decaying with a five-day half-life for 14 days after each customer's latest Canvas email."""
        age = day_index - self._since
        active = (age >= 0) & (age < self.spec.window_days)
        if not active.any():
            return None
        return np.where(active, CANVAS_LIFT * 0.5 ** (age / self.spec.half_life), 0.0)


EMAIL_KINDS = {
    "seasonal": lambda spec, ctx, by_id: SeasonalCampaign(spec, ctx),
    "newsletter": lambda spec, ctx, by_id: NewsletterCampaign(spec, ctx),
    "reminder": lambda spec, ctx, by_id: ReminderCampaign(spec, ctx, by_id[spec.parent]),
    "winback": lambda spec, ctx, by_id: WinBackCampaign(spec, ctx),
    "canvas": lambda spec, ctx, by_id: CanvasCampaign(spec, ctx),
}


def email_campaigns(specs, ctx):
    """Build one DemandModifier per email campaign, in calendar order, wiring reminders to their parents.
    Called by build_demand; the signup kinds are handled before the engine and are skipped here."""
    by_id, out = {}, []
    for spec in [s for s in specs if s.kind in EMAIL_KINDS]:
        modifier = EMAIL_KINDS[spec.kind](spec, ctx, by_id)
        by_id[spec.campaign_id] = modifier
        out.append(modifier)
    return out
