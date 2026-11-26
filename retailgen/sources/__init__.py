"""Source-system emulators: each takes the clean truth, applies that system's conventions and
defects, and writes its files. Every defect is recorded in the manifest."""
from . import crm, pim, oms, pos
from .small import emit_stores, emit_fx, emit_promo
from .web_inventory import emit_web, emit_inventory
from . import ads, braze

EMITTERS = [
    ("crm", crm.emit),
    ("pim", pim.emit),
    ("storeops", emit_stores),
    ("finance", emit_fx),
    ("promo", emit_promo),
    ("oms", oms.emit),
    ("pos", pos.emit),
    ("web", emit_web),
    ("inventory", emit_inventory),
    ("ads", ads.emit),
    ("braze", braze.emit),
]
