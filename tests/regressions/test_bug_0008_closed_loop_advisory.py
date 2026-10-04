"""BUG-0008: W.SELECT.CLOSED_LOOP ("closed branch inside a loop neither exits nor
changes eligibility") was reported when the closed branch communicates the loop exit
through the select's *value* or by assigning state (e.g. `let done = select { ...
closed rx => true }` followed by `if done { break }`), a correct and common shape.
The advisory must only fire when the branch's outcome cannot influence the loop."""
from tests.helpers import check

VALUE_EXIT = """
async fn drain(rx: ReceivePort[Int]) -> Int {
    let total = 0
    while true {
        let done = select { receive x from rx => { total = total + x
          false }
         closed rx => true }
        if done { break }
    }
    return total
}"""

FLAG_EXIT = """
async fn drain(rx: ReceivePort[Int]) -> Int {
    let open = true
    let total = 0
    while open {
        select { receive x from rx => { total = total + x }
         closed rx => { open = false } }
    }
    return total
}"""

GENUINE = """
async fn drain(rx: ReceivePort[Int]) {
    for i in 0..10 {
        select { receive x from rx => print(x)
         closed rx => print("closed") }
    }
}"""


def test_value_exit_is_not_flagged():
    assert "W.SELECT.CLOSED_LOOP" not in check(VALUE_EXIT, "verified").check_codes


def test_state_change_is_not_flagged():
    assert "W.SELECT.CLOSED_LOOP" not in check(FLAG_EXIT, "verified").check_codes


def test_genuine_spin_is_still_flagged():
    assert "W.SELECT.CLOSED_LOOP" in check(GENUINE, "verified").check_codes
