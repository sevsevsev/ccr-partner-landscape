"""SY26-27 CCR Partner Landscape, a Streamlit app fed by the compiled Google Sheet."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import ccr_data as D

ACCENT = "#2a78d6"
MUTED = "#c3c2b7"
HOLLOW_STROKE = "#898781"
SIZE_PX = {0: 9, 1: 11, 2: 16, 3: 22, 4: 28}
GROUP_LABELS = {"multi": "Two or more organizations", "one": "One organization", "none": "No partner listed"}
TTL_SECONDS = 600

st.set_page_config(page_title="SY26-27 CCR Partner Landscape", page_icon="🏫", layout="wide")


# ---------------------------------------------------------------- data

@st.cache_data(ttl=TTL_SECONDS, show_spinner="Reading the compiled sheet…")
def fetch_raw(sheet_id: str) -> tuple[list[dict], list[dict], list[dict], str]:
    raw = tuple(D.fetch_tab(D.TABS[k], sheet_id) for k in ("programs", "enrollment", "issues"))
    return (*raw, dt.datetime.now().strftime("%b %d, %Y %H:%M"))


def get_landscape() -> tuple[D.Landscape, str]:
    try:
        sheet_id = st.secrets.get("sheet_id", D.SHEET_ID)
    except Exception:  # noqa: BLE001 - no secrets file is the normal case
        sheet_id = D.SHEET_ID
    try:
        p, e, i, at = fetch_raw(sheet_id)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not read the Google Sheet ({exc}). Check that it is shared with 'Anyone with the link'.")
        st.stop()
    return D.build(p, e, i), at


# ---------------------------------------------------------------- state

def init_state():
    for k, v in {"org": "", "goal": "", "school": "", "group": "", "show_all": False}.items():
        st.session_state.setdefault(k, v)


def set_school(name: str):
    st.session_state.school = "" if st.session_state.school == name else name


def fmt(n) -> str:
    return "" if n is None else f"{n:,}"


# ---------------------------------------------------------------- helpers for filters

def orgs_at(rows: list[dict], goal: str, org: str) -> set[str]:
    return {r["organization"] for r in rows if (not goal or goal in r["goals"]) and (not org or r["organization"] == org)}


def school_matches(s: dict, rows: list[dict], goal: str, org: str, group: str, n: int) -> bool:
    return (not group or s["group"] == group) and (not org or any(r["organization"] == org for r in rows)) and (not goal or n > 0)


# ---------------------------------------------------------------- views

def render_header(L: D.Landscape, loaded_at: str):
    o = L.overview
    st.title("SY26-27 CCR Partner Landscape")
    st.markdown(
        f"**{o['programs']}** programs from **{o['organizations']}** organizations reported where they work this year. "
        "Use this page to see where partners overlap, which district high schools have no partner listed yet, "
        f"and who you could coordinate with. **{o['schools_3plus']}** schools host three or more organizations."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Schools with two or more partner organizations", o["schools_multi"])
    c2.metric("Schools with one organization", o["schools_one"])
    c3.metric("District high schools with no partner listed", o["schools_none"], f"about {fmt(o['students_none'])} students", delta_color="off")
    c4.metric("Programs that listed no schools", o["programs_no_school"], "cannot appear in the views below", delta_color="off")
    st.caption(f"Data read from the compiled Google Sheet at {loaded_at}; it refreshes every {TTL_SECONDS // 60} minutes or on demand from the sidebar.")


def render_sidebar(L: D.Landscape):
    with st.sidebar:
        st.header("Filters")
        orgs = L.organizations
        st.selectbox("Your organization", [""] + orgs, format_func=lambda v: "All organizations" if v == "" else D.org_label(v), key="org")
        st.selectbox("Goal area", [""] + D.GOAL_LABELS, format_func=lambda v: "All goal areas" if v == "" else v, key="goal")
        schools = sorted(L.coverage, key=lambda s: s["short"])
        names = [""] + [s["school"] for s in schools]
        labels = {s["school"]: s["short"] + (" (none listed)" if s["orgs"] == 0 else "") for s in schools}
        idx = names.index(st.session_state.school) if st.session_state.school in names else 0
        picked = st.selectbox("School", names, index=idx, format_func=lambda v: "All schools" if v == "" else labels.get(v, v))
        if picked != st.session_state.school:
            st.session_state.school = picked
            st.rerun()
        st.radio("School group", [""] + list(GROUP_LABELS), format_func=lambda v: "All schools" if v == "" else GROUP_LABELS[v], key="group")
        if st.button("Reset filters"):
            for k in ("org", "goal", "school", "group"):
                st.session_state[k] = ""
            st.rerun()
        st.divider()
        if st.button("Refresh data now"):
            fetch_raw.clear()
            st.rerun()
        st.caption("Source: the compiled SY26-27 CCR Program Data sheet (Programs, Enrollment by School and Grade, Issues tabs). "
                   "School list, enrollment and locations: City of Philadelphia public Schools dataset, matched by ULCS code.")


def active_filter_line():
    parts = []
    if st.session_state.org:
        parts.append(D.org_label(st.session_state.org))
    if st.session_state.goal:
        parts.append(st.session_state.goal)
    if st.session_state.school:
        parts.append(st.session_state.school)
    if st.session_state.group:
        parts.append(GROUP_LABELS[st.session_state.group].lower())
    if parts:
        st.info("Showing: " + " · ".join(parts), icon="🔎")


def build_map(L: D.Landscape) -> go.Figure:
    goal, org, group, school = st.session_state.goal, st.session_state.org, st.session_state.group, st.session_state.school
    rows_by_school: dict[str, list[dict]] = {}
    for r in L.school_programs:
        rows_by_school.setdefault(r["school"], []).append(r)
    pts = []
    for s in L.coverage:
        if s["lat"] is None or s["virtual"]:
            continue
        rows = rows_by_school.get(s["school"], [])
        n = len(orgs_at(rows, goal, org)) if (goal or org) else s["orgs"]
        match = school_matches(s, rows, goal, org, group, n)
        hollow = s["orgs"] == 0
        if hollow:
            hover = f"<b>{s['school']}</b><br>No partner listed · {fmt(s['school_enrollment'])} students · grades {s['grade_org'] or ''}<br>{s['setting'] or ''}"
        else:
            shown_orgs = sorted({D.org_label(r['organization']) for r in rows if not goal or goal in r['goals']})
            count = f"{n} of {s['orgs']}" if (goal or org) else str(s["orgs"])
            hover = f"<b>{s['school']}</b><br>{count} organization{'s' if s['orgs'] != 1 else ''} · {s['programs']} program{'s' if s['programs'] != 1 else ''}" \
                    + (f" · {goal}" if goal else "") + "<br>" + "; ".join(shown_orgs)
        pts.append({
            "school": s["school"], "short": s["short"], "lat": s["lat"], "lon": s["lon"],
            "size": SIZE_PX[1] if hollow else SIZE_PX[max(1, min(4, n or 1))],
            "color": "#ffffff" if hollow else (ACCENT if match else MUTED),
            "opacity": 1.0 if hollow else (0.85 if match else 0.45),
            "line_color": "#0b0b0b" if school == s["school"] else (HOLLOW_STROKE if hollow else "#ffffff"),
            "line_width": 3 if school == s["school"] else 1.5,
            "hover": hover, "label": s["short"] if (s["orgs"] >= 3 and not school) or school == s["school"] else "",
        })
    df = pd.DataFrame(pts)
    ring = L.boundary["geometry"]["coordinates"][0]
    fig = go.Figure()
    fig.add_trace(go.Scattermap(lon=[p[0] for p in ring], lat=[p[1] for p in ring], mode="lines",
                                line=dict(color=HOLLOW_STROKE, width=1), hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scattermap(
        lon=df["lon"], lat=df["lat"], mode="markers+text", text=df["label"], textposition="middle right",
        textfont=dict(size=11, color="#52514e"),
        marker=dict(size=df["size"], color=df["color"], opacity=df["opacity"], sizemode="diameter"),
        customdata=df["school"], hovertext=df["hover"], hoverinfo="text", showlegend=False, name="schools",
    ))
    # Marker outlines are drawn as a second trace so hollow and selected rings read in every theme.
    fig.add_trace(go.Scattermap(
        lon=df["lon"], lat=df["lat"], mode="markers",
        marker=dict(size=df["size"] + 3, color=df["line_color"], opacity=1, sizemode="diameter"),
        hoverinfo="skip", showlegend=False,
    ))
    fig.data = (fig.data[0], fig.data[2], fig.data[1])  # outline ring under the fill
    fig.update_layout(
        map=dict(style="carto-positron", center=dict(lat=40.005, lon=-75.13), zoom=10.3),
        margin=dict(l=0, r=0, t=0, b=0), height=520, hoverlabel=dict(bgcolor="white", font_size=12),
    )
    return fig


def render_overlap(L: D.Landscape):
    st.header("Where partners overlap, and where nobody is listed")
    st.markdown("Every district high school, sized by how many partner organizations listed it. Filled circles have a partner; "
                "hollow circles have none listed in this year's submissions. Click a school on the map or in a list to see who is there.")
    fig = build_map(L)
    event = st.plotly_chart(fig, width="stretch", on_select="rerun", selection_mode="points", key="map")
    try:
        pts = event.selection.points if event and event.selection else []
    except AttributeError:
        pts = event.get("selection", {}).get("points", []) if isinstance(event, dict) else []
    if pts:
        picked = pts[0].get("customdata")
        if isinstance(picked, list):
            picked = picked[0]
        if picked and picked != st.session_state.school:
            st.session_state.school = picked
            st.rerun()
    st.caption("Circle size: 1, 2, 3 or 4 organizations. Hollow: no partner listed. Shaded: outside the current filters. "
               "Philadelphia Virtual Academy has no campus and is left off the map.")

    left, right = st.columns([1, 1])
    with left:
        render_school_detail(L)
    with right:
        render_org_ranking(L)

    left, right = st.columns([1, 1])
    with left:
        render_none_list(L)
    with right:
        render_sharing(L)


def effective_school(L: D.Landscape) -> tuple[str, bool]:
    if st.session_state.school:
        return st.session_state.school, False
    return (L.school_orgs[0]["school"] if L.school_orgs else ""), True


def render_school_detail(L: D.Landscape):
    school, is_default = effective_school(L)
    cov = next((s for s in L.coverage if s["school"] == school), None)
    with st.container(border=True):
        st.subheader(school or "Programs at a school")
        if is_default:
            st.caption("Showing the school with the most organizations. Pick any school to change.")
        if not cov:
            st.write("—")
            return
        bits = []
        if cov["orgs"] > 0:
            bits.append(f"{cov['orgs']} organization{'s' if cov['orgs'] != 1 else ''} · {cov['programs']} program{'s' if cov['programs'] != 1 else ''}")
        if cov["school_enrollment"] is not None:
            bits.append(f"{fmt(cov['school_enrollment'])} students (city directory)")
        if cov["grade_org"]:
            bits.append(f"grades {cov['grade_org']}")
        st.caption(" · ".join(bits))
        if cov["orgs"] == 0:
            st.info("No partner program listed this school in SY26-27. Six programs listed no schools at all, so it may still have one on site.")
            return
        so = next((s for s in L.school_orgs if s["school"] == school), None)
        if so:
            strip = " ".join(("🟦" if so[g] else "⬜") + g[1:] for g in D.GRADES)
            st.caption("Grades with partner students: " + strip)
        sg = L.school_goals.get(school, {"covered": [], "not_covered": []})
        st.caption("Goal areas with an organization here: " + ("; ".join(sg["covered"]) or "none") + ".  \n"
                   "Not covered here: " + ("; ".join(sg["not_covered"]) or "none of the goal areas partners cover elsewhere") + ".")
        goal_key = next((k for k, lab in D.GOALS if lab == st.session_state.goal), None)
        targets = {D._pkey(p) for p in L.programs if not goal_key or p.get(goal_key) is True}
        rows = [r for r in L.enrollment if r["school"] == school]
        org_order = sorted({r["organization"] for r in rows}, key=lambda o: (o != st.session_state.org, o))
        table = []
        for o in org_order:
            for r in rows:
                if r["organization"] != o:
                    continue
                tot = "no numbers" if not r["reported"] else fmt(r["total"]) + (" ◌" if r["round"] else "")
                table.append({"Organization": D.org_label(o), "Program": r["program"],
                              "9th": fmt(r["g9"]), "10th": fmt(r["g10"]), "11th": fmt(r["g11"]), "12th": fmt(r["g12"]), "Total": tot,
                              "Selected goal": "yes" if (goal_key and D._key(r) in targets) else ("no" if goal_key else "")})
        df = pd.DataFrame(table)
        if not goal_key:
            df = df.drop(columns=["Selected goal"])
        st.dataframe(df, hide_index=True, width="stretch")
        st.caption("Blank cells were empty in the submission, or the form had no column for that grade. ◌ marks counts that are all "
                   "multiples of 5, which usually means a planned cohort size rather than a roster.")


def render_org_ranking(L: D.Landscape):
    goal, org, group, school = st.session_state.goal, st.session_state.org, st.session_state.group, st.session_state.school
    rows_by_school: dict[str, list[dict]] = {}
    for r in L.school_programs:
        rows_by_school.setdefault(r["school"], []).append(r)
    items = []
    for s in L.coverage:
        if s["orgs"] == 0:
            continue
        rows = rows_by_school.get(s["school"], [])
        n = len(orgs_at(rows, goal, org)) if (goal or org) else s["orgs"]
        if (goal or org) and n == 0:
            continue
        items.append({**s, "n": n, "match": school_matches(s, rows, goal, org, group, n)})
    items.sort(key=lambda s: (-s["n"], -s["orgs"], s["short"]))
    with st.container(border=True):
        st.subheader("Partner organizations per school")
        st.caption("Bar length is organizations; the label also gives program rows. Organizations that listed the school without enrollment numbers still count.")
        if not items:
            st.write("No school matches this combination of filters.")
            return
        limit = 15
        shown = items if st.session_state.show_all or len(items) <= limit else items[:limit]
        fig = go.Figure(go.Bar(
            x=[s["n"] for s in shown], y=[s["short"] for s in shown], orientation="h",
            marker=dict(color=[ACCENT if s["match"] else MUTED for s in shown],
                        line=dict(color=["#0b0b0b" if s["school"] == school else "rgba(0,0,0,0)" for s in shown], width=2)),
            text=[(f"{s['n']} of {s['orgs']}" if (goal or org) else f"{s['orgs']} org{'s' if s['orgs'] != 1 else ''}") + f" · {s['programs']} program{'s' if s['programs'] != 1 else ''}" for s in shown],
            textposition="outside", cliponaxis=False,
            customdata=[s["school"] for s in shown],
            hovertext=[f"<b>{s['school']}</b><br>{s['orgs']} organizations, {s['orgs_with_numbers']} with numbers · {s['programs']} program rows<br>{s['org_list']}" for s in shown],
            hoverinfo="text",
        ))
        fig.update_layout(height=max(220, 26 * len(shown) + 40), margin=dict(l=0, r=90, t=0, b=0),
                          xaxis=dict(range=[0, 4.6], tickvals=[0, 1, 2, 3, 4], showgrid=True, gridcolor="#e1e0d9", zeroline=False),
                          yaxis=dict(autorange="reversed", tickfont=dict(size=12)), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        event = st.plotly_chart(fig, width="stretch", on_select="rerun", selection_mode="points", key="ranking")
        try:
            pts = event.selection.points if event and event.selection else []
        except AttributeError:
            pts = []
        if pts:
            picked = pts[0].get("customdata")
            if isinstance(picked, list):
                picked = picked[0]
            if picked and picked != st.session_state.school:
                st.session_state.school = picked
                st.rerun()
        if len(items) > limit:
            st.toggle(f"Show all {len(items)} schools", key="show_all")


def render_none_list(L: D.Landscape):
    none = [s for s in L.coverage if s["orgs"] == 0]
    none.sort(key=lambda s: (D.SETTING_ORDER.index(s["setting"]) if s["setting"] in D.SETTING_ORDER else 9, -(s["school_enrollment"] or 0)))
    with st.container(border=True):
        st.subheader("District high schools with no partner listed")
        st.caption("Ranked by total enrollment in the city's school directory, so the largest unlisted student bodies come first. "
                   "Neighborhood high schools are the clearest openings.")
        df = pd.DataFrame([{"Setting": s["setting"] or "Other settings", "School": s["short"], "Full name": s["school"],
                            "Grades": s["grade_org"] or "", "Students": s["school_enrollment"]} for s in none])
        st.dataframe(df, hide_index=True, width="stretch",
                     column_config={"Students": st.column_config.ProgressColumn("Students", format="%d", min_value=0,
                                                                                  max_value=int(df["Students"].max() or 1))})
        st.caption("\"No partner listed\" means none of the organizations in this collection named the school. Six programs listed no "
                   "schools, so some of these may be served. If yours is, add it to your submission. Charter high schools are not included.")


def render_sharing(L: D.Landscape):
    org = st.session_state.org
    with st.container(border=True):
        st.subheader("Who shares schools")
        if not org:
            st.caption("Pairs of organizations that listed the same schools, most shared first. Choose your organization in the sidebar "
                       "to see your own schools and who else is at each.")
            df = pd.DataFrame([{"Organizations": f"{D.org_label(p['org_a'])} + {D.org_label(p['org_b'])}", "Schools shared": p["schools"],
                                "Both with numbers": p["with_numbers_both"], "Schools": "; ".join(p["school_list"])} for p in L.org_pairs[:10]])
            st.dataframe(df, hide_index=True, width="stretch")
        else:
            st.caption(f"Each school {D.org_label(org)} listed, with the other organizations there. Schools where you are the only one listed come last.")
            rows = [r for r in L.org_shared if r["organization"] == org]
            if not rows:
                st.write("This organization listed no schools.")
                return
            df = pd.DataFrame([{"School": r["school"], "Other organizations there": "; ".join(D.org_label(o) for o in r["others_list"]) or "only you",
                                "Your students": r["own_students"] if r["own_students"] is not None else "no numbers"} for r in rows])
            st.dataframe(df, hide_index=True, width="stretch")


def render_goals(L: D.Landscape):
    st.header("What partners are working toward")
    st.markdown("Each program picked the district CCR goal areas it contributes to. Crowded areas are where coordination matters most; "
                "thin ones may be a gap, or simply outside what partners do. The solid part of each bar is programs that also listed schools.")
    left, right = st.columns([1, 1])
    goal = st.session_state.goal
    total = max(1, L.overview["programs"])
    with left, st.container(border=True):
        st.subheader("Programs per goal area")
        gc = L.goal_coverage
        fig = go.Figure()
        fig.add_trace(go.Bar(name="listed schools", y=[g["goal"] for g in gc], x=[g["with_schools"] for g in gc], orientation="h",
                             marker_color=[ACCENT if (not goal or goal == g["goal"]) else MUTED for g in gc],
                             hovertext=[f"<b>{g['goal']}</b><br>{g['programs']} programs from {g['organizations']} organizations · {g['with_schools']} listed schools · {g['schools_reached']} schools reached<br>{g['names']}" for g in gc], hoverinfo="text"))
        fig.add_trace(go.Bar(name="ticked, no schools listed", y=[g["goal"] for g in gc], x=[g["programs"] - g["with_schools"] for g in gc], orientation="h",
                             marker_color=MUTED, opacity=0.6, hoverinfo="skip",
                             text=[f"{g['programs']} of {total} · {g['with_schools']} with schools" for g in gc], textposition="outside", cliponaxis=False))
        fig.update_layout(barmode="stack", height=260, margin=dict(l=0, r=120, t=0, b=0), legend=dict(orientation="h", y=-0.2),
                          xaxis=dict(range=[0, total + 1], showgrid=True, gridcolor="#e1e0d9", zeroline=False),
                          yaxis=dict(autorange="reversed"), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, width="stretch")
    with right, st.container(border=True):
        st.subheader("Goal areas by program")
        key = next((k for k, lab in D.GOALS if lab == goal), None)
        org = st.session_state.org
        rows = sorted(L.programs, key=lambda p: (p["Organization"], p["Program"]))
        short = {"9th graders on track": "9th on track", "4-year graduation rate": "4-yr grad", "Algebra, Biology & Literature": "Alg/Bio/Lit",
                 "CTE coursework": "CTE", "College-ready coursework": "College-ready", "FAFSA completion": "FAFSA", "College enrollment": "College enroll."}
        table = []
        for p in rows:
            dim = (key and p.get(key) is not True) or (org and p["Organization"] != org)
            row = {"Program": p["Program"], "Organization": D.org_label(p["Organization"])}
            for k, lab in D.GOALS:
                row[short[lab]] = ("○" if dim else "●") if p.get(k) is True else ""
            row["Other"] = p.get("Other (write-in)") or ""
            table.append(row)
        totals = {"Program": "Programs per goal area", "Organization": ""}
        for g in L.goal_coverage:
            totals[short[g["goal"]]] = str(g["programs"])
        totals["Other"] = ""
        table.append(totals)
        st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch", height=min(760, 36 * len(table) + 40))
        st.caption("● selected the goal area; ○ selected it but is outside the current filter. Two organizations run a Talent Search and an Upward Bound.")


def render_grades(L: D.Landscape):
    st.header("Which grades programs reach")
    o = L.overview
    st.markdown(f"Programs reported **{fmt(o['seats'])}** enrollments across **{o['programs_with_seats']}** programs. These are seats, not unique "
                "students, and whole-school models dominate the total; compare the grade mix, not the lengths.")
    goal, org = st.session_state.goal, st.session_state.org
    data = [r for r in L.program_grades if not goal or goal in r["goals"]]
    with st.container(border=True):
        st.subheader("Enrollment by grade, per program")
        if not data:
            st.write("No program selected this goal area.")
            return
        labels = [f"{r['program']} · {D.org_label(r['organization'])}" + (" ◌" if r["round"] else "") for r in data]
        fig = go.Figure()
        alphas = [0.5, 0.67, 0.84, 1.0]
        for i, (g, name) in enumerate(zip(D.GRADES, ["9th", "10th", "11th", "12th"])):
            fig.add_trace(go.Bar(name=f"{name} grade", y=labels, x=[r[g] for r in data], orientation="h",
                                 marker=dict(color=[ACCENT if not org or r["organization"] == org else MUTED for r in data], opacity=alphas[i]),
                                 hovertext=[f"<b>{r['program']}</b><br>{D.org_label(r['organization'])} · {r['schools']} schools" + (f" ({r['schools_reported']} with numbers)" if r['schools_reported'] < r['schools'] else "") + f"<br>{name}: {fmt(r[g])} · total {fmt(r['total'])}" + (" · round numbers" if r['round'] else "") for r in data], hoverinfo="text"))
        fig.update_layout(barmode="stack", height=max(260, 26 * len(data) + 60), margin=dict(l=0, r=20, t=0, b=0), legend=dict(orientation="h", y=-0.12),
                          xaxis=dict(showgrid=True, gridcolor="#e1e0d9", zeroline=False), yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
                          plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, width="stretch")
        st.caption("◌ every reported row for this program is round numbers, likely planned cohorts. Programs with no enrollment numbers show no bar.")


def render_complete(L: D.Landscape):
    st.header("Help complete the picture")
    st.markdown("A program with no schools listed cannot appear in the overlap view, and a program with schools but no numbers counts as present "
                "but reaches nobody in the totals. If yours is here, adding schools and enrollment to your submission updates this page.")
    org = st.session_state.org
    df = pd.DataFrame([{"Program": r["program"], "Organization": D.org_label(r["organization"]), "Schools listed": r["schools"],
                        "With numbers": r["schools_reported"], "What is missing": r["note"], "Yours": "yes" if org and r["organization"] == org else ""}
                       for r in L.data_gaps])
    if not org:
        df = df.drop(columns=["Yours"])
    st.dataframe(df, hide_index=True, width="stretch")


def render_notes(L: D.Landscape):
    with st.expander("How to read this page, and what was compiled"):
        st.markdown("""
- **Goal areas** are the seven district College and Career Readiness (CCR) goal areas each program selected on its submission form. "Other" is the program's own write-in.
- **Organizations, not programs,** are the unit for overlap. LULAC runs three TRIO programs and Philadelphia Academies five, so a school with six program rows may have four organizations in the building.
- **The school universe** is every district-run school serving grades 9 to 12 in the City of Philadelphia's public Schools dataset, except the Re-Engagement Center and special settings such as the juvenile justice and student transition centers. Charter schools are excluded because the goal areas are district accountability measures. Two rows were repaired: a duplicate Olney entry and an implausible enrollment figure for The LINC. The dataset's vintage may differ from this year's submissions.
- **Numbers update** from the compiled Google Sheet every ten minutes while the app is open, or on demand from the sidebar.
- **Philadelphia Academies, Inc.** rows arrive shifted one column to the left because the comma in the organization's name was read as a column break during compilation. The app repairs those rows and recovers each school from its ULCS code.
- **Blank cells** stay blank. A zero is a reported zero.
""")
        st.markdown("**Issues found while compiling the submissions**")
        st.dataframe(pd.DataFrame([{"Source file": r.get("Source file", "").replace("CCR Data Collection - ", ""), "Tab": r.get("Tab", ""),
                                    "What is wrong": r.get("What's wrong", "")} for r in L.issues]), hide_index=True, width="stretch")


# ---------------------------------------------------------------- main

def main():
    init_state()
    L, loaded_at = get_landscape()
    render_sidebar(L)
    render_header(L, loaded_at)
    active_filter_line()
    render_overlap(L)
    render_goals(L)
    render_grades(L)
    render_complete(L)
    render_notes(L)


main()
