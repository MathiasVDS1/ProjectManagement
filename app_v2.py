# app_v2.py
import streamlit as st
import matplotlib.pyplot as plt

from engine_v2 import (
    PARTS,
    PART_IDS_BY_GROUP,
    make_missing_parts_list,
    find_best_express_strategy_for_site,
    build_expected_schedule,
    ACTIVITIES,
    ACTIVITY_EXPRESS_CANDIDATES,
)

st.set_page_config(page_title="Lead Time & Site Selection Tool", layout="wide")

st.title("🛠️ Lead Time Monte Carlo & Express Decision Tool (AT vs BE)")

st.markdown(
    """
This tool:
- lets the **customer** choose between normal delivery (14 days) or express (7 days, +€250),
- lets you specify which **components are missing** for **Austria and Belgium separately**,
- decides **which components and internal activities should be expedited (express)**,
- and can compare **production in Austria vs Belgium** to maximise expected profit.
"""
)

# ------------ Inputs ------------

# Service type
service_type = st.radio(
    "Choose service level",
    options=["normal", "express"],
    format_func=lambda x: "Normal delivery (14 days)" if x == "normal" else "Express delivery (7 days, +€250)",
    horizontal=True,
)

# Site mode
site_mode = st.radio(
    "Choose production site mode",
    options=["AT", "BE", "auto"],
    format_func=lambda x: {
        "AT": "Austria only",
        "BE": "Belgium only",
        "auto": "Automatic: choose best site",
    }[x],
    horizontal=True,
)

st.markdown("### Missing components per site")

tab_AT, tab_BE = st.tabs(["Austria (AT) inventory", "Belgium (BE) inventory"])

missing_AT_ids = []
missing_BE_ids = []

# ----- Austria inventory -----
with tab_AT:
    st.markdown("#### Missing components in Austria (AT)")
    col_mech_AT, col_elec_AT, col_cast_AT = st.columns(3)

    with col_mech_AT:
        st.markdown("**Mechanical parts (AT)**")
        mech_names_AT = [
            f"{pid} – {PARTS[pid]['name']}" for pid in PART_IDS_BY_GROUP["mechanical"]
        ]
        selected_mech_AT = st.multiselect(
            "Missing mechanical components in Austria",
            options=mech_names_AT,
            default=[],
            key="mech_missing_AT",
        )
        for label in selected_mech_AT:
            pid = label.split(" – ", 1)[0]
            missing_AT_ids.append(pid)

    with col_elec_AT:
        st.markdown("**Electrical parts (AT)**")
        elec_names_AT = [
            f"{pid} – {PARTS[pid]['name']}" for pid in PART_IDS_BY_GROUP["electrical"]
        ]
        selected_elec_AT = st.multiselect(
            "Missing electrical components in Austria",
            options=elec_names_AT,
            default=[],
            key="elec_missing_AT",
        )
        for label in selected_elec_AT:
            pid = label.split(" – ", 1)[0]
            missing_AT_ids.append(pid)

    with col_cast_AT:
        st.markdown("**Casting parts (AT)**")
        cast_names_AT = [
            f"{pid} – {PARTS[pid]['name']}" for pid in PART_IDS_BY_GROUP["casting"]
        ]
        selected_cast_AT = st.multiselect(
            "Missing casting components in Austria",
            options=cast_names_AT,
            default=[],
            key="cast_missing_AT",
        )
        for label in selected_cast_AT:
            pid = label.split(" – ", 1)[0]
            missing_AT_ids.append(pid)

# ----- Belgium inventory -----
with tab_BE:
    st.markdown("#### Missing components in Belgium (BE)")
    col_mech_BE, col_elec_BE, col_cast_BE = st.columns(3)

    with col_mech_BE:
        st.markdown("**Mechanical parts (BE)**")
        mech_names_BE = [
            f"{pid} – {PARTS[pid]['name']}" for pid in PART_IDS_BY_GROUP["mechanical"]
        ]
        selected_mech_BE = st.multiselect(
            "Missing mechanical components in Belgium",
            options=mech_names_BE,
            default=[],
            key="mech_missing_BE",
        )
        for label in selected_mech_BE:
            pid = label.split(" – ", 1)[0]
            missing_BE_ids.append(pid)

    with col_elec_BE:
        st.markdown("**Electrical parts (BE)**")
        elec_names_BE = [
            f"{pid} – {PARTS[pid]['name']}" for pid in PART_IDS_BY_GROUP["electrical"]
        ]
        selected_elec_BE = st.multiselect(
            "Missing electrical components in Belgium",
            options=elec_names_BE,
            default=[],
            key="elec_missing_BE",
        )
        for label in selected_elec_BE:
            pid = label.split(" – ", 1)[0]
            missing_BE_ids.append(pid)

    with col_cast_BE:
        st.markdown("**Casting parts (BE)**")
        cast_names_BE = [
            f"{pid} – {PARTS[pid]['name']}" for pid in PART_IDS_BY_GROUP["casting"]
        ]
        selected_cast_BE = st.multiselect(
            "Missing casting components in Belgium",
            options=cast_names_BE,
            default=[],
            key="cast_missing_BE",
        )
        for label in selected_cast_BE:
            pid = label.split(" – ", 1)[0]
            missing_BE_ids.append(pid)

missing_AT_part_ids = make_missing_parts_list(missing_AT_ids)
missing_BE_part_ids = make_missing_parts_list(missing_BE_ids)

st.markdown("---")

# ------------ Run optimisation ------------

if st.button("Run Monte Carlo & optimise express decisions"):
    if site_mode == "AT" and not missing_AT_part_ids:
        st.warning("No missing components selected for Austria. In that case, all deliveries are instantaneous for AT.")
    if site_mode == "BE" and not missing_BE_part_ids:
        st.warning("No missing components selected for Belgium. In that case, all deliveries are instantaneous for BE.")
    if site_mode == "auto" and not (missing_AT_part_ids or missing_BE_part_ids):
        st.warning("You did not select any missing components for AT or BE. Both sites would have instant deliveries.")

    with st.spinner("Running Monte Carlo simulation and express optimisation..."):

        if site_mode == "AT":
            best_set, metrics = find_best_express_strategy_for_site(
                service_type, "AT", missing_AT_part_ids
            )
            chosen_site = "AT"
            other_site = None
            other_site_metrics = None

        elif site_mode == "BE":
            best_set, metrics = find_best_express_strategy_for_site(
                service_type, "BE", missing_BE_part_ids
            )
            chosen_site = "BE"
            other_site = None
            other_site_metrics = None

        else:
            # Automatic site selection: compare AT vs BE with their own missing-part sets
            best_set_AT, metrics_AT = find_best_express_strategy_for_site(
                service_type, "AT", missing_AT_part_ids
            )
            best_set_BE, metrics_BE = find_best_express_strategy_for_site(
                service_type, "BE", missing_BE_part_ids
            )

            if metrics_AT["expected_profit"] >= metrics_BE["expected_profit"]:
                chosen_site = "AT"
                best_set = best_set_AT
                metrics = metrics_AT
                other_site = "BE"
                other_site_metrics = metrics_BE
            else:
                chosen_site = "BE"
                best_set = best_set_BE
                metrics = metrics_BE
                other_site = "AT"
                other_site_metrics = metrics_AT

    st.success("Optimisation finished ✅")

    st.subheader(f"Selected site: {'Austria' if chosen_site == 'AT' else 'Belgium'}")
    if site_mode == "auto" and other_site_metrics is not None:
        st.markdown(
            f"- Expected profit at chosen site: **€{metrics['expected_profit']:.0f}**  \n"
            f"- Expected profit at other site: **€{other_site_metrics['expected_profit']:.0f}**"
        )

    # ---- KPIs ----
    st.subheader("Key performance indicators")

    colA, colB = st.columns(2)
    with colA:
        st.metric("Promised lead time L", f"{metrics['L']:.1f} days")
        st.metric("Average total lead time", f"{metrics['avg_T']:.2f} days")
        st.metric("Average delay", f"{metrics['avg_delay']:.2f} days")
    with colB:
        st.metric("Probability on time", f"{metrics['prob_on_time']*100:.1f} %")
        st.metric("Probability late", f"{metrics['prob_late']*100:.1f} %")
        st.metric("Average churn probability", f"{metrics['avg_churn_prob']*100:.1f} %")

    st.markdown(
        f"- **Probability of > 5 days late:** {metrics['prob_more_than_5_late']*100:.1f} %"
    )

    # ---- Cost breakdown ----
    st.subheader("Cost breakdown per order (expected values)")

    colC, colD = st.columns(2)
    with colC:
        st.metric("Expected discount/compensation", f"€ {metrics['expected_discount_cost']:.0f}")
        st.metric("Expected churn cost", f"€ {metrics['expected_churn_cost']:.0f}")
        st.metric("Total expected late cost", f"€ {metrics['expected_late_cost']:.0f}")
    with colD:
        st.metric("Margin (incl. express service surcharge)", f"€ {metrics['margin']:.0f}")
        st.metric("Internal express cost", f"€ {metrics['express_cost']:.0f}")
        st.metric("Expected profit", f"€ {metrics['expected_profit']:.0f}")

    st.caption(
        "Expected profit = margin − internal express costs − (discount cost + expected churn cost)."
    )

    # ---- Show express decisions ----
    st.subheader("Express decisions (crashed components and activities)")

    if best_set:
        st.markdown("**Component-level express orders:**")
        any_parts = False
        for cid in sorted(best_set):
            if cid in PARTS:
                any_parts = True
                part = PARTS[cid]
                st.write(
                    f"- {cid} – {part['name']} "
                    f"(express cost: €{part['express_cost']:.0f}, group: {part['group']})"
                )
        if not any_parts:
            st.write("_No parts are expedited._")

        st.markdown("**Activity-level express (internal crashing):**")

        any_acts = False
        for aid in ACTIVITY_EXPRESS_CANDIDATES:
            if aid in best_set:
                any_acts = True
                act = ACTIVITIES[aid]
                st.write(
                    f"- {aid} – {act.name} (internal express cost: €{act.express_cost:.0f})"
                )
        if not any_acts:
            st.write("_No internal activities are crashed._")
    else:
        st.write("No express decisions: everything runs at normal speed.")

    st.caption(
        "The model only chooses express options if the expected reduction in late costs "
        "is larger than the additional internal express costs."
    )

    # ---- Gantt chart ----
    st.subheader("Gantt chart with PERT mean durations")

    if chosen_site == "AT":
        sched_missing = missing_AT_part_ids
    else:
        sched_missing = missing_BE_part_ids

    schedule, total_duration = build_expected_schedule(chosen_site, best_set, sched_missing)

    if schedule:
        activities = [row["Activity"] for row in schedule]
        starts = [row["Start"] for row in schedule]
        durations = [row["Duration"] for row in schedule]

        y_pos = list(range(len(activities)))

        fig, ax = plt.subplots(figsize=(10, 6))

        # horizontal bars
        ax.barh(
            y_pos,
            durations,
            left=starts,
            height=0.6,
            align="center",
            edgecolor="black",
            alpha=0.6,
        )

        # duration labels inside bars
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

        # y-axis labels
        ax.set_yticks(y_pos)
        ax.set_yticklabels(activities)
        ax.invert_yaxis()  # first activity at top

        ax.set_xlabel("Time (days)")
        ax.set_title("Gantt Chart with PERT Mean Durations")

        # vertical line for total project duration
        ax.axvline(total_duration, color="red", linestyle="--")
        ax.text(
            total_duration,
            1.02,
            f"Total duration: {total_duration:.2f} d",
            transform=ax.get_xaxis_transform(),
            color="red",
            ha="right",
            va="bottom",
        )

        ax.grid(axis="x", linestyle="--", alpha=0.4)

        st.pyplot(fig)
    else:
        st.info("No Gantt data available for this scenario.")

else:
    st.info("Select service level, site mode, and missing components for each site, then click the button.")
