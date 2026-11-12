"""Checks the data layer against CSV snapshots of the sheet. Run: python tests/test_data.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ccr_data as D  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def test_headline_figures():
    L = D.load_from_files(FIXTURES)
    o = L.overview
    assert (o["programs"], o["organizations"]) == (20, 11)
    assert o["district_schools"] == 61 and o["schools_partnered"] == 45
    assert (o["schools_multi"], o["schools_one"], o["schools_none"], o["schools_3plus"]) == (27, 18, 16, 7)
    assert o["students_none"] == 4865 and o["programs_no_school"] == 6
    assert o["seats"] == 7992


def test_academies_repair():
    L = D.load_from_files(FIXTURES)
    rows = [r for r in L.enrollment if r["organization"] == "Philadelphia Academies, Inc."]
    assert len(rows) == 9 and all(r["school"] for r in rows)
    ece = next(r for r in rows if r["program"].startswith("ECE"))
    assert (ece["school"], ece["ulcs"], ece["g9"], ece["g10"], ece["g11"], ece["g12"], ece["total"]) == ("Parkway West High School", "5090", 0, 36, 21, 7, 64)


def test_goal_counts():
    L = D.load_from_files(FIXTURES)
    assert [g["programs"] for g in L.goal_coverage] == [8, 12, 3, 6, 13, 8, 18]
    assert [g["with_schools"] for g in L.goal_coverage] == [6, 10, 1, 4, 10, 7, 14]


def test_round_flag():
    L = D.load_from_files(FIXTURES)
    assert sum(1 for r in L.enrollment if r["round"]) == 18
    assert {r["program"] for r in L.program_grades if r["round"]} == {"Heights", "Talent Search"}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
