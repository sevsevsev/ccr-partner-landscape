"""Data layer for the SY26-27 CCR Partner Landscape.

Reads the compiled Google Sheet (link-shared) through its public CSV endpoint,
repairs known defects, and derives every number the app shows. Pure Python so it
can be tested without the app; the app wraps `load_all` in a Streamlit cache.
"""
from __future__ import annotations

import csv
import io
import json
import re
import urllib.parse
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

SHEET_ID = "1q7qPxJAIGQBtGbj31_jmAAo5Gb1ULTJzUYticiylM90"
TABS = {
    "programs": "Programs",
    "enrollment": "Enrollment by School and Grade",
    "issues": "Issues",
}
DATA_DIR = Path(__file__).parent / "data"

GOALS = [
    ("9th graders on track to graduate in four years", "9th graders on track"),
    ("Four-year high school graduation rate", "4-year graduation rate"),
    ("Algebra, Biology, and Literature performance and growth", "Algebra, Biology & Literature"),
    ("Career and technical education (CTE) coursework and industry standards", "CTE coursework"),
    ("College-ready coursework participation and performance", "College-ready coursework"),
    ("FAFSA completion rate", "FAFSA completion"),
    ("College enrollment", "College enrollment"),
]
GOAL_LABELS = [label for _, label in GOALS]
GRADES = ["g9", "g10", "g11", "g12"]
SETTING_ORDER = ["Neighborhood", "Citywide, special admission & CTE", "EOP, alternative & accelerated"]


def org_label(name: str) -> str:
    return "LULAC (LNESC)" if name == "LULAC National Educational Service Centers Inc." else name


# ---------------------------------------------------------------- fetching

def csv_url(sheet_id: str, tab: str) -> str:
    return (f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?"
            + urllib.parse.urlencode({"tqx": "out:csv", "sheet": tab}))


def fetch_tab(tab: str, sheet_id: str = SHEET_ID, timeout: int = 30) -> list[dict]:
    """One tab of the sheet as a list of row dicts keyed by header. Cells are text."""
    req = urllib.request.Request(csv_url(sheet_id, tab), headers={"User-Agent": "ccr-partner-landscape"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8-sig")
    return parse_csv(text)


def parse_csv(text: str) -> list[dict]:
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return []
    header = rows[0]
    out = []
    for r in rows[1:]:
        if all(c.strip() == "" for c in r):
            continue
        row = {}
        for i, h in enumerate(header):
            if h == "":
                continue
            row[h] = r[i] if i < len(r) else ""
        out.append(row)
    return out


def typed(v):
    """TRUE/FALSE to bool, numeric text to numbers, blank to None."""
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    if s.upper() == "TRUE":
        return True
    if s.upper() == "FALSE":
        return False
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d+\.\d+", s):
        return float(s)
    return s


# ---------------------------------------------------------------- repairs

def programs_rows(raw: list[dict]) -> list[dict]:
    out = []
    for r in raw:
        row = {k: typed(v) for k, v in r.items()}
        for key, _ in GOALS:
            row[key] = row.get(key) is True
        out.append(row)
    return out


def enrollment_rows(raw: list[dict], name_by_ulcs: dict[str, str] | None = None) -> list[dict]:
    """Enrollment tab with the Philadelphia Academies column shift repaired and numbers typed.

    The public CSV endpoint types each column, so a school name sitting in the numeric
    "ULCS Code" column of a shifted row comes back blank; it is recovered from the code.
    """
    name_by_ulcs = name_by_ulcs or {}
    grades = ["9th Grade Enrollment", "10th Grade Enrollment", "11th Grade Enrollment", "12th Grade Enrollment"]
    out = []
    for r in raw:
        o = dict(r)
        if r.get("Organization") == "Philadelphia Academies" and r.get("Program") == "Inc.":
            # The comma in the organization's name was read as a column break, shifting every value one column left.
            o = {
                "Organization": "Philadelphia Academies, Inc.",
                "Program": r.get("School", ""),
                "School": r.get("ULCS Code", ""),
                "ULCS Code": r.get("9th Grade Enrollment", ""),
                "9th Grade Enrollment": r.get("10th Grade Enrollment", ""),
                "10th Grade Enrollment": r.get("11th Grade Enrollment", ""),
                "11th Grade Enrollment": r.get("12th Grade Enrollment", ""),
                "12th Grade Enrollment": r.get("Total Enrollment", ""),
                "Total Enrollment": "",
                "Source file": r.get("Source file", ""),
            }
        g = [typed(o.get(k)) for k in grades]
        g = [int(x) if isinstance(x, (int, float)) else None for x in g]
        total = typed(o.get("Total Enrollment"))
        total = int(total) if isinstance(total, (int, float)) else None
        any_grade = any(x is not None for x in g)
        if total is None and any_grade:
            total = sum(x or 0 for x in g)
        code = typed(o.get("ULCS Code"))
        ulcs = str(int(code)) if isinstance(code, (int, float)) else None
        school = (o.get("School") or "").strip()
        if not school and ulcs and ulcs in name_by_ulcs:
            school = name_by_ulcs[ulcs]
        nonzero = [x for x in g if x]
        out.append({
            "organization": o.get("Organization", ""), "program": o.get("Program", ""), "school": school,
            "ulcs": ulcs, "g9": g[0], "g10": g[1], "g11": g[2], "g12": g[3], "total": total,
            "reported": total is not None or any_grade,
            # Counts that are all multiples of 5 usually mean a planned cohort size rather than a roster.
            "round": len(nonzero) >= 2 and all(x % 5 == 0 for x in nonzero),
            "source": o.get("Source file", ""),
        })
    return out


# ---------------------------------------------------------------- derived views

def _key(r):
    return r["organization"] + " | " + r["program"]


def _pkey(p):
    return p["Organization"] + " | " + p["Program"]


def goals_of(programs: list[dict]) -> dict[str, list[str]]:
    return {_pkey(p): [label for key, label in GOALS if p.get(key) is True] for p in programs}


def school_orgs(enrollment: list[dict], programs: list[dict]) -> list[dict]:
    """One row per school any program listed, with organization-level counts."""
    gmap = goals_of(programs)
    by: dict[str, dict] = OrderedDict()
    for r in enrollment:
        s = by.setdefault(r["school"], {"school": r["school"], "ulcs": r["ulcs"], "orgs": OrderedDict(), "programs": 0,
                                        "goals": set(), "g9": False, "g10": False, "g11": False, "g12": False})
        o = s["orgs"].setdefault(r["organization"], {"programs": 0, "with_numbers": 0})
        o["programs"] += 1
        if r["reported"]:
            o["with_numbers"] += 1
        s["programs"] += 1
        s["goals"].update(gmap.get(_key(r), []))
        for k in GRADES:
            if r[k]:
                s[k] = True
    rows = []
    for s in by.values():
        rows.append({
            "school": s["school"], "ulcs": s["ulcs"], "orgs": len(s["orgs"]),
            "orgs_with_numbers": sum(1 for o in s["orgs"].values() if o["with_numbers"] > 0),
            "programs": s["programs"],
            "org_list": "; ".join(
                name + (f" ({o['programs']} programs)" if o["programs"] > 1 else "") + (" (no numbers)" if o["with_numbers"] == 0 else "")
                for name, o in s["orgs"].items()),
            "org_names": list(s["orgs"].keys()),
            "goal_areas": len(s["goals"]),
            **{k: s[k] for k in GRADES},
        })
    rows.sort(key=lambda s: (-s["orgs"], -s["orgs_with_numbers"], -s["programs"], s["school"]))
    return rows


def load_district_schools() -> list[dict]:
    return json.loads((DATA_DIR / "district_schools.json").read_text(encoding="utf-8"))


def load_boundary() -> dict:
    return json.loads((DATA_DIR / "philly_boundary.json").read_text(encoding="utf-8"))


def school_coverage(district: list[dict], sorgs: list[dict]) -> list[dict]:
    """Every district high school joined to the partner data by ULCS code."""
    by_code = {s["ulcs"]: s for s in sorgs if s["ulcs"]}
    seen = set()
    rows = []
    for d in district:
        s = by_code.get(d["ulcs"])
        if s:
            seen.add(d["ulcs"])
        orgs = s["orgs"] if s else 0
        rows.append({
            "ulcs": d["ulcs"], "school": s["school"] if s else d["name"], "short": d["short"], "setting": d.get("setting"),
            "grade_org": d.get("grade_org"), "school_enrollment": d.get("school_enrollment"), "lat": d["lat"], "lon": d["lon"],
            "virtual": bool(d.get("virtual")), "orgs": orgs, "orgs_with_numbers": s["orgs_with_numbers"] if s else 0,
            "programs": s["programs"] if s else 0, "group": "none" if orgs == 0 else "one" if orgs == 1 else "multi",
            "org_list": s["org_list"] if s else "", "org_names": s["org_names"] if s else [],
        })
    for s in sorgs:
        if not s["ulcs"] or s["ulcs"] not in seen:
            rows.append({"ulcs": s["ulcs"], "school": s["school"], "short": s["school"], "setting": None, "grade_org": None,
                         "school_enrollment": None, "lat": None, "lon": None, "virtual": False, "orgs": s["orgs"],
                         "orgs_with_numbers": s["orgs_with_numbers"], "programs": s["programs"],
                         "group": "one" if s["orgs"] == 1 else "multi", "org_list": s["org_list"], "org_names": s["org_names"]})
    rows.sort(key=lambda r: (-r["orgs"], -(r["school_enrollment"] or 0), r["short"]))
    return rows


def overview(programs, enrollment, coverage) -> dict:
    with_school = {_key(r) for r in enrollment}
    none = [s for s in coverage if s["group"] == "none"]
    return {
        "programs": len(programs),
        "organizations": len({p["Organization"] for p in programs}),
        "district_schools": sum(1 for s in coverage if s["lat"] is not None),
        "schools_partnered": sum(1 for s in coverage if s["orgs"] > 0),
        "schools_multi": sum(1 for s in coverage if s["group"] == "multi"),
        "schools_3plus": sum(1 for s in coverage if s["orgs"] >= 3),
        "schools_one": sum(1 for s in coverage if s["group"] == "one"),
        "schools_none": len(none),
        "students_none": sum(s["school_enrollment"] or 0 for s in none),
        "programs_no_school": sum(1 for p in programs if _pkey(p) not in with_school),
        "seats": sum(r["total"] or 0 for r in enrollment),
        "programs_with_seats": len({_key(r) for r in enrollment if (r["total"] or 0) > 0}),
    }


def goal_coverage(programs, enrollment) -> list[dict]:
    with_school = {_key(r) for r in enrollment}
    out = []
    for key, label in GOALS:
        hits = [p for p in programs if p.get(key) is True]
        keys = {_pkey(p) for p in hits}
        out.append({
            "goal": label, "programs": len(hits),
            "with_schools": sum(1 for p in hits if _pkey(p) in with_school),
            "organizations": len({p["Organization"] for p in hits}),
            "schools_reached": len({r["school"] for r in enrollment if _key(r) in keys}),
            "names": "; ".join(p["Organization"] + " – " + p["Program"] for p in hits),
        })
    return out


def school_programs(enrollment, programs) -> list[dict]:
    gmap = goals_of(programs)
    return [{"school": r["school"], "ulcs": r["ulcs"], "organization": r["organization"], "program": r["program"],
             "total": r["total"], "reported": r["reported"], "round": r["round"], "goals": gmap.get(_key(r), [])}
            for r in enrollment]


def school_goals(sprog, gcov) -> dict[str, dict]:
    """Per school: goal areas with an organization there, and those without (ignoring goals almost nobody with schools covers)."""
    viable = {g["goal"] for g in gcov if g["with_schools"] >= 2}
    by: dict[str, set] = {}
    for r in sprog:
        by.setdefault(r["school"], set()).update(r["goals"])
    return {school: {"covered": [g for g in GOAL_LABELS if g in cov],
                     "not_covered": [g for g in GOAL_LABELS if g in viable and g not in cov]}
            for school, cov in by.items()}


def org_pairs(sprog) -> list[dict]:
    by_school: dict[str, dict[str, bool]] = {}
    for r in sprog:
        s = by_school.setdefault(r["school"], {})
        s[r["organization"]] = s.get(r["organization"], False) or (r["total"] or 0) > 0
    pairs: dict[tuple, dict] = {}
    for school, orgs in by_school.items():
        for a, b in combinations(sorted(orgs), 2):
            p = pairs.setdefault((a, b), {"org_a": a, "org_b": b, "schools": 0, "with_numbers_both": 0, "school_list": []})
            p["schools"] += 1
            p["school_list"].append(school)
            if orgs[a] and orgs[b]:
                p["with_numbers_both"] += 1
    out = [{**p, "pair": p["org_a"] + " + " + p["org_b"], "school_list": sorted(p["school_list"])} for p in pairs.values()]
    out.sort(key=lambda p: (-p["schools"], -p["with_numbers_both"], p["pair"]))
    return out


def org_shared(sprog) -> list[dict]:
    by_school: dict[str, dict[str, dict]] = {}
    for r in sprog:
        s = by_school.setdefault(r["school"], {})
        o = s.setdefault(r["organization"], {"programs": 0, "students": 0, "reported": False})
        o["programs"] += 1
        o["students"] += r["total"] or 0
        o["reported"] = o["reported"] or r["reported"]
    rows = []
    for school, orgs in by_school.items():
        for org, o in orgs.items():
            others = sorted(x for x in orgs if x != org)
            rows.append({"organization": org, "school": school, "own_programs": o["programs"],
                         "own_students": o["students"] if o["reported"] else None, "others": len(others), "others_list": others})
    rows.sort(key=lambda r: (r["organization"], -r["others"], r["school"]))
    return rows


def program_grades(enrollment, programs) -> list[dict]:
    out = []
    for p in programs:
        rows = [r for r in enrollment if r["organization"] == p["Organization"] and r["program"] == p["Program"]]
        reported = [r for r in rows if r["reported"]]
        out.append({
            "organization": p["Organization"], "program": p["Program"], "schools": len(rows), "schools_reported": len(reported),
            "round": bool(reported) and all(r["round"] for r in reported),
            **{k: sum(r[k] or 0 for r in rows) for k in GRADES},
            "total": sum(r["total"] or 0 for r in rows),
            "goals": [label for key, label in GOALS if p.get(key) is True],
        })
    out.sort(key=lambda r: -r["total"])
    return out


def data_gaps(programs, enrollment) -> list[dict]:
    out = []
    for p in programs:
        rows = [r for r in enrollment if r["organization"] == p["Organization"] and r["program"] == p["Program"]]
        reported = sum(1 for r in rows if r["reported"])
        goals = sum(1 for key, _ in GOALS if p.get(key) is True)
        note, severity = "", 9
        if not rows:
            note, severity = "No schools listed", 1
        elif reported == 0:
            note, severity = "Schools listed, no enrollment numbers", 2
        elif reported < len(rows):
            note, severity = f"Enrollment missing for {len(rows) - reported} of {len(rows)} schools", 3
        if goals == 0:
            note = (note + "; " if note else "") + "No goal areas selected"
            severity = min(severity, 1)
        if note:
            out.append({"organization": p["Organization"], "program": p["Program"], "schools": len(rows),
                        "schools_reported": reported, "goal_areas": goals, "note": note, "severity": severity})
    out.sort(key=lambda r: (r["severity"], r["organization"]))
    return out


@dataclass
class Landscape:
    programs: list[dict]
    enrollment: list[dict]
    issues: list[dict]
    district: list[dict]
    boundary: dict
    school_orgs: list[dict] = field(default_factory=list)
    coverage: list[dict] = field(default_factory=list)
    overview: dict = field(default_factory=dict)
    goal_coverage: list[dict] = field(default_factory=list)
    school_programs: list[dict] = field(default_factory=list)
    school_goals: dict = field(default_factory=dict)
    org_pairs: list[dict] = field(default_factory=list)
    org_shared: list[dict] = field(default_factory=list)
    program_grades: list[dict] = field(default_factory=list)
    data_gaps: list[dict] = field(default_factory=list)

    @property
    def organizations(self) -> list[str]:
        return sorted({p["Organization"] for p in self.programs})


def build(programs_raw, enrollment_raw, issues_raw, district=None, boundary=None) -> Landscape:
    programs = programs_rows(programs_raw)
    district = district if district is not None else load_district_schools()
    enrollment = enrollment_rows(enrollment_raw, {d["ulcs"]: d["name"] for d in district if d.get("ulcs")})
    issues = [dict(r) for r in issues_raw]
    boundary = boundary if boundary is not None else load_boundary()
    L = Landscape(programs, enrollment, issues, district, boundary)
    L.school_orgs = school_orgs(enrollment, programs)
    L.coverage = school_coverage(district, L.school_orgs)
    L.overview = overview(programs, enrollment, L.coverage)
    L.goal_coverage = goal_coverage(programs, enrollment)
    L.school_programs = school_programs(enrollment, programs)
    L.school_goals = school_goals(L.school_programs, L.goal_coverage)
    L.org_pairs = org_pairs(L.school_programs)
    L.org_shared = org_shared(L.school_programs)
    L.program_grades = program_grades(enrollment, programs)
    L.data_gaps = data_gaps(programs, enrollment)
    return L


def load_all(sheet_id: str = SHEET_ID) -> Landscape:
    """Fetch the three tabs from the live sheet and derive everything."""
    return build(fetch_tab(TABS["programs"], sheet_id), fetch_tab(TABS["enrollment"], sheet_id), fetch_tab(TABS["issues"], sheet_id))


def load_from_files(folder: Path) -> Landscape:
    """Build from CSV files saved from the sheet (same tab names), for offline use and tests."""
    rd = lambda name: parse_csv((folder / f"{name}.csv").read_text(encoding="utf-8-sig"))
    return build(rd(TABS["programs"]), rd(TABS["enrollment"]), rd(TABS["issues"]))
