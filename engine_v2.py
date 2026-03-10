# engine_v2.py
import random
import itertools
import math
from dataclasses import dataclass
from typing import Dict, List, Tuple, Any, Set

# ---------- Base parameters ----------

BASE_MARGIN = 1000.0          # margin for normal delivery
EXPRESS_SURCHARGE = 250.0     # extra margin customer pays for express service

CUSTOMER_VALUE = 4000.0       # expected future value (LTV) of the customer
DISCOUNT_PER_DAY = 100.0      # discount/compensation per day late

N_SAMPLES = 5000              # Monte Carlo samples per strategy
RANDOM_SEED = 42              # for reproducibility (optional)


# ---------- PERT helpers ----------

def sample_pert(a: float, m: float, b: float, lamb: float = 4.0) -> float:
    """Sample from a PERT distribution with min=a, mode=m, max=b."""
    if b == a:
        return a
    alpha = 1.0 + lamb * (m - a) / (b - a)
    beta = 1.0 + lamb * (b - m) / (b - a)
    x = random.betavariate(alpha, beta)
    return a + x * (b - a)


def mean_pert(a: float, m: float, b: float) -> float:
    """Mean of a PERT distribution."""
    return (a + 4.0 * m + b) / 6.0


# ---------- Activity network (process steps) ----------

@dataclass
class Activity:
    id: str
    name: str
    predecessors: List[str]
    normal_pert: Tuple[float, float, float]
    express_pert: Tuple[float, float, float]
    express_cost: float = 0.0   # internal cost to crash this activity


ACTIVITIES: Dict[str, Activity] = {
    "a": Activity("a", "Order Confirmation", [], (0.5, 1.0, 1.0), (0.5, 1.0, 1.0)),
    "b": Activity("b", "Mechanical Delivery", ["a"], (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
    "c": Activity("c", "Electrical Delivery", ["a"], (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
    "d": Activity("d", "Casting Delivery", ["a"], (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
    "e": Activity("e", "SA Mechanical", ["b"], (1.5, 2.5, 3.0), (0.5, 1.5, 2.0), 120.0),
    "f": Activity("f", "SA Electrical", ["c"], (2.0, 3.0, 3.5), (1.5, 2.0, 3.0), 120.0),
    "g": Activity("g", "SA Casting", ["d"], (0.5, 1.5, 2.0), (0.5, 1.0, 1.5), 120.0),
    "h": Activity("h", "In-process QC", ["e", "f", "g"], (0.5, 1.0, 1.0), (0.25, 0.5, 0.75), 60.0),
    "i": Activity("i", "Final Assembly", ["h"], (1.0, 1.5, 1.5), (0.5, 0.75, 1.0), 120.0),
    "j": Activity("j", "Painting & Curing", ["i"], (0.5, 1.0, 1.5), (0.25, 0.5, 0.5), 50.0),
    "k": Activity("k", "Packing", ["j"], (1.0, 1.5, 2.0), (1.0, 1.5, 2.0), 0.0),
    "l": Activity("l", "Transport Scheduling", ["j"], (0.25, 0.5, 0.5), (0.25, 0.5, 0.5), 0.0),
    "m": Activity("m", "Transport", ["k", "l"], (0.5, 0.5, 1.0), (0.5, 0.5, 1.0), 0.0),
    "n": Activity("n", "Delivery (end)", ["m"], (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
}

TOPO_ORDER = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n"]

# Activities that can be crashed (internal express)
ACTIVITY_EXPRESS_CANDIDATES: List[str] = ["e", "f", "g", "h", "i", "j"]


# ---------- Part-level BOM (same parts exist in AT & BE, but with different PERTs) ----------

# Short codes per part:
# Mxx = Mechanical, Exx = Electrical, Cxx = Casting

PARTS: Dict[str, Dict[str, Any]] = {
    # ---------- MECHANICAL ----------
    "M01": {
        "name": "SP BALL BEARING 6014 2Z",
        "group": "mechanical",
        "pert": {
            "AT": {"normal": (7.0, 9.0, 11.0), "express": (5.0, 6.0, 9.0)},
            "BE": {"normal": (2.0, 3.0, 4.0),  "express": (1.0, 1.0, 1.5)},
        },
        "express_cost": 45.0,
    },
    "M02": {
        "name": "NTWL-32306 – Tapered roller bearing 32306",
        "group": "mechanical",
        "pert": {
            "AT": {"normal": (7.0, 9.0, 13.0), "express": (4.0, 6.0, 8.0)},
            "BE": {"normal": (2.0, 3.0, 5.0),  "express": (0.5, 1.0, 1.0)},
        },
        "express_cost": 55.0,
    },
    "M03": {
        "name": "SP TAPERED ROLLER BEARING 30306",
        "group": "mechanical",
        "pert": {
            "AT": {"normal": (5.0, 8.0, 12.0), "express": (5.0, 7.0, 10.0)},
            "BE": {"normal": (2.0, 3.0, 4.0),  "express": (0.5, 1.0, 1.5)},
        },
        "express_cost": 48.0,
    },
    "M04": {
        "name": "SP TAPERED ROLLER BEARING 32206",
        "group": "mechanical",
        "pert": {
            "AT": {"normal": (6.0, 8.0, 12.0), "express": (6.0, 7.0, 8.0)},
            "BE": {"normal": (2.0, 3.0, 5.0),  "express": (1.0, 1.0, 1.0)},
        },
        "express_cost": 52.0,
    },
    "M05": {
        "name": "SP SHAFT SEAL RING 70X110X8 NBRSL",
        "group": "mechanical",
        "pert": {
            "AT": {"normal": (8.0, 10.0, 13.0), "express": (4.0, 6.0, 11.0)},
            "BE": {"normal": (2.0, 3.0, 4.0),   "express": (1.0, 1.0, 1.0)},
        },
        "express_cost": 50.0,
    },
    "M06": {
        "name": "SP DISTANCE SLEEVE WG20 F07, K07 70X55",
        "group": "mechanical",
        "pert": {
            "AT": {"normal": (8.0, 10.0, 14.0), "express": (5.0, 7.0, 10.0)},
            "BE": {"normal": (3.0, 3.0, 4.0),   "express": (1.0, 1.0, 2.0)},
        },
        "express_cost": 46.0,
    },
    "M07": {
        "name": "SP BEARING PLUG 72X9",
        "group": "mechanical",
        "pert": {
            "AT": {"normal": (7.0, 9.0, 11.0), "express": (6.0, 7.0, 8.0)},
            "BE": {"normal": (2.0, 3.0, 4.0),  "express": (0.5, 1.0, 1.0)},
        },
        "express_cost": 53.0,
    },
    "M08": {
        "name": "NTEV-T1/4Z – Vent plug T.R1/4Z",
        "group": "mechanical",
        "pert": {
            "AT": {"normal": (7.0, 9.0, 11.0), "express": (4.0, 6.0, 8.0)},
            "BE": {"normal": (2.0, 3.0, 5.0),  "express": (1.0, 1.0, 2.0)},
        },
        "express_cost": 51.0,
    },

    # ---------- ELECTRICAL ----------
    "E01": {
        "name": "KIT INPUT ADAPTER WG20 S142 K24A",
        "group": "electrical",
        "pert": {
            "AT": {"normal": (9.0, 12.0, 15.0), "express": (7.0, 9.0, 11.0)},
            "BE": {"normal": (3.0, 4.0, 5.0),   "express": (2.0, 2.0, 2.0)},
        },
        "express_cost": 48.0,
    },
    "E02": {
        "name": "SP ADAPTER FLANGE WG20 C120/FR200",
        "group": "electrical",
        "pert": {
            "AT": {"normal": (9.0, 12.0, 15.0), "express": (6.0, 9.0, 12.0)},
            "BE": {"normal": (3.0, 4.0, 6.0),   "express": (1.0, 2.0, 3.0)},
        },
        "express_cost": 52.0,
    },
    "E03": {
        "name": "SP INSPECTION COVER WG20 K07",
        "group": "electrical",
        "pert": {
            "AT": {"normal": (10.0, 12.0, 16.0), "express": (7.0, 8.0, 13.0)},
            "BE": {"normal": (3.0, 4.0, 5.0),    "express": (2.0, 2.0, 3.0)},
        },
        "express_cost": 50.0,
    },
    "E04": {
        "name": "SP BEVEL PAIR WG20 K07 Z29/17",
        "group": "electrical",
        "pert": {
            "AT": {"normal": (10.0, 12.0, 14.0), "express": (8.0, 9.0, 10.0)},
            "BE": {"normal": (3.0, 4.0, 5.0),    "express": (2.0, 2.0, 2.0)},
        },
        "express_cost": 46.0,
    },
    "E05": {
        "name": "SP PINION SHAFT WG20 K07 Z15",
        "group": "electrical",
        "pert": {
            "AT": {"normal": (10.0, 13.0, 16.0), "express": (6.0, 9.0, 13.0)},
            "BE": {"normal": (4.0, 4.0, 5.0),    "express": (1.0, 2.0, 3.0)},
        },
        "express_cost": 54.0,
    },
    "E06": {
        "name": "SP PINION WG20 120 Z26C22",
        "group": "electrical",
        "pert": {
            "AT": {"normal": (10.0, 13.0, 16.0), "express": (7.0, 10.0, 11.0)},
            "BE": {"normal": (3.0, 4.0, 6.0),    "express": (2.0, 2.0, 3.0)},
        },
        "express_cost": 49.0,
    },
    "E07": {
        "name": "SP HOLLOW SHAFT WG20 F07 50mm",
        "group": "electrical",
        "pert": {
            "AT": {"normal": (9.0, 11.0, 15.0), "express": (8.0, 9.0, 11.0)},
            "BE": {"normal": (3.0, 4.0, 5.0),   "express": (2.0, 2.0, 2.0)},
        },
        "express_cost": 51.0,
    },
    "E08": {
        "name": "SP OUTPUT GEAR WG20 K07 Z84",
        "group": "electrical",
        "pert": {
            "AT": {"normal": (9.0, 11.0, 15.0), "express": (7.0, 9.0, 12.0)},
            "BE": {"normal": (4.0, 4.0, 5.0),   "express": (1.0, 2.0, 3.0)},
        },
        "express_cost": 47.0,
    },
    "E09": {
        "name": "SP GEAR HOUSING WG20 K07 B35 MACHINED",
        "group": "electrical",
        "pert": {
            "AT": {"normal": (10.0, 12.0, 14.0), "express": (6.0, 8.0, 12.0)},
            "BE": {"normal": (3.0, 4.0, 5.0),    "express": (2.0, 2.0, 2.0)},
        },
        "express_cost": 53.0,
    },
    "E10": {
        "name": "SP GEAR UNIT WG20 072 Z075",
        "group": "electrical",
        "pert": {
            "AT": {"normal": (10.0, 12.0, 14.0), "express": (8.0, 10.0, 11.0)},
            "BE": {"normal": (3.0, 4.0, 6.0),    "express": (2.0, 2.0, 3.0)},
        },
        "express_cost": 50.0,
    },

    # ---------- CASTING ----------
    "C01": {
        "name": "SP ADJUSTING WASHER DIN988 60X72X0.1mm",
        "group": "casting",
        "pert": {
            "AT": {"normal": (1.0, 3.0, 6.0), "express": (1.0, 2.0, 5.0)},
            "BE": {"normal": (1.0, 1.0, 1.0), "express": (1.0, 1.0, 1.0)},
        },
        "express_cost": 48.0,
    },
    "C02": {
        "name": "SP RETAINING RING DIN472 J110",
        "group": "casting",
        "pert": {
            "AT": {"normal": (2.0, 3.0, 6.0), "express": (1.0, 2.0, 4.0)},
            "BE": {"normal": (1.0, 1.0, 2.0), "express": (0.5, 1.0, 2.0)},
        },
        "express_cost": 52.0,
    },
    "C03": {
        "name": "SP PARALLEL KEY B14X9X40 HARD",
        "group": "casting",
        "pert": {
            "AT": {"normal": (2.0, 3.0, 6.0), "express": (2.0, 2.0, 4.0)},
            "BE": {"normal": (1.0, 1.0, 1.0), "express": (1.0, 1.0, 1.0)},
        },
        "express_cost": 50.0,
    },
    "C04": {
        "name": "SP RETAINING RING DIN472 J72",
        "group": "casting",
        "pert": {
            "AT": {"normal": (2.0, 3.0, 6.0), "express": (1.0, 2.0, 5.0)},
            "BE": {"normal": (1.0, 1.0, 2.0), "express": (1.0, 1.0, 1.0)},
        },
        "express_cost": 49.0,
    },
    "C05": {
        "name": "SP SUPPORTING RING DIN988 50X62X3mm",
        "group": "casting",
        "pert": {
            "AT": {"normal": (2.0, 3.0, 6.0), "express": (1.0, 3.0, 4.0)},
            "BE": {"normal": (1.0, 1.0, 1.0), "express": (1.0, 1.0, 1.0)},
        },
        "express_cost": 51.0,
    },
    "C06": {
        "name": "SP THREADED PLUG DIN908 R1/4Z",
        "group": "casting",
        "pert": {
            "AT": {"normal": (2.0, 3.0, 6.0), "express": (2.0, 2.0, 3.0)},
            "BE": {"normal": (1.0, 1.0, 2.0), "express": (1.0, 1.0, 1.0)},
        },
        "express_cost": 47.0,
    },
    "C07": {
        "name": "SP SUPPORTING RING DIN988 25X35X2mm",
        "group": "casting",
        "pert": {
            "AT": {"normal": (2.0, 3.0, 6.0), "express": (1.0, 2.0, 5.0)},
            "BE": {"normal": (1.0, 1.0, 1.0), "express": (1.0, 1.0, 2.0)},
        },
        "express_cost": 53.0,
    },
    "C08": {
        "name": "SP RETAINING RING DIN472 J62",
        "group": "casting",
        "pert": {
            "AT": {"normal": (2.0, 3.0, 6.0), "express": (1.0, 2.0, 4.0)},
            "BE": {"normal": (1.0, 1.0, 2.0), "express": (1.0, 1.0, 1.5)},
        },
        "express_cost": 50.0,
    },
    "C09": {
        "name": "SP PARALLEL KEY B8X5X20 HARD",
        "group": "casting",
        "pert": {
            "AT": {"normal": (1.0, 3.0, 5.0), "express": (2.0, 2.0, 4.0)},
            "BE": {"normal": (1.0, 1.0, 1.0), "express": (0.5, 1.0, 1.0)},
        },
        "express_cost": 48.0,
    },
    "C10": {
        "name": "SP HEX BOLT DIN933 M8X20",
        "group": "casting",
        "pert": {
            "AT": {"normal": (2.0, 3.0, 6.0), "express": (1.0, 3.0, 5.0)},
            "BE": {"normal": (1.0, 1.0, 2.0), "express": (1.0, 1.0, 1.0)},
        },
        "express_cost": 52.0,
    },
    "C11": {
        "name": "SP SUPPORTING RING DIN988 56X72X3mm",
        "group": "casting",
        "pert": {
            "AT": {"normal": (2.0, 3.0, 6.0), "express": (1.0, 2.0, 4.0)},
            "BE": {"normal": (1.0, 1.0, 1.0), "express": (1.0, 1.0, 2.0)},
        },
        "express_cost": 49.0,
    },
    "C12": {
        "name": "SP RETAINING RING DIN471 A25",
        "group": "casting",
        "pert": {
            "AT": {"normal": (2.0, 3.0, 5.0), "express": (2.0, 2.0, 3.0)},
            "BE": {"normal": (1.0, 1.0, 1.0), "express": (1.0, 1.0, 1.0)},
        },
        "express_cost": 51.0,
    },
    "C13": {
        "name": "SP PARALLEL KEY B8X7X22 HARD",
        "group": "casting",
        "pert": {
            "AT": {"normal": (2.0, 3.0, 5.0), "express": (1.0, 2.0, 5.0)},
            "BE": {"normal": (1.0, 1.0, 1.0), "express": (1.0, 1.0, 1.0)},
        },
        "express_cost": 50.0,
    },
    "C14": {
        "name": "SP ADJUSTING WASHER DIN988 50X62X0.1mm",
        "group": "casting",
        "pert": {
            "AT": {"normal": (3.0, 3.0, 5.0), "express": (1.0, 3.0, 4.0)},
            "BE": {"normal": (1.0, 1.0, 2.0), "express": (1.0, 1.0, 2.0)},
        },
        "express_cost": 48.0,
    },
    "C15": {
        "name": "SP STUD SCREW M10X25",
        "group": "casting",
        "pert": {
            "AT": {"normal": (3.0, 3.0, 5.0), "express": (2.0, 2.0, 4.0)},
            "BE": {"normal": (1.0, 1.0, 2.0), "express": (1.0, 1.0, 1.0)},
        },
        "express_cost": 52.0,
    },
    "C16": {
        "name": "SP HEXAGONAL NUT DIN934 M10",
        "group": "casting",
        "pert": {
            "AT": {"normal": (3.0, 3.0, 5.0), "express": (1.0, 2.0, 5.0)},
            "BE": {"normal": (1.0, 1.0, 1.0), "express": (1.0, 1.0, 1.0)},
        },
        "express_cost": 49.0,
    },
    "C17": {
        "name": "SP HEX SOCKET SCREW M6X16 DIN6912",
        "group": "casting",
        "pert": {
            "AT": {"normal": (3.0, 3.0, 5.0), "express": (1.0, 2.0, 4.0)},
            "BE": {"normal": (1.0, 1.0, 2.0), "express": (0.5, 1.0, 1.0)},
        },
        "express_cost": 51.0,
    },
    "C18": {
        "name": "SP GASKET WG20 K07",
        "group": "casting",
        "pert": {
            "AT": {"normal": (3.0, 3.0, 5.0), "express": (2.0, 3.0, 4.0)},
            "BE": {"normal": (1.0, 1.0, 1.0), "express": (1.0, 1.0, 1.0)},
        },
        "express_cost": 50.0,
    },
    "C19": {
        "name": "SP GASKET WG20 C120",
        "group": "casting",
        "pert": {
            "AT": {"normal": (3.0, 3.0, 4.0), "express": (1.0, 2.0, 5.0)},
            "BE": {"normal": (1.0, 1.0, 2.0), "express": (1.0, 1.0, 2.0)},
        },
        "express_cost": 48.0,
    },
    "C20": {
        "name": "SP SEAL RING DIN7603-CU 13X18X1.5mm",
        "group": "casting",
        "pert": {
            "AT": {"normal": (2.0, 3.0, 4.0), "express": (1.0, 2.0, 4.0)},
            "BE": {"normal": (1.0, 1.0, 1.0), "express": (1.0, 1.0, 1.0)},
        },
        "express_cost": 52.0,
    },
    "C21": {
        "name": "SP GASKET WG20 R200",
        "group": "casting",
        "pert": {
            "AT": {"normal": (2.0, 3.0, 4.0), "express": (2.0, 2.0, 3.0)},
            "BE": {"normal": (1.0, 1.0, 2.0), "express": (1.0, 1.0, 2.0)},
        },
        "express_cost": 50.0,
    },
}

PART_IDS_BY_GROUP: Dict[str, List[str]] = {
    "mechanical": [pid for pid, p in PARTS.items() if p["group"] == "mechanical"],
    "electrical": [pid for pid, p in PARTS.items() if p["group"] == "electrical"],
    "casting": [pid for pid, p in PARTS.items() if p["group"] == "casting"],
}

PART_EXPRESS_CANDIDATES: List[str] = list(PARTS.keys())


# ---------- Missing parts scenario ----------

def make_missing_parts_list(selected_part_ids: List[str]) -> List[str]:
    """
    We represent missing parts simply as a list of part IDs (Mxx, Exx, Cxx).
    """
    return selected_part_ids[:]  # shallow copy


# ---------- Sampling activity durations ----------

def sample_group_delivery_time(
    site: str,
    group: str,
    missing_part_ids: List[str],
    express_set: Set[str],
) -> float:
    """
    Sample delivery time for a group (mechanical/electrical/casting) at a site.
    - All missing parts are ordered in parallel.
    - Group lead time = max of the sampled lead times of all missing parts.
    - Parts that are not missing contribute 0.
    """
    times: List[float] = []

    for pid in PART_IDS_BY_GROUP[group]:
        if pid not in missing_part_ids:
            continue

        part = PARTS[pid]
        pert_info = part["pert"][site]
        use_express = pid in express_set
        a, m, b = pert_info["express" if use_express else "normal"]
        t = sample_pert(a, m, b)
        times.append(t)

    if not times:
        return 0.0

    return max(times)


def sample_activity_duration(
    site: str,
    act: Activity,
    express_set: Set[str],
    missing_part_ids: List[str],
) -> float:
    """
    Sample the duration of one activity given the site, express-set and missing parts.
    """
    if act.id == "b":
        return sample_group_delivery_time(site, "mechanical", missing_part_ids, express_set)
    if act.id == "c":
        return sample_group_delivery_time(site, "electrical", missing_part_ids, express_set)
    if act.id == "d":
        return sample_group_delivery_time(site, "casting", missing_part_ids, express_set)

    # Internal activities: use activity-level PERT (express or normal)
    use_express = act.id in express_set
    a, m, b = act.express_pert if use_express else act.normal_pert
    return sample_pert(a, m, b)


# ---------- CPM ----------

def compute_makespan(durations: Dict[str, float]) -> float:
    """Compute makespan via simple CPM (forward pass only)."""
    earliest_finish: Dict[str, float] = {}
    for act_id in TOPO_ORDER:
        act = ACTIVITIES[act_id]
        if not act.predecessors:
            est = 0.0
        else:
            est = max(earliest_finish[p] for p in act.predecessors)
        earliest_finish[act_id] = est + durations[act_id]
    return earliest_finish["n"]


# ---------- Monte Carlo simulation ----------

def simulate_lead_times(
    site: str,
    express_set: Set[str],
    missing_part_ids: List[str],
    n_samples: int = N_SAMPLES,
) -> List[float]:
    """
    Simulate n_samples times the total lead time for a given site and express-set.
    """
    T_samples: List[float] = []

    for _ in range(n_samples):
        durations: Dict[str, float] = {}
        for act_id, act in ACTIVITIES.items():
            durations[act_id] = sample_activity_duration(site, act, express_set, missing_part_ids)
        T = compute_makespan(durations)
        T_samples.append(T)

    return T_samples


# ---------- Cost model ----------

def churn_prob(delay: float) -> float:
    """
    Probability of churn as a function of the number of days late.
    Logistic S-curve:
    - around D_mid ≈ 4 days late => ~50% churn
    - k controls steepness
    """
    if delay <= 0:
        return 0.0

    D_mid = 4.0
    k = 1.0

    x = delay - D_mid
    p = 1.0 / (1.0 + math.exp(-k * x))
    return min(max(p, 0.0), 1.0)


def cost_components(
    T: float,
    L: float,
    customer_value: float = CUSTOMER_VALUE,
    discount_per_day: float = DISCOUNT_PER_DAY,
):
    """
    Return all components of the late cost:
    - delay:       max(T-L, 0)
    - p_churn:     churn probability
    - discount:    discount/compensation (per day late)
    - churn_cost:  expected lost customer value
    - total:       discount + churn_cost
    """
    delay = max(T - L, 0.0)
    if delay <= 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    p_churn = churn_prob(delay)
    discount_cost = discount_per_day * delay
    churn_cost = p_churn * customer_value
    total = discount_cost + churn_cost

    return delay, p_churn, discount_cost, churn_cost, total


def total_express_cost(
    site: str,
    express_set: Set[str],
    missing_part_ids: List[str],
) -> float:
    """
    Total internal express cost:
    - Part-level express: pay only if part is missing.
    - Activity-level express: pay express_cost of activity.
    """
    cost = 0.0

    # Part-level express
    for pid in PART_EXPRESS_CANDIDATES:
        if pid not in express_set:
            continue
        if pid not in missing_part_ids:
            continue  # no order -> no express cost
        cost += PARTS[pid]["express_cost"]

    # Activity-level express
    for aid in ACTIVITY_EXPRESS_CANDIDATES:
        if aid not in express_set:
            continue
        act = ACTIVITIES[aid]
        cost += act.express_cost

    return cost


# ---------- Evaluation of a strategy for a given service and site ----------

def evaluate_strategy_for_service(
    service_type: str,
    site: str,
    express_set: Set[str],
    missing_part_ids: List[str],
    n_samples: int = N_SAMPLES,
) -> Dict[str, float]:
    """
    Compute KPIs and expected profit for a given service_type ('normal' or 'express')
    and given site ('AT' or 'BE') and express_set.
    """
    if service_type == "normal":
        L = 14.0
        margin = BASE_MARGIN
    elif service_type == "express":
        L = 7.0
        margin = BASE_MARGIN + EXPRESS_SURCHARGE
    else:
        raise ValueError("service_type must be 'normal' or 'express'")

    if RANDOM_SEED is not None:
        random.seed(RANDOM_SEED)

    T_samples = simulate_lead_times(site, express_set, missing_part_ids, n_samples)

    n = len(T_samples)
    sum_T = 0.0
    sum_delay = 0.0
    sum_p_churn = 0.0
    sum_discount_cost = 0.0
    sum_churn_cost = 0.0
    sum_late_cost = 0.0
    count_on_time = 0
    count_late = 0
    count_late_5 = 0

    for T in T_samples:
        sum_T += T
        delay, p_churn, discount_cost, churn_cost, total_cost = cost_components(T, L)

        sum_delay += delay
        sum_p_churn += p_churn
        sum_discount_cost += discount_cost
        sum_churn_cost += churn_cost
        sum_late_cost += total_cost

        if delay <= 0:
            count_on_time += 1
        else:
            count_late += 1
            if delay > 5.0:
                count_late_5 += 1

    avg_T = sum_T / n
    avg_delay = sum_delay / n
    avg_churn_prob = sum_p_churn / n
    prob_on_time = count_on_time / n
    prob_late = count_late / n
    prob_more_than_5_late = count_late_5 / n

    expected_discount_cost = sum_discount_cost / n
    expected_churn_cost = sum_churn_cost / n
    expected_late_cost = sum_late_cost / n

    expr_cost = total_express_cost(site, express_set, missing_part_ids)
    expected_profit = margin - expr_cost - expected_late_cost

    return {
        "site": site,
        "L": L,
        "margin": margin,
        "express_cost": expr_cost,
        "avg_T": avg_T,
        "avg_delay": avg_delay,
        "avg_churn_prob": avg_churn_prob,
        "prob_on_time": prob_on_time,
        "prob_late": prob_late,
        "prob_more_than_5_late": prob_more_than_5_late,
        "expected_discount_cost": expected_discount_cost,
        "expected_churn_cost": expected_churn_cost,
        "expected_late_cost": expected_late_cost,
        "expected_profit": expected_profit,
    }


# ---------- Express decision optimisation (greedy hill-climbing) ----------

def get_all_express_candidates() -> List[str]:
    """
    All IDs that can be set to express:
    - part-level candidates
    - activity-level candidates
    """
    return PART_EXPRESS_CANDIDATES + ACTIVITY_EXPRESS_CANDIDATES


def find_best_express_strategy_for_site(
    service_type: str,
    site: str,
    missing_part_ids: List[str],
    n_samples: int = N_SAMPLES,
) -> Tuple[Set[str], Dict[str, float]]:
    """
    Use a greedy hill-climbing search over express candidates:
    - Start with no express.
    - Iteratively toggle the candidate that yields the best positive improvement
      in expected profit.
    - Stop when no further improvement is possible.
    """
    candidates = get_all_express_candidates()
    express_set: Set[str] = set()

    base_metrics = evaluate_strategy_for_service(service_type, site, express_set, missing_part_ids, n_samples)
    base_profit = base_metrics["expected_profit"]

    improved = True
    best_metrics = base_metrics

    while improved:
        improved = False
        best_candidate = None
        best_candidate_profit = base_profit
        best_candidate_metrics = best_metrics

        for cid in candidates:
            # toggle this candidate
            if cid in express_set:
                toggled = set(express_set)
                toggled.remove(cid)
            else:
                toggled = set(express_set)
                toggled.add(cid)

            metrics = evaluate_strategy_for_service(service_type, site, toggled, missing_part_ids, n_samples)
            profit = metrics["expected_profit"]

            if profit > best_candidate_profit + 1e-6:
                best_candidate_profit = profit
                best_candidate = cid
                best_candidate_metrics = metrics

        if best_candidate is not None:
            express_set.symmetric_difference_update({best_candidate})
            base_profit = best_candidate_profit
            best_metrics = best_candidate_metrics
            improved = True

    return express_set, best_metrics


# ---------- Expected schedule for Gantt chart ----------

def build_expected_schedule(
    site: str,
    express_set: Set[str],
    missing_part_ids: List[str],
) -> Tuple[List[Dict[str, Any]], float]:
    """
    Build a deterministic schedule based on PERT means and return:
      - list of {ActivityId, Activity, Start, Finish, Duration}
      - total project duration
    """
    # 1) mean duration per activity
    durations: Dict[str, float] = {}

    # group-level mean durations for b/c/d based on PERT means of parts
    def group_mean_duration(group: str) -> float:
        times: List[float] = []
        for pid in PART_IDS_BY_GROUP[group]:
            if pid not in missing_part_ids:
                continue
            part = PARTS[pid]
            pert_info = part["pert"][site]
            use_express = pid in express_set
            a, m, b = pert_info["express" if use_express else "normal"]
            times.append(mean_pert(a, m, b))
        if not times:
            return 0.0
        return max(times)

    for act_id, act in ACTIVITIES.items():
        if act.id == "b":
            durations[act_id] = group_mean_duration("mechanical")
        elif act.id == "c":
            durations[act_id] = group_mean_duration("electrical")
        elif act.id == "d":
            durations[act_id] = group_mean_duration("casting")
        else:
            use_express = act.id in express_set
            a, m, b = act.express_pert if use_express else act.normal_pert
            durations[act_id] = mean_pert(a, m, b)

    # 2) earliest start / finish via CPM
    es: Dict[str, float] = {}
    ef: Dict[str, float] = {}

    for act_id in TOPO_ORDER:
        act = ACTIVITIES[act_id]
        if not act.predecessors:
            es[act_id] = 0.0
        else:
            es[act_id] = max(ef[p] for p in act.predecessors)
        ef[act_id] = es[act_id] + durations[act_id]

    total_duration = ef["n"]

    # 3) list for Gantt (skip dummy 'n')
    schedule: List[Dict[str, Any]] = []
    for act_id in TOPO_ORDER:
        if act_id == "n":
            continue
        act = ACTIVITIES[act_id]
        schedule.append(
            {
                "ActivityId": act_id,
                "Activity": act.name,
                "Start": es[act_id],
                "Finish": ef[act_id],
                "Duration": durations[act_id],
            }
        )

    schedule.sort(key=lambda x: x["Start"])
    return schedule, total_duration
