"""Scheduling-interleaving fuzz (V3 7.12.7, 7.14.5; TEST-FUZZ-003): concurrent programs
whose observable result is schedule-independent by construction are run under many
seeded random schedules; every run must produce the FIFO result and never an
interpreter-level failure."""
import pytest

from tests.helpers import run

PROGRAMS = {
    "worker_pool_exactly_once": """
async fn worker(jobs: ReceivePort[Int], out: SendPort[Int]) throws ChannelClosed {
    for await j in jobs { try await out.send(j * j) }
}
async fn main() throws ChannelClosed, AggregateException {
    let jobs = Channel[Int].buffered(3)
    let res = Channel[Int].unbounded()
    let tx = jobs.sender()
    parallel {
        for _ in 0..4 { spawn worker(jobs.receiver(), res.sender()) }
        for i in 0..30 { try await tx.send(i) }
        jobs.close()
    }
    res.close()
    let seen = MutableList[Int]()
    for await v in res.receiver() { seen.push(v) }
    print(seen.length, seen.freeze().sorted() == (0..30).toList().map(fn(i) => i * i))
}""",
    "select_multiplexer": """
async fn produce(tx: SendPort[Int], base: Int) throws ChannelClosed {
    for i in 0..10 { try await tx.send(base + i) }
}
async fn main() throws ChannelClosed, AggregateException {
    let a = Channel[Int].rendezvous()
    let b = Channel[Int].buffered(2)
    let ra = a.receiver()
    let rb = b.receiver()
    let total = parallel {
        spawn produce(a.sender(), 0)
        spawn produce(b.sender(), 100)
        let sum = 0
        let n = 0
        while n < 20 {
            select {
                receive x from ra => { sum = sum + x }
                receive y from rb => { sum = sum + y }
            }
            n = n + 1
        }
        sum
    }
    print(total)
}""",
    "failfast_aggregate_contents": """
error Bad { n: Int }
async fn job(n: Int) -> Int throws Bad {
    if n == 3 { throw Bad(n: n) }
    await sleep(5.millis)
    return n
}
async fn main() {
    let r = try parallel { for i in 0..6 { spawn job(i) }
        0 } catch AggregateException as a => a.entries.length
    print(r)
}""",
    "collect_report_shape": """
error Bad { }
async fn job(n: Int) -> Int throws Bad {
    await sleep((n % 3).millis)
    if n % 2 == 0 { throw Bad() }
    return n
}
async fn main() {
    let rep = parallel collect { for i in 0..8 { spawn job(i) } }
    let ok = rep.outcomes.filter(fn(o) => o is TaskOutcome.Succeeded).length
    print(ok, rep.outcomes.length)
}""",
    "ping_pong_rendezvous": """
async fn ponger(rx: ReceivePort[Int], tx: SendPort[Int]) throws ChannelClosed {
    for await v in rx { try await tx.send(v + 1) }
}
async fn main() throws ChannelClosed, AggregateException {
    let ping = Channel[Int].rendezvous()
    let pong = Channel[Int].rendezvous()
    let tx = ping.sender()
    let rx = pong.receiver()
    let last = parallel {
        spawn ponger(ping.receiver(), pong.sender())
        let v = 0
        for _ in 0..25 { try await tx.send(v)
            v = try await rx.receive() }
        ping.close()
        v
    }
    print(last)
}""",
    "race_single_possible_winner": """
error Nope { }
async fn fails(ms: Int) -> Int throws Nope { await sleep(ms.millis)
    throw Nope() }
async fn wins() -> Int { await sleep(3.millis)
    return 42 }
async fn main() {
    let v = parallel firstSuccess { spawn fails(1)
        spawn wins()
        spawn fails(2) }
    print(v)
}""",
}

SEEDS = range(1, 21)


@pytest.mark.parametrize("name", sorted(PROGRAMS))
def test_schedule_independent_result(name):
    src = PROGRAMS[name]
    base = run(src)
    assert base.exit_code == 0, base.text()
    for seed in SEEDS:
        r = run(src, schedule="random", seed=seed)
        assert not [c for c in r.codes if c.startswith("H.")], (seed, r.text())
        assert (r.exit_code, r.lines) == (base.exit_code, base.lines), (name, seed, r.lines, base.lines)
