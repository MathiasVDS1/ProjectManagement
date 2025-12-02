# engine.py
import random
import itertools
import math
from dataclasses import dataclass
from typing import Dict, List, Tuple, Any

# ---------- Basisparameters ----------

BASE_MARGIN = 1000.0          # marge bij normale levering
EXPRESS_SURCHARGE = 250.0     # extra marge die klant betaalt voor express

CUSTOMER_VALUE = 4000.0       # verwachte toekomstige waarde van de klant (LTV)
DISCOUNT_PER_DAY = 100.0      # korting / schadevergoeding per dag te laat

N_SAMPLES = 5000              # Monte Carlo runs per strategie
RANDOM_SEED = 42              # voor reproduceerbaarheid (optioneel)


# ---------- PERT sampling ----------

def sample_pert(a: float, m: float, b: float, lamb: float = 4.0) -> float:
    """Sample uit een PERT-verdeling met min=a, modus=m, max=b."""
    if b == a:
        return a
    alpha = 1.0 + lamb * (m - a) / (b - a)
    beta = 1.0 + lamb * (b - m) / (b - a)
    x = random.betavariate(alpha, beta)
    return a + x * (b - a)


def mean_pert(a: float, m: float, b: float) -> float:
    """Gemiddelde van een PERT-verdeling."""
    return (a + 4.0 * m + b) / 6.0


# ---------- Activiteiten ----------

@dataclass
class Activity:
    id: str
    name: str
    predecessors: List[str]
    normal_pert: Tuple[float, float, float]
    express_pert: Tuple[float, float, float]
    express_cost: float = 0.0
    can_be_missing: bool = False  # True voor b, c, d


ACTIVITIES: Dict[str, Activity] = {
    "a": Activity("a", "Order Confirmation", [], (0.5, 1.0, 1.0), (0.5, 1.0, 1.0)),
    "b": Activity("b", "Delivery Mechanical", ["a"], (1.0, 3.0, 5.0), (0.5, 1.0, 1.5), 50.0, True),
    "c": Activity("c", "Delivery Electrical", ["a"], (2.0, 4.0, 6.0), (1.0, 2.0, 3.0), 50.0, True),
    "d": Activity("d", "Delivery Casting", ["a"], (0.5, 1.0, 2.0), (0.5, 1.0, 1.5), 50.0, True),
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

# Kandidaten die gecrashed kunnen worden (heeft express_cost > 0)
EXPRESS_CANDIDATES = [act_id for act_id, act in ACTIVITIES.items() if act.express_cost > 0.0]

# Topologische volgorde voor CPM
TOPO_ORDER = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n"]


# ---------- Missing parts scenario ----------

def make_missing_parts_dict(
    mech_missing: bool,
    elec_missing: bool,
    cast_missing: bool,
) -> Dict[str, bool]:
    return {
        "b": mech_missing,
        "c": elec_missing,
        "d": cast_missing,
    }


def sample_activity_duration(
    act: Activity,
    use_express: bool,
    missing_parts: Dict[str, bool],
) -> float:
    """
    Trek een duur voor één activiteit, rekening houdend met:
    - normale vs express distributie
    - eventueel in stock (delivery = 0 tijd)
    """
    # Delivery-activiteiten kunnen 'in stock' zijn
    if act.can_be_missing and not missing_parts.get(act.id, False):
        return 0.0

    a, m, b = act.express_pert if use_express else act.normal_pert
    return sample_pert(a, m, b)


# ---------- CPM ----------

def compute_makespan(durations: Dict[str, float]) -> float:
    """Bereken makespan via simple CPM."""
    earliest_finish: Dict[str, float] = {}
    for act_id in TOPO_ORDER:
        act = ACTIVITIES[act_id]
        if not act.predecessors:
            est = 0.0
        else:
            est = max(earliest_finish[p] for p in act.predecessors)
        earliest_finish[act_id] = est + durations[act_id]
    return earliest_finish["n"]

# ---------- Monte Carlo voor een gegeven express-set ----------

def simulate_lead_times(
    express_set: List[str],
    missing_parts: Dict[str, bool],
    n_samples: int = N_SAMPLES,
) -> List[float]:
    """
    Simuleer n_samples keer totale doorlooptijd voor een gegeven set gecrashte activiteiten.
    """
    T_samples: List[float] = []

    for _ in range(n_samples):
        durations: Dict[str, float] = {}
        for act_id, act in ACTIVITIES.items():
            use_express = act_id in express_set
            durations[act_id] = sample_activity_duration(act, use_express, missing_parts)
        T = compute_makespan(durations)
        T_samples.append(T)

    return T_samples


# ---------- Kosten ----------

def churn_prob(delay: float) -> float:
    """
    Kans op churn als functie van het aantal dagen te laat.
    Logistische S-curve:
    - rond D_mid ≈ 50% churn
    - k bepaalt hoe steil de curve is.
    """
    if delay <= 0:
        return 0.0

    D_mid = 4.0   # bij ~4 dagen te laat: 50% churn
    k = 1.0       # steilheid

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
    Geef alle componenten van de kost terug:
    - delay:       max(T-L, 0)
    - p_churn:     kans op churn
    - discount:    korting / schadevergoeding (per dag te laat)
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


def total_express_cost(express_set: List[str], missing_parts: Dict[str, bool]) -> float:
    """
    Interne expresskost, rekening houdend met:
    - express_cost van elke activiteit
    - bij b,c,d enkel als part effectief ontbreekt.
    """
    cost = 0.0
    for act_id in express_set:
        act = ACTIVITIES[act_id]
        if act.express_cost <= 0:
            continue
        if act.can_be_missing and not missing_parts.get(act_id, False):
            continue
        cost += act.express_cost
    return cost


# ---------- Evaluatie van een strategie voor een service-type ----------

def evaluate_strategy_for_service(
    service_type: str,
    express_set: List[str],
    missing_parts: Dict[str, bool],
    n_samples: int = N_SAMPLES,
) -> Dict[str, float]:
    """
    Bepaal KPI's en expected profit voor:
    - service_type = "normal": L=14, marge=BASE_MARGIN
    - service_type = "express": L=7, marge=BASE_MARGIN + EXPRESS_SURCHARGE
    en gegeven express_set.

    Geeft veel extra info terug:
    - gemiddelde vertraging
    - kans op te laat zijn
    - gemiddelde churn-kans
    - expected discount cost, churn cost, total late cost
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

    # Simuleer doorlooptijden
    T_samples = simulate_lead_times(express_set, missing_parts, n_samples)

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

    expr_cost = total_express_cost(express_set, missing_parts)
    expected_profit = margin - expr_cost - expected_late_cost

    return {
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


# ---------- Optimale express-set zoeken (crash-beslissing) ----------

def find_best_express_strategy_for_service(
    service_type: str,
    missing_parts: Dict[str, bool],
    n_samples: int = N_SAMPLES,
) -> Tuple[List[str], Dict[str, float]]:
    """
    Probeer alle subsets van EXPRESS_CANDIDATES en kies de express_set
    die de hoogste expected_profit geeft voor de gekozen service.
    Returnt:
      - best_express_set
      - metrics dict (zoals evaluate_strategy_for_service)
    """
    best_set: List[str] = []
    best_metrics: Dict[str, float] = {}
    best_profit = float("-inf")

    for r in range(len(EXPRESS_CANDIDATES) + 1):
        for subset in itertools.combinations(EXPRESS_CANDIDATES, r):
            express_set = list(subset)
            metrics = evaluate_strategy_for_service(
                service_type, express_set, missing_parts, n_samples
            )
            if metrics["expected_profit"] > best_profit:
                best_profit = metrics["expected_profit"]
                best_set = express_set
                best_metrics = metrics

    return best_set, best_metrics


# ---------- Expected schedule voor Gantt-chart ----------

def build_expected_schedule(
    express_set: List[str],
    missing_parts: Dict[str, bool],
) -> Tuple[List[Dict[str, Any]], float]:
    """
    Bouw een deterministische planning op basis van PERT-gemiddelden
    en geef start/finish/duration per activiteit terug + totale projectduur.
    """
    # 1) gemiddelde duur per activiteit
    durations: Dict[str, float] = {}
    for act_id, act in ACTIVITIES.items():
        if act.can_be_missing and not missing_parts.get(act_id, False):
            durations[act_id] = 0.0
            continue

        use_express = act_id in express_set
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

    # 3) lijst voor Gantt (skip dummy 'n')
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
