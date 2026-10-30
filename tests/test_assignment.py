import pytest

from domain.assignment import (
    AssignmentService,
    LoadBasedStrategy,
    RoundRobinStrategy,
    SkillBasedStrategy,
)
from domain.enums import Status
from domain.exceptions import (
    InvalidStateTransitionError,
    NoEligibleTechnicianError,
    ValidationError,
)
from domain.incident import Incident
from domain.users import Technician


def tech(uid, skills=("network",), exp=1, cap=5):
    return Technician(uid, uid, set(skills), exp, cap)


def busy(t, n=1):
    for _ in range(n):
        t.take_incident()
    return t


# ---------- skill-based ----------
def test_skill_picks_only_skilled_technicians():
    a = tech("A", {"database"})
    b = tech("B", {"network"})
    assert SkillBasedStrategy().select([a, b], "network") is b


def test_skill_prefers_more_experience():
    a = tech("A", exp=2)
    b = tech("B", exp=7)
    assert SkillBasedStrategy().select([a, b], "network") is b


def test_skill_tie_goes_to_lighter_load_then_id():
    a = busy(tech("A", exp=3))
    b = tech("B", exp=3)
    c = tech("C", exp=3)
    assert SkillBasedStrategy().select([a, b, c], "network") is b


def test_skill_requires_a_skill_name():
    with pytest.raises(ValidationError):
        SkillBasedStrategy().select([tech("A")], None)


def test_skill_nobody_has_it():
    with pytest.raises(NoEligibleTechnicianError):
        SkillBasedStrategy().select([tech("A", {"database"})], "network")


def test_skill_skips_full_technicians():
    full = busy(tech("A", cap=1))
    ok = tech("B")
    assert SkillBasedStrategy().select([full, ok], "network") is ok


def test_skill_skips_unavailable_technicians():
    away = tech("A")
    away.set_available(False)
    ok = tech("B")
    assert SkillBasedStrategy().select([away, ok], "network") is ok


# ---------- load-based ----------
def test_load_picks_least_busy():
    a = busy(tech("A"), 3)
    b = busy(tech("B"), 1)
    assert LoadBasedStrategy().select([a, b]) is b


def test_load_tie_goes_to_experience():
    a = tech("A", exp=2)
    b = tech("B", exp=6)
    assert LoadBasedStrategy().select([a, b]) is b


def test_load_full_tie_goes_to_lowest_id():
    assert LoadBasedStrategy().select([tech("B"), tech("A")]).user_id == "A"


def test_load_empty_list_raises():
    with pytest.raises(NoEligibleTechnicianError):
        LoadBasedStrategy().select([])


# ---------- round robin ----------
def test_round_robin_takes_turns():
    techs = [tech("A"), tech("B"), tech("C")]
    rr = RoundRobinStrategy()
    assert [rr.select(techs).user_id for _ in range(4)] == ["A", "B", "C", "A"]


def test_round_robin_skips_full_technicians():
    a, b, c = tech("A"), busy(tech("B", cap=1)), tech("C")
    rr = RoundRobinStrategy()
    assert [rr.select([a, b, c]).user_id for _ in range(3)] == ["A", "C", "A"]


def test_round_robin_state_can_be_saved_and_restored():
    techs = [tech("A"), tech("B"), tech("C")]
    first = RoundRobinStrategy()
    first.select(techs)
    saved = first.get_state()
    second = RoundRobinStrategy()
    second.set_state(saved)
    assert second.select(techs).user_id == "B"


def test_round_robin_survives_a_changing_list():
    rr = RoundRobinStrategy()
    rr.set_state("B")
    # B has left, so it carries on with the next id after B
    assert rr.select([tech("A"), tech("C"), tech("D")]).user_id == "C"


# ---------- service ----------
def test_service_assigns_and_charges_the_technician():
    inc = Incident("INC1", "Payment app down")
    t = tech("A")
    result = AssignmentService(SkillBasedStrategy()).assign(inc, [t], "network")
    assert result is t
    assert inc.status == Status.ASSIGNED
    assert inc.technician is t
    assert t.active_count == 1


def test_service_falls_back_to_load_based():
    inc = Incident("INC1", "Payment app down")
    a = busy(tech("A", {"database"}), 2)
    b = tech("B", {"database"})
    result = AssignmentService(SkillBasedStrategy()).assign(inc, [a, b], "network")
    assert result is b


def test_service_raises_when_nobody_can_take_it():
    inc = Incident("INC1", "Payment app down")
    full = busy(tech("A", cap=1))
    with pytest.raises(NoEligibleTechnicianError):
        AssignmentService(SkillBasedStrategy()).assign(inc, [full], "network")
    assert inc.status == Status.NEW


def test_service_strategy_can_be_swapped_at_runtime():
    service = AssignmentService(SkillBasedStrategy())
    service.set_strategy(LoadBasedStrategy())
    inc = Incident("INC1", "Payment app down")
    a = busy(tech("A"), 2)
    b = tech("B")
    assert service.assign(inc, [a, b]) is b


def test_service_does_not_charge_when_the_incident_cannot_be_assigned():
    inc = Incident("INC1", "Payment app down")
    inc.assign()
    t = tech("A")
    with pytest.raises(InvalidStateTransitionError):
        AssignmentService(LoadBasedStrategy()).assign(inc, [t])
    assert t.active_count == 0