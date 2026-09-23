"""Demo data (fictional workers) and the rule check for who may take a shift.

Rules:
1. Trained for this location
2. No overlap with another shift today
3. Stays within the contract hour band (new Dutch flex law: max = 130% of min)
Ranking: workers furthest below their guaranteed minimum hours first
(the employer pays those hours anyway), then fewest recent offers (fairness).
"""

# Change this one line if you may not name the real customer
STORE_NAME = "Demo Store · Amsterdam"

SHIFT = {
    "id": "sat-evening",
    "location": STORE_NAME,
    "day": "Saturday",
    "start": "17:00",
    "end": "22:00",
    "hours": 5,
    "cancelled_by": "Tom",
}

# All names fictional. contract_max = 130% of contract_min (rounded down)
WORKERS = [
    {"name": "Noah",  "lang": "NL", "trained": [STORE_NAME, "Centraal"], "contract_min": 16, "contract_max": 20, "hours_this_week": 10, "busy": [], "offers_14d": 5,
     "demo_reply": "sorry kan niet vanavond, familie etentje"},
    {"name": "Daan",  "lang": "NL", "trained": [STORE_NAME], "contract_min": 8, "contract_max": 10, "hours_this_week": 4, "busy": [], "offers_14d": 0,
     "demo_reply": "ja maar tot 9 uur"},
    {"name": "Ayşe",  "lang": "TR", "trained": [STORE_NAME], "contract_min": 12, "contract_max": 15, "hours_this_week": 8, "busy": [], "offers_14d": 1,
     "demo_reply": "tamam gelirim, tüm vardiya olur 👍"},
    {"name": "Kasia", "lang": "PL", "trained": [STORE_NAME], "contract_min": 16, "contract_max": 20, "hours_this_week": 12, "busy": [], "offers_14d": 3,
     "demo_reply": "Tak, mogę od 18"},
    {"name": "Lucas", "lang": "EN", "trained": [STORE_NAME], "contract_min": 20, "contract_max": 26, "hours_this_week": 24, "busy": [], "offers_14d": 2,
     "demo_reply": "yes I can do it"},
    {"name": "Mert",  "lang": "TR", "trained": ["Centraal"], "contract_min": 12, "contract_max": 15, "hours_this_week": 6, "busy": [], "offers_14d": 1,
     "demo_reply": "gelirim"},
    {"name": "Sofia", "lang": "ES", "trained": [STORE_NAME], "contract_min": 12, "contract_max": 15, "hours_this_week": 5, "busy": [("16:00", "20:00")], "offers_14d": 0,
     "demo_reply": "Sí, puedo"},
    {"name": "Emma",  "lang": "EN", "trained": [STORE_NAME], "contract_min": 12, "contract_max": 15, "hours_this_week": 11, "busy": [], "offers_14d": 1,
     "demo_reply": "sure!"},
]


def _mins(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def overlaps(a_start, a_end, b_start, b_end):
    return _mins(a_start) < _mins(b_end) and _mins(b_start) < _mins(a_end)


def check_worker(worker, shift):
    """Return (eligible: bool, reason: str)."""
    if worker["name"] == shift.get("cancelled_by"):
        return False, "Cancelled this shift"
    if shift["location"] not in worker["trained"]:
        return False, f"Not trained for {shift['location']}"
    for b_start, b_end in worker["busy"]:
        if overlaps(shift["start"], shift["end"], b_start, b_end):
            return False, f"Already working {b_start}–{b_end} today"
    new_total = worker["hours_this_week"] + shift["hours"]
    if new_total > worker["contract_max"]:
        return False, (f"Would reach {new_total}h this week, above contract max "
                       f"{worker['contract_max']}h (flex-law hour band)")
    gap = max(0, worker["contract_min"] - worker["hours_this_week"])
    if gap:
        return True, f"{gap}h below guaranteed minimum — hours already paid for"
    return True, "Within hour band"


def rank_candidates(workers, shift):
    """Split into eligible (ranked) and excluded lists."""
    eligible, excluded = [], []
    for w in workers:
        ok, reason = check_worker(w, shift)
        row = {**w, "reason": reason}
        (eligible if ok else excluded).append(row)
    eligible.sort(key=lambda w: (-(max(0, w["contract_min"] - w["hours_this_week"])), w["offers_14d"]))
    return eligible, excluded


def pick_best(offers):
    """offers: list of dicts with 'rank' and 'parsed'. Full 'yes' beats 'partial'."""
    yes = [o for o in offers if o.get("parsed") and o["parsed"]["status"] == "yes"]
    if yes:
        return min(yes, key=lambda o: o["rank"])
    partial = [o for o in offers if o.get("parsed") and o["parsed"]["status"] == "partial"]
    if partial:
        return min(partial, key=lambda o: o["rank"])
    return None
