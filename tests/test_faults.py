"""Modul 02 & 03: generator berlabel, korelator yang buta label, dan akurasi yang dikunci terhadap regresi."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from oss import correlate as C, faults as F, inventory as I  # noqa: E402

NET = ("transport_cut", "power_outage", "link_flapping", "concurrent_cut")


@pytest.fixture(scope="module")
def inv():
    return I.build()


@pytest.fixture(scope="module")
def clean(inv):
    d = F.generate(inv)
    return d, C.correlate(d["alarms"], inv)


@pytest.fixture(scope="module")
def hard(inv):
    d = F.generate(inv, hard=True)
    return d, C.correlate(d["alarms"], inv)


def acc(ev, types):
    v = [ev["per_type"][t] for t in types if t in ev["per_type"]]
    return sum(x["correct"] for x in v) / sum(x["scenarios"] for x in v)


def test_catalog_marks_name_origin():
    for vendor in ("ZTE", "EID"):
        assert all(src in ("public", "generic") for *_, src in F.CATALOG[vendor].values())
        assert all(sev in ("Critical", "Major", "Minor", "Warning") for _, sev, _, _ in F.CATALOG[vendor].values())


def test_generator_is_deterministic_and_labelled(inv, clean):
    d, _ = clean
    again = F.generate(inv)
    assert [a["alarm_id"] for a in again["alarms"]] == [a["alarm_id"] for a in d["alarms"]]
    roots = {a["scenario_id"] for a in d["alarms"] if a["is_root"]}
    assert roots == {s["scenario_id"] for s in d["scenarios"]}                 # setiap skenario punya alarm akar


def test_correlator_ignores_labels(inv, clean):
    d, res = clean
    scrambled = [{**a, "scenario_id": "X", "scenario_type": "X", "is_root": False} for a in d["alarms"]]
    again = C.correlate(scrambled, inv)
    assert [(i["root_type"], i["root_object"], i["alarm_count"]) for i in again["incidents"]] == \
           [(i["root_type"], i["root_object"], i["alarm_count"]) for i in res["incidents"]]


def test_clean_data_is_solved(clean):
    d, res = clean
    ev = C.evaluate(d["alarms"], d["scenarios"], res["incidents"])
    assert acc(ev, NET) == 1.0
    assert ev["per_type"]["link_flapping"]["split"] == 0                       # flapping = satu insiden


def test_hard_data_accuracy_floor(hard):
    """Angka yang dilaporkan di README; test ini mencegah penurunan diam-diam."""
    d, res = hard
    ev = C.evaluate(d["alarms"], d["scenarios"], res["incidents"])
    assert acc(ev, ["transport_cut"]) >= 0.95
    assert acc(ev, ["power_outage"]) >= 0.90
    assert acc(ev, ["concurrent_cut"]) >= 0.65                                 # batas yang diketahui, lihat README
    assert acc(ev, NET) >= 0.88
    assert ev["incidents"] < ev["alarms"] / 8                                  # kompresi alarm -> insiden


def test_relay_power_outage_is_power_not_link(inv):
    d = F.generate(inv, mix={"power_outage": 40}, seed=7)
    res = C.correlate(d["alarms"], inv)
    ev = C.evaluate(d["alarms"], d["scenarios"], res["incidents"])
    assert ev["per_type"]["power_outage"]["correct"] == 40
    relay = [i for i in res["incidents"] if i["root_type"] == "power" and i["sites_affected"] > 1]
    assert relay                                                               # padam di relay memutus site di belakangnya


def test_lost_outage_alarm_does_not_split_incident(inv):
    """Regresi: bila alarm 'NE tak terjangkau' di site relay hilang, bukti RAN/sel tetap menyambung rantainya."""
    d = F.generate(inv, mix={"transport_cut": 30}, seed=11)
    full = C.evaluate(d["alarms"], d["scenarios"], C.correlate(d["alarms"], inv)["incidents"])
    lost = [a for a in d["alarms"] if not (a["symptom"] == "ne_down" and int(a["alarm_id"][3:]) % 5 == 0)]
    ev = C.evaluate(lost, d["scenarios"], C.correlate(lost, inv)["incidents"])
    # 20% alarm 'NE tak terjangkau' hilang tidak boleh menurunkan akurasi dibanding data lengkap. (Pada biji ini satu
    # skenario memang salah sejak data lengkap: dua gangguan acak tumpang tindih di subtree yang sama.)
    assert ev["per_type"]["transport_cut"]["correct"] == full["per_type"]["transport_cut"]["correct"] >= 29
