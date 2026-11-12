"""SY26-27 CCR Partner Landscape, a Streamlit app fed by the shared Google Sheet."""
from __future__ import annotations

import datetime as dt
import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import ccr_data as D

ACCENT = "#2a78d6"
MUTED = "#c3c2b7"
HOLLOW_STROKE = "#898781"
GRID = "#e1e0d9"
SIZE_PX = {0: 9, 1: 11, 2: 16, 3: 22, 4: 28}
GROUP_LABELS = {"multi": "Two or more partner organizations", "one": "One partner organization", "none": "No partner listed"}
GRADE_NAMES = {"g9": "9th", "g10": "10th", "g11": "11th", "g12": "12th"}
SHORT_GOAL = {"9th graders on track": "9th on track", "4-year graduation rate": "4-yr graduation", "Algebra, Biology & Literature": "Alg/Bio/Lit",
              "CTE coursework": "CTE courses", "College-ready coursework": "College-ready courses", "FAFSA completion": "FAFSA",
              "College enrollment": "College enrollment"}
TTL_SECONDS = 600
MAP_ZOOM = 10.75
NUDGE_PX = 20  # how far apart two schools in the same building are drawn

st.set_page_config(page_title="SY26-27 CCR Partner Landscape", page_icon="🏫", layout="wide", initial_sidebar_state="collapsed")


# ---------------------------------------------------------------- data

@st.cache_data(ttl=TTL_SECONDS, show_spinner="Reading the Google Sheet…")
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
        st.error(f"Could not read the Google Sheet. Check that it is shared with \"Anyone with the link\", then click Refresh data now. (Technical details: {exc})")
        st.stop()
    return D.build(p, e, i), at


# ---------------------------------------------------------------- state and helpers

def init_state():
    for k, v in {"org": "", "goal": "", "school": "", "group": "", "show_all": False}.items():
        st.session_state.setdefault(k, v)


def fmt(n) -> str:
    return "" if n is None else f"{n:,}"


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def orgs_at(rows: list[dict], goal: str, org: str) -> set[str]:
    return {r["organization"] for r in rows if (not goal or goal in r["goals"]) and (not org or r["organization"] == org)}


def school_matches(s: dict, rows: list[dict], goal: str, org: str, group: str, n: int) -> bool:
    return (not group or s["group"] == group) and (not org or any(r["organization"] == org for r in rows)) and (not goal or n > 0)


def rows_by_school(L: D.Landscape) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in L.school_programs:
        out.setdefault(r["school"], []).append(r)
    return out


def selected_point(event) -> str | None:
    """The school name carried by a clicked Plotly point, if any."""
    try:
        pts = event.selection.points if event and event.selection else []
    except AttributeError:
        pts = event.get("selection", {}).get("points", []) if isinstance(event, dict) else []
    if not pts:
        return None
    picked = pts[0].get("customdata")
    return picked[0] if isinstance(picked, list) else picked


def pick_school(name: str | None):
    if name and name != st.session_state.school:
        st.session_state.school = name
        st.rerun()


def chart_layout(fig: go.Figure, **kw):
    fig.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", hoverlabel=dict(bgcolor="white", font_size=12), **kw)
    return fig


# ---------------------------------------------------------------- header and filters

def render_header(L: D.Landscape, loaded_at: str):
    o = L.overview
    st.title("SY26-27 CCR Partner Landscape")
    st.markdown(
        f"{o['programs']} programs from {o['organizations']} organizations listed the schools where they work in the 2026-27 school year "
        f"(SY26-27) and the district College and Career Readiness (CCR) goal areas they work on. {o['schools_3plus']} schools have three "
        "or more partner organizations. Use this page to see where organizations overlap, which district high schools have no partner "
        "listed, and who you could coordinate with."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Schools with two or more partner organizations", o["schools_multi"])
    c2.metric("Schools with one partner organization", o["schools_one"])
    c3.metric("District high schools with no partner listed", o["schools_none"], f"{fmt(o['students_none'])} students in those schools", delta_color="off")
    c4.metric("Programs that listed no schools", o["programs_no_school"], "not on the map or in the school lists", delta_color="off")


def render_filters(L: D.Landscape, loaded_at: str):
    with st.container(border=True):
        c1, c2, c3, c4, c5 = st.columns([1.2, 1.2, 1.2, 1.2, 0.9])
        c1.selectbox("Your organization", [""] + L.organizations, format_func=lambda v: "All organizations" if v == "" else D.org_label(v), key="org")
        c2.selectbox("Goal area", [""] + D.GOAL_LABELS, format_func=lambda v: "All goal areas" if v == "" else v, key="goal")
        schools = sorted(L.coverage, key=lambda s: s["short"])
        names = [""] + [s["school"] for s in schools]
        labels = {s["school"]: s["short"] + (" (no partner listed)" if s["orgs"] == 0 else "") for s in schools}
        idx = names.index(st.session_state.school) if st.session_state.school in names else 0
        picked = c3.selectbox("School", names, index=idx, format_func=lambda v: "All schools" if v == "" else labels.get(v, v))
        if picked != st.session_state.school:
            st.session_state.school = picked
            st.rerun()
        c4.selectbox("Show schools with", [""] + list(GROUP_LABELS), format_func=lambda v: "Any number of partners" if v == "" else GROUP_LABELS[v], key="group")
        with c5:
            st.write("")
            b1, b2 = st.columns(2)
            if b1.button("Reset", width="stretch"):
                for k in ("org", "goal", "school", "group"):
                    st.session_state[k] = ""
                st.rerun()
            if b2.button("Refresh data", width="stretch", help="Read the Google Sheet again now"):
                fetch_raw.clear()
                st.rerun()
        parts = []
        if st.session_state.org:
            parts.append(D.org_label(st.session_state.org))
        if st.session_state.goal:
            parts.append(st.session_state.goal)
        if st.session_state.school:
            parts.append(st.session_state.school)
        if st.session_state.group:
            parts.append("schools with " + GROUP_LABELS[st.session_state.group].lower())
        tail = f"Numbers come from the shared Google Sheet, last read {loaded_at}; they refresh every {TTL_SECONDS // 60} minutes or when you click Refresh data now."
        st.caption(("Filtered to: " + "; ".join(parts) + ". " if parts else "") + tail)


# ---------------------------------------------------------------- map

def nudge_apart(pts: list[dict]):
    """Spread circles that would overlap at the initial zoom, so each one can be hovered and clicked.

    Schools in the same building (a high school and its Educational Options program) share a point, and the
    Kensington schools sit a few hundred meters apart. Positions are relaxed in pixel space at MAP_ZOOM, with
    bigger circles moving less, and a hairline from each moved circle points back to its true location.
    """
    scale = 512 / (2 * math.pi) * (2 ** MAP_ZOOM)  # 512-pixel tiles, as the map library uses

    def to_px(lat, lon):
        x = scale * (math.radians(lon) + math.pi)
        y = scale * (math.pi - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))
        return x, y

    def to_geo(x, y):
        lon = math.degrees(x / scale - math.pi)
        lat = math.degrees(2 * math.atan(math.exp(math.pi - y / scale)) - math.pi / 2)
        return lat, lon

    for p in pts:
        p["_x"], p["_y"] = to_px(p["lat"], p["lon"])
        p["_x0"], p["_y0"] = p["_x"], p["_y"]
    for _ in range(80):
        moved = False
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                a, b = pts[i], pts[j]
                dx, dy = b["_x"] - a["_x"], b["_y"] - a["_y"]
                d = math.hypot(dx, dy)
                want = a["size"] / 2 + b["size"] / 2 + NUDGE_PX / 4
                if d >= want:
                    continue
                if d < 1e-6:
                    dx, dy, d = 1.0, 0.4, math.hypot(1.0, 0.4)
                push = (want - d) / d
                wa = b["size"] / (a["size"] + b["size"])  # the smaller circle moves more
                a["_x"] -= dx * push * wa
                a["_y"] -= dy * push * wa
                b["_x"] += dx * push * (1 - wa)
                b["_y"] += dy * push * (1 - wa)
                moved = True
        if not moved:
            break
    for p in pts:
        if math.hypot(p["_x"] - p["_x0"], p["_y"] - p["_y0"]) > p["size"] / 2:
            p["lat0"], p["lon0"] = p["lat"], p["lon"]
        p["lat"], p["lon"] = to_geo(p["_x"], p["_y"])


def build_map(L: D.Landscape) -> go.Figure:
    goal, org, group, school = st.session_state.goal, st.session_state.org, st.session_state.group, st.session_state.school
    by_school = rows_by_school(L)
    pts = []
    for s in L.coverage:
        if s["lat"] is None or s["virtual"]:
            continue
        rows = by_school.get(s["school"], [])
        n = len(orgs_at(rows, goal, org)) if (goal or org) else s["orgs"]
        match = school_matches(s, rows, goal, org, group, n)
        hollow = s["orgs"] == 0
        if hollow:
            hover = f"<b>{s['school']}</b><br>No partner listed · {fmt(s['school_enrollment'])} students (city school list) · grades {s['grade_org'] or ''}" + (f"<br>{s['setting']}" if s['setting'] else "")
        else:
            shown_orgs = sorted({D.org_label(r['organization']) for r in rows if not goal or goal in r['goals']})
            count = f"{n} of {s['orgs']}" if (goal or org) else str(s["orgs"])
            matching = " match your filters" if (goal or org) else ""
            hover = f"<b>{s['school']}</b><br>{count} organization{'s' if s['orgs'] != 1 else ''}{matching} · {plural(s['programs'], 'program')}" \
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
    nudge_apart(pts)
    df = pd.DataFrame(pts)
    ring = L.boundary["geometry"]["coordinates"][0]
    fig = go.Figure()
    fig.add_trace(go.Scattermap(lon=[p[0] for p in ring], lat=[p[1] for p in ring], mode="lines",
                                line=dict(color=HOLLOW_STROKE, width=1), hoverinfo="skip", showlegend=False))
    for p in pts:  # hairlines from a nudged circle back to the real building
        if "lat0" in p:
            fig.add_trace(go.Scattermap(lon=[p["lon0"], p["lon"]], lat=[p["lat0"], p["lat"]], mode="lines",
                                        line=dict(color=HOLLOW_STROKE, width=1), hoverinfo="skip", showlegend=False))
    # Outline ring under the fill, so hollow and selected rings read in every theme.
    fig.add_trace(go.Scattermap(lon=df["lon"], lat=df["lat"], mode="markers",
                                marker=dict(size=df["size"] + 3, color=df["line_color"], opacity=1, sizemode="diameter"),
                                hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scattermap(
        lon=df["lon"], lat=df["lat"], mode="markers+text", text=df["label"], textposition="middle right",
        textfont=dict(size=11, color="#52514e"),
        marker=dict(size=df["size"], color=df["color"], opacity=df["opacity"], sizemode="diameter"),
        customdata=df["school"], hovertext=df["hover"], hoverinfo="text", showlegend=False, name="schools",
    ))
    fig.update_layout(map=dict(style="carto-positron", center=dict(lat=40.02, lon=-75.13), zoom=MAP_ZOOM),
                      margin=dict(l=0, r=0, t=0, b=0), height=640, hoverlabel=dict(bgcolor="white", font_size=12))
    return fig


# ---------------------------------------------------------------- overlap section

def render_overlap(L: D.Landscape):
    st.header("Where partners overlap, and where no partner is listed")
    st.markdown("Each circle is a district high school, and bigger circles have more partner organizations. Click a school on the map "
                "or in the bar chart, or choose one in the School filter, to see who is there.")
    pick_school(selected_point(st.plotly_chart(build_map(L), width="stretch", on_select="rerun", selection_mode="points", key="map")))
    st.caption("Circle size shows 1, 2, 3, or 4 or more organizations. Blue circles have at least one partner. White circles have no "
               "partner listed in this year's submissions. Gray circles do not match the current filters. Schools that share a building, "
               "such as a high school and its Educational Options program, are drawn a short distance apart with a line back to the "
               "building. Philadelphia Virtual Academy has no building, so it is not on the map.")
    render_school_detail(L)
    left, right = st.columns(2)
    with left:
        render_org_ranking(L)
    with right:
        render_none_list(L)
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
            st.caption("Showing the school with the most partner organizations. Choose another on the map, in the bar chart, or in the School filter.")
        if not cov:
            st.write("No record for this school.")
            return
        bits = []
        if cov["orgs"] > 0:
            bits.append(f"{plural(cov['orgs'], 'organization')} · {plural(cov['programs'], 'program')}")
        if cov["school_enrollment"] is not None:
            bits.append(f"{fmt(cov['school_enrollment'])} students (city school list)")
        if cov["grade_org"]:
            bits.append(f"grades {cov['grade_org']}")
        st.caption(" · ".join(bits))
        if cov["orgs"] == 0:
            st.info(f"No partner program listed this school for 2026-27. {L.overview['programs_no_school']} programs did not list any schools, so one of them may still be here.")
            return
        facts, table_col = st.columns([1, 2])
        with facts:
            so = next((s for s in L.school_orgs if s["school"] == school), None)
            if so:
                have = [GRADE_NAMES[g] for g in D.GRADES if so[g]]
                missing = [GRADE_NAMES[g] for g in D.GRADES if not so[g]]
                line = "Grades where a partner reported students: " + (", ".join(have) if have else "none")
                if have and missing:
                    line += ". None reported for " + ", ".join(missing)
                st.markdown(line + ".")
            sg = L.school_goals.get(school, {"covered": [], "not_covered": []})
            st.markdown("Goal areas a partner here selected: " + ("; ".join(sg["covered"]) or "none") + ".")
            st.markdown("Goal areas no partner here selected: " + ("; ".join(sg["not_covered"]) or "none") + ".")
        with table_col:
            goal_key = next((k for k, lab in D.GOALS if lab == st.session_state.goal), None)
            targets = {D._pkey(p) for p in L.programs if not goal_key or p.get(goal_key) is True}
            rows = [r for r in L.enrollment if r["school"] == school]
            org_order = sorted({r["organization"] for r in rows}, key=lambda o: (o != st.session_state.org, o))
            table = []
            for o in org_order:
                for r in rows:
                    if r["organization"] != o:
                        continue
                    tot = "No numbers given" if not r["reported"] else fmt(r["total"]) + (" *" if r["round"] else "")
                    table.append({"Organization": D.org_label(o), "Program": r["program"],
                                  "9th": fmt(r["g9"]), "10th": fmt(r["g10"]), "11th": fmt(r["g11"]), "12th": fmt(r["g12"]), "Total": tot,
                                  "Selected this goal area": "Yes" if (goal_key and D._key(r) in targets) else ("No" if goal_key else "")})
            df = pd.DataFrame(table)
            if not goal_key:
                df = df.drop(columns=["Selected this goal area"])
            narrow = {c: st.column_config.Column(c, width="small") for c in ("9th", "10th", "11th", "12th", "Total")}
            st.dataframe(df, hide_index=True, width="stretch", column_config=narrow)
            st.caption("A blank cell means the program left it empty, or its form had no box for that grade. An asterisk marks a program whose "
                       "counts are all multiples of 5 (10, 25, 50 and so on), which usually means a planned group size rather than a count "
                       "of actual students.")


def render_org_ranking(L: D.Landscape):
    goal, org, group, school = st.session_state.goal, st.session_state.org, st.session_state.group, st.session_state.school
    by_school = rows_by_school(L)
    items = []
    for s in L.coverage:
        if s["orgs"] == 0:
            continue
        rows = by_school.get(s["school"], [])
        n = len(orgs_at(rows, goal, org)) if (goal or org) else s["orgs"]
        if (goal or org) and n == 0:
            continue
        items.append({**s, "n": n, "match": school_matches(s, rows, goal, org, group, n)})
    items.sort(key=lambda s: (-s["n"], -s["orgs"], s["short"]))
    with st.container(border=True):
        st.subheader("Partner organizations at each school")
        st.caption("Each bar counts the organizations at a school; the label beside it also gives the number of programs. An organization "
                   "that listed the school but gave no enrollment numbers still counts.")
        if not items:
            st.write("No school matches these filters.")
            return
        limit = 15
        shown = items if st.session_state.show_all or len(items) <= limit else items[:limit]
        fig = go.Figure(go.Bar(
            x=[s["n"] for s in shown], y=[s["short"] for s in shown], orientation="h",
            marker=dict(color=[ACCENT if s["match"] else MUTED for s in shown],
                        line=dict(color=["#0b0b0b" if s["school"] == school else "rgba(0,0,0,0)" for s in shown], width=2)),
            text=[(f"{s['n']} of {s['orgs']} match" if (goal or org) else plural(s["orgs"], "organization")) + f" · {plural(s['programs'], 'program')}" for s in shown],
            textposition="outside", cliponaxis=False,
            customdata=[s["school"] for s in shown],
            hovertext=[f"<b>{s['school']}</b><br>{s['orgs']} organizations ({s['orgs_with_numbers']} gave enrollment numbers) · {plural(s['programs'], 'program')}<br>{s['org_list']}" for s in shown],
            hoverinfo="text",
        ))
        chart_layout(fig, height=max(220, 26 * len(shown) + 40), margin=dict(l=0, r=180, t=0, b=0),
                     xaxis=dict(range=[0, 4.6], tickvals=[0, 1, 2, 3, 4], showgrid=True, gridcolor=GRID, zeroline=False),
                     yaxis=dict(autorange="reversed", tickfont=dict(size=12)))
        pick_school(selected_point(st.plotly_chart(fig, width="stretch", on_select="rerun", selection_mode="points", key="ranking")))
        if len(items) > limit:
            st.toggle(f"Show all {len(items)} schools", key="show_all")


def render_none_list(L: D.Landscape):
    none = [s for s in L.coverage if s["orgs"] == 0]
    none.sort(key=lambda s: (D.SETTING_ORDER.index(s["setting"]) if s["setting"] in D.SETTING_ORDER else 9, -(s["school_enrollment"] or 0)))
    with st.container(border=True):
        st.subheader("District high schools with no partner listed")
        st.caption("Grouped by school type, then by enrollment from the city school list, largest first. Neighborhood high schools "
                   "are the clearest openings. CTE is career and technical education; EOP is the district's Educational Options Program.")
        df = pd.DataFrame([{"School type": s["setting"] or "Not categorized", "School": s["school"],
                            "Grades": s["grade_org"] or "", "Students": s["school_enrollment"]} for s in none])
        st.dataframe(df, hide_index=True, width="stretch", height=min(620, 36 * len(df) + 40),
                     column_config={"Students": st.column_config.ProgressColumn("Students", format="%d", min_value=0,
                                                                                  max_value=int(df["Students"].max() or 1)),
                                    "Grades": st.column_config.Column("Grades", width="small"),
                                    "School type": st.column_config.Column("School type", width="medium")})
        st.caption(f"\"No partner listed\" means no program in this year's submissions named the school. {L.overview['programs_no_school']} "
                   "programs did not list any schools, so some of these schools may have a partner after all. If one of them is yours, add it "
                   "to your submission. Charter high schools are not included.")


def render_sharing(L: D.Landscape):
    with st.container(border=True):
        st.subheader("Who shares schools")
        pairs_tab, mine_tab = st.tabs(["Organizations that share schools", "Your organization's schools"])
        with pairs_tab:
            st.caption("The ten pairs of organizations that share the most schools. Open a pair to see which schools.")
            df = pd.DataFrame([{"Organizations": f"{D.org_label(p['org_a'])} + {D.org_label(p['org_b'])}", "Shared schools": p["schools"],
                                "Shared schools where both gave numbers": p["with_numbers_both"]} for p in L.org_pairs[:10]])
            st.dataframe(df, hide_index=True, width="stretch",
                         column_config={"Shared schools": st.column_config.Column("Shared schools", width="small"),
                                        "Shared schools where both gave numbers": st.column_config.Column("Shared schools where both gave numbers", width="medium")})
            with st.expander("Which schools each pair shares"):
                for p in L.org_pairs[:10]:
                    st.markdown(f"**{D.org_label(p['org_a'])} + {D.org_label(p['org_b'])}**: " + "; ".join(p["school_list"]))
        with mine_tab:
            orgs = L.organizations
            default = orgs.index(st.session_state.org) if st.session_state.org in orgs else 0
            org = st.selectbox("Organization", orgs, index=default, format_func=D.org_label, key="share_org")
            st.caption(f"Each school {D.org_label(org)} listed, with the other organizations there. Schools where it is the only organization listed come last.")
            rows = [r for r in L.org_shared if r["organization"] == org]
            if not rows:
                st.write("This organization listed no schools.")
            else:
                df = pd.DataFrame([{"School": r["school"], "Other organizations there": "; ".join(D.org_label(o) for o in r["others_list"]) or "Only this one",
                                    "Its enrollment": r["own_students"] if r["own_students"] is not None else "No numbers given"} for r in rows])
                st.dataframe(df, hide_index=True, width="stretch", height=min(480, 36 * len(df) + 40),
                             column_config={"Its enrollment": st.column_config.Column("Its enrollment", width="small")})


# ---------------------------------------------------------------- goal areas

def goal_grid(L: D.Landscape) -> go.Figure:
    goal, org = st.session_state.goal, st.session_state.org
    rows = sorted(L.programs, key=lambda p: (p["Organization"], p["Program"]))
    counts = {g["goal"]: g["programs"] for g in L.goal_coverage}
    x = [f"{SHORT_GOAL[lab]}<br><span style='color:#898781'>{counts.get(lab, 0)} programs</span>" for _, lab in D.GOALS]
    y = [f"{p['Program']} · {D.org_label(p['Organization'])}" for p in rows]
    z, hover = [], []
    for p in rows:
        zr, hr = [], []
        row_dim = bool(org and p["Organization"] != org)
        for key, lab in D.GOALS:
            on = p.get(key) is True
            dim = row_dim or bool(goal and goal != lab)
            zr.append((0.45 if dim else 1.0) if on else 0.0)
            other = p.get("Other (write-in)") or ""
            hr.append(f"<b>{p['Program']}</b><br>{D.org_label(p['Organization'])}<br>{lab}: {'selected' if on else 'not selected'}"
                      + (f"<br>Other: {other}" if other else ""))
        z.append(zr)
        hover.append(hr)
    fig = go.Figure(go.Heatmap(z=z, x=x, y=y, zmin=0, zmax=1, showscale=False, xgap=4, ygap=4,
                               colorscale=[[0, "#f4f3ef"], [0.45, MUTED], [1, ACCENT]],
                               hovertext=hover, hoverinfo="text"))
    chart_layout(fig, height=26 * len(rows) + 80, margin=dict(l=0, r=0, t=70, b=0),
                 xaxis=dict(side="top", tickfont=dict(size=11), fixedrange=True),
                 yaxis=dict(autorange="reversed", tickfont=dict(size=11), fixedrange=True))
    return fig


def render_goals(L: D.Landscape):
    st.header("Which goal areas programs selected")
    st.markdown("On its form, each program selected the district College and Career Readiness (CCR) goal areas it works on. A goal area with "
                "many programs is where coordination matters most; one with few may be a gap, or something partners do not do. CTE is career "
                "and technical education; FAFSA is the Free Application for Federal Student Aid.")
    goal = st.session_state.goal
    total = max(1, L.overview["programs"])
    with st.container(border=True):
        st.subheader("Programs per goal area")
        gc = L.goal_coverage
        fig = go.Figure()
        fig.add_trace(go.Bar(name="Listed schools", y=[g["goal"] for g in gc], x=[g["with_schools"] for g in gc], orientation="h",
                             marker_color=[ACCENT if (not goal or goal == g["goal"]) else MUTED for g in gc],
                             hovertext=[f"<b>{g['goal']}</b><br>{g['programs']} programs from {g['organizations']} organizations · {g['with_schools']} of them listed schools · {g['schools_reached']} different schools in total<br>{g['names']}" for g in gc], hoverinfo="text"))
        fig.add_trace(go.Bar(name="Selected the goal, but listed no schools", y=[g["goal"] for g in gc], x=[g["programs"] - g["with_schools"] for g in gc], orientation="h",
                             marker_color=MUTED, opacity=0.6, hoverinfo="skip",
                             text=[f"{g['programs']} of {total} programs · {g['with_schools']} listed schools" for g in gc], textposition="outside", cliponaxis=False))
        chart_layout(fig, barmode="stack", height=300, margin=dict(l=0, r=200, t=0, b=0), legend=dict(orientation="h", y=-0.18),
                     xaxis=dict(range=[0, total + 1], showgrid=True, gridcolor=GRID, zeroline=False), yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, width="stretch")
        st.caption("The solid part of each bar is programs that also listed schools; the faded part is programs that selected the goal area but listed no schools.")
    with st.container(border=True):
        st.subheader("Which goal areas each program selected")
        grid_tab, table_tab = st.tabs(["Grid", "Table"])
        with grid_tab:
            st.plotly_chart(goal_grid(L), width="stretch", config={"displayModeBar": False})
            st.caption("A blue cell means the program selected that goal area; a gray cell means it did, but the program is outside the current "
                       "filters. Hover a cell for the full goal area name and the program's write-in. Talent Search and Upward Bound each appear "
                       "twice because two organizations run one of each.")
        with table_tab:
            key = next((k for k, lab in D.GOALS if lab == goal), None)
            org = st.session_state.org
            table = []
            for p in sorted(L.programs, key=lambda p: (p["Organization"], p["Program"])):
                dim = (key and p.get(key) is not True) or (org and p["Organization"] != org)
                row = {"Organization": D.org_label(p["Organization"]), "Program": p["Program"]}
                for k, lab in D.GOALS:
                    row[SHORT_GOAL[lab]] = ("(✓)" if dim else "✓") if p.get(k) is True else ""
                row["Other (in their own words)"] = p.get("Other (write-in)") or ""
                table.append(row)
            totals = {"Organization": "", "Program": "Total programs"}
            for g in L.goal_coverage:
                totals[SHORT_GOAL[g["goal"]]] = str(g["programs"])
            totals["Other (in their own words)"] = ""
            table.append(totals)
            full = {SHORT_GOAL[lab]: key for key, lab in D.GOALS}
            st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch", height=min(760, 36 * len(table) + 40),
                         column_config={s: st.column_config.Column(s, help=full[s], width="small") for s in full})
            st.caption("✓ = selected this goal area. (✓) = selected it, but outside the current filters. Hover a column header for the full goal area name.")


# ---------------------------------------------------------------- grades and gaps

def render_grades(L: D.Landscape):
    st.header("Which grades programs reach")
    o = L.overview
    st.markdown(f"Programs reported {fmt(o['seats'])} student enrollments across {o['programs_with_seats']} programs. A student in two programs "
                "is counted twice, and programs that serve a whole school make up most of the total, so compare the mix of grades within each "
                "bar rather than how long the bars are.")
    goal, org = st.session_state.goal, st.session_state.org
    data = [r for r in L.program_grades if not goal or goal in r["goals"]]
    with st.container(border=True):
        st.subheader("Enrollment by grade, for each program")
        if not data:
            st.write("No program selected this goal area.")
            return
        labels = [f"{r['program']} · {D.org_label(r['organization'])}" + (" *" if r["round"] else "") for r in data]
        fig = go.Figure()
        alphas = [0.5, 0.67, 0.84, 1.0]
        for i, (g, name) in enumerate(zip(D.GRADES, ["9th", "10th", "11th", "12th"])):
            fig.add_trace(go.Bar(name=f"{name} grade", y=labels, x=[r[g] for r in data], orientation="h",
                                 marker=dict(color=[ACCENT if not org or r["organization"] == org else MUTED for r in data], opacity=alphas[i]),
                                 hovertext=[f"<b>{r['program']}</b><br>{D.org_label(r['organization'])} · {plural(r['schools'], 'school')}" + (f" ({r['schools_reported']} gave enrollment numbers)" if r['schools_reported'] < r['schools'] else "") + f"<br>{name}: {fmt(r[g])} · total {fmt(r['total'])}" + (" · all counts are multiples of 5" if r['round'] else "") for r in data], hoverinfo="text"))
        chart_layout(fig, barmode="stack", height=max(260, 26 * len(data) + 60), margin=dict(l=0, r=20, t=0, b=0), legend=dict(orientation="h", y=-0.12),
                     xaxis=dict(showgrid=True, gridcolor=GRID, zeroline=False), yaxis=dict(autorange="reversed", tickfont=dict(size=11)))
        st.plotly_chart(fig, width="stretch")
        st.caption("An asterisk marks a program whose every count is a multiple of 5, which usually means planned group sizes rather than actual students. Programs that gave no enrollment numbers have no bar.")


def render_complete(L: D.Landscape):
    st.header("Programs with schools or numbers missing")
    st.markdown("A program that listed no schools is not on the map or in any school's count. A program that listed schools but gave no "
                "enrollment numbers shows up at those schools but adds nothing to the student totals. If your program is in this table, add "
                "the missing schools or numbers to your submission and this page will pick them up.")
    org = st.session_state.org
    df = pd.DataFrame([{"Organization": D.org_label(r["organization"]), "Program": r["program"], "Schools listed": r["schools"],
                        "Schools with enrollment numbers": r["schools_reported"], "What is missing": r["note"],
                        "Your program": "Yes" if org and r["organization"] == org else ""}
                       for r in L.data_gaps])
    if not org:
        df = df.drop(columns=["Your program"])
    st.dataframe(df, hide_index=True, width="stretch",
                 column_config={"Schools listed": st.column_config.Column("Schools listed", width="small"),
                                "Schools with enrollment numbers": st.column_config.Column("Schools with enrollment numbers", width="medium")})


def render_notes(L: D.Landscape):
    with st.expander("Definitions and data notes"):
        st.markdown("""
- Goal areas are the seven district College and Career Readiness (CCR) goal areas each program selected on its form. "Other" is whatever the program wrote in itself.
- Overlap counts organizations, not programs. LULAC (LNESC) runs three federal TRIO programs and Philadelphia Academies, Inc. runs five programs, so a school with six programs may have only four organizations in the building.
- The school list is every district-run school with grades 9 to 12 in the City of Philadelphia's public list of schools, except the Re-Engagement Center and special settings such as the juvenile justice and student transition centers. Charter schools are left out because the goal areas are district accountability measures. Two entries in the city list were corrected: a duplicate Olney entry and an enrollment figure for The LINC that could not be right. The city list may be from a different year than this year's submissions.
- Partner data comes from the SY26-27 CCR Program Data Google Sheet (tabs: Programs; Enrollment by School and Grade; Issues). School names, student counts and map locations come from the City of Philadelphia's public list of schools, matched to the sheet by each school's district ID number (ULCS code).
- Philadelphia Academies, Inc. rows in the shared sheet are shifted one column to the left, because the comma in the organization's name was read as a column break when the submissions were combined. This page shifts them back and fills in each school's name from its district ID number (ULCS code).
- A blank cell means nothing was entered. A zero means the program entered 0.
""")
        st.markdown("#### Problems found while combining the submissions")
        st.dataframe(pd.DataFrame([{"Source file": r.get("Source file", "").replace("CCR Data Collection - ", ""), "Tab": r.get("Tab", ""),
                                    "What is wrong": r.get("What's wrong", "")} for r in L.issues]), hide_index=True, width="stretch")


# ---------------------------------------------------------------- main

def main():
    init_state()
    L, loaded_at = get_landscape()
    render_header(L, loaded_at)
    render_filters(L, loaded_at)
    render_overlap(L)
    render_goals(L)
    render_grades(L)
    render_complete(L)
    render_notes(L)


main()
