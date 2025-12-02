# app.py
import streamlit as st
import matplotlib.pyplot as plt

from engine import (
    make_missing_parts_dict,
    find_best_express_strategy_for_service,
    ACTIVITIES,
    build_expected_schedule,
)

st.set_page_config(page_title="Lead Time & Express Crash Tool", layout="centered")

st.title("🛠️ Lead Time Monte Carlo & Crash Decision Tool")

st.markdown(
    """
Deze tool:
- laat de **klant** kiezen tussen normale levering (14 dagen) of express (7 dagen, +€200),
- laat jou aanduiden welke onderdelen ontbreken,
- en beslist vervolgens **zelf welke activiteiten express (gecrashed) moeten worden**
  om de verwachte winst te maximaliseren.
"""
)

# ---- Input: service type ----
service_type = st.radio(
    "Kies de leveroptie",
    options=["normal", "express"],
    format_func=lambda x: "Normale levering (14 dagen)" if x == "normal" else "Express levering (7 dagen, +€200)",
)

# ---- Input: missing parts ----
st.subheader("Ontbrekende onderdelen")
col1, col2, col3 = st.columns(3)
with col1:
    mech_missing = st.checkbox("Mechanical part ontbreekt (b)", value=True)
with col2:
    elec_missing = st.checkbox("Electrical part ontbreekt (c)", value=True)
with col3:
    cast_missing = st.checkbox("Casting part ontbreekt (d)", value=True)

missing_parts = make_missing_parts_dict(
    mech_missing=mech_missing,
    elec_missing=elec_missing,
    cast_missing=cast_missing,
)

# ---- Run button ----
if st.button("Optimaliseer express-crashing met Monte Carlo"):
    with st.spinner("Monte Carlo simulatie en optimalisatie uitvoeren..."):
        best_set, metrics = find_best_express_strategy_for_service(
            service_type, missing_parts
        )

    st.success("Optimalisatie afgerond ✅")

    # ---- Toon beloofde levertijd en basis-KPI's ----
    st.subheader("Resultaten voor gekozen service-optie")

    colA, colB = st.columns(2)
    with colA:
        st.metric("Beloofde levertijd L", f"{metrics['L']:.1f} dagen")
        st.metric("Gemiddelde doorlooptijd", f"{metrics['avg_T']:.2f} dagen")
        st.metric("Gemiddelde vertraging", f"{metrics['avg_delay']:.2f} dagen")
    with colB:
        st.metric("Kans op tijd", f"{metrics['prob_on_time']*100:.1f} %")
        st.metric("Kans te laat", f"{metrics['prob_late']*100:.1f} %")
        st.metric("Gemiddelde churn-kans", f"{metrics['avg_churn_prob']*100:.1f} %")

    st.markdown(
        f"- **Kans > 5 dagen te laat:** {metrics['prob_more_than_5_late']*100:.1f} %"
    )

    # ---- Kostenopbouw ----
    st.subheader("Kostenopbouw per order (verwacht)")

    colC, colD = st.columns(2)
    with colC:
        st.metric("Verwachte korting / compensatie", f"€ {metrics['expected_discount_cost']:.0f}")
        st.metric("Verwachte churn-kost", f"€ {metrics['expected_churn_cost']:.0f}")
        st.metric("Totale kost te laat (verwacht)", f"€ {metrics['expected_late_cost']:.0f}")
    with colD:
        st.metric("Marge (incl. eventuele express-toeslag)", f"€ {metrics['margin']:.0f}")
        st.metric("Interne expresskosten", f"€ {metrics['express_cost']:.0f}")
        st.metric("Verwachte winst", f"€ {metrics['expected_profit']:.0f}")

    st.caption(
        "Totale verwachte winst = marge − interne expresskosten − (kortingskost + expected churn-kost)."
    )

    # ---- Toon gekozen express-activiteiten ----
    st.subheader("Gecrashte (express) activiteiten volgens het model")

    if best_set:
        for act_id in best_set:
            act = ACTIVITIES[act_id]
            st.write(f"- **{act_id}** – {act.name} (extra interne expresskost: €{act.express_cost:.0f})")
    else:
        st.write("Geen activiteiten worden gecrashed; alles loopt op normale snelheid.")

    st.caption(
        "Het model kiest express-activiteiten enkel als de besparing in verwachte boetes "
        "groter is dan de extra interne expresskost."
    )

    # ---- Gantt chart met PERT-gemiddelden ----
    st.subheader("Gantt chart met PERT-gemiddelde doorlooptijden")

    schedule, total_duration = build_expected_schedule(best_set, missing_parts)

    if schedule:
        activities = [row["Activity"] for row in schedule]
        starts = [row["Start"] for row in schedule]
        durations = [row["Duration"] for row in schedule]

        y_pos = list(range(len(activities)))

        fig, ax = plt.subplots(figsize=(10, 6))

        # horizontale balken
        ax.barh(
            y_pos,
            durations,
            left=starts,
            height=0.6,
            align="center",
            edgecolor="black",
            alpha=0.6,
        )

        # duurlabels in de balk
        for y, s, d in zip(y_pos, starts, durations):
            if d > 0:
                ax.text(
                    s + d / 2.0,
                    y,
                    f"{d:.2f}",
                    va="center",
                    ha="center",
                    fontsize=8,
                )

        # y-as labels
        ax.set_yticks(y_pos)
        ax.set_yticklabels(activities)
        ax.invert_yaxis()  # bovenaan eerst

        ax.set_xlabel("Time (days)")
        ax.set_title("Gantt Chart with PERT Durations")

        # verticale lijn voor totale projectduur
        ax.axvline(total_duration, color="red", linestyle="--")
        ax.text(
            total_duration,
            1.02,
            f"Total Duration: {total_duration:.2f} d",
            transform=ax.get_xaxis_transform(),
            color="red",
            ha="right",
            va="bottom",
        )

        ax.grid(axis="x", linestyle="--", alpha=0.4)

        st.pyplot(fig)
    else:
        st.info("Geen Gantt-data beschikbaar voor dit scenario.")

else:
    st.info("Kies eerst de leveroptie en ontbrekende onderdelen, en klik dan op de knop.")
