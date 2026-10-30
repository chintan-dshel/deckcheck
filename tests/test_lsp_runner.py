from pathlib import Path

from deckcheck.lsp.runner import Runner


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _runner(durations=None, models=None):
    clock, ran, published = Clock(), [], []

    def check(main):
        ran.append(main)
        clock.t += (durations or {}).get(main.name, 0.01)
        return f"report {main.name} #{len(ran)}"

    r = Runner(models=models or (lambda f: [f]), check=check,
               publish=lambda main, rep, err: published.append((main.name, rep, err)),
               threshold=2.0, clock=clock)
    return r, clock, ran, published


def test_open_checks_at_once():
    r, _, ran, pub = _runner()
    r.request(Path("a.k"), "open")
    assert r.step() and pub == [("a.k", "report a.k #1", None)]


def test_change_on_a_small_model_waits_for_the_pause():
    r, clock, ran, pub = _runner()
    r.request(Path("a.k"), "open")
    r.step()
    r.request(Path("a.k"), "change")
    assert not r.step()          # 300 ms debounce not over
    clock.t += 0.31
    assert r.step() and len(pub) == 2


def test_change_on_a_big_model_waits_for_save():
    r, clock, ran, pub = _runner(durations={"big.k": 63.0})
    r.request(Path("big.k"), "open")
    r.step()
    assert not r.live(Path("big.k"))
    r.request(Path("big.k"), "change")
    clock.t += 1
    assert not r.step()
    r.request(Path("big.k"), "save")
    assert r.step() and len(pub) == 2


def test_repeated_requests_coalesce():
    r, clock, ran, pub = _runner()
    for _ in range(5):
        r.request(Path("a.k"), "save")
    assert r.step() and not r.step() and len(ran) == 1


def test_result_of_superseded_request_is_discarded():
    r, clock, ran, pub = _runner()
    real = r.check

    def check_then_edit(main):
        rep = real(main)
        r.request(Path("a.k"), "save")   # a newer edit arrives while this check runs
        return rep
    r.check = check_then_edit
    r.request(Path("a.k"), "open")
    r.step()
    assert pub == []                      # the older result is never published
    r.check = real
    r.step()
    assert [p[1] for p in pub] == ["report a.k #2"]


def test_active_model_goes_first():
    r, _, ran, _ = _runner()
    r.request(Path("a.k"), "save")
    r.request(Path("b.k"), "save")
    r.active = r.key(Path("b.k"))
    r.step()
    assert ran == [Path("b.k")]


def test_file_request_runs_every_model_of_the_file():
    r, _, ran, _ = _runner(models=lambda f: [Path("a.k"), Path("b.k")])
    r.request(Path("mat.k"), "open")
    r.step()
    r.step()
    assert sorted(m.name for m in ran) == ["a.k", "b.k"]


def test_failed_check_is_published_as_an_error():
    r, _, _, pub = _runner()

    def boom(main):
        raise RuntimeError("bad")
    r.check = boom
    r.request(Path("a.k"), "open")
    r.step()
    assert pub[0][1] is None and isinstance(pub[0][2], RuntimeError)


def test_prepare_runs_before_mapping():
    order = []
    r = Runner(models=lambda f: order.append("map") or [f], check=lambda m: "r", publish=lambda *a: None,
               threshold=2.0, prepare=lambda: order.append("scan"))
    r.request(Path("a.k"), "open")
    r.step()
    assert order == ["scan", "map"]


def test_change_during_first_check_supersedes_it():
    r, clock, ran, pub = _runner()
    real = r.check

    def check_then_type(main):
        rep = real(main)
        r.request(Path("a.k"), "change")  # typing while the very first check runs: duration not known yet
        return rep
    r.check = check_then_type
    r.request(Path("a.k"), "open")
    r.step()
    assert pub == []                       # the first result read older text: discarded
    r.check = real
    clock.t += 0.31
    assert r.step() and [p[1] for p in pub] == ["report a.k #2"]


def test_big_model_keeps_its_first_result_when_typed_during_it():
    r, clock, ran, pub = _runner(durations={"big.k": 63.0})
    real = r.check

    def check_then_type(main):
        rep = real(main)
        r.request(Path("big.k"), "change")
        return rep
    r.check = check_then_type
    r.request(Path("big.k"), "open")
    r.step()
    assert len(pub) == 1                   # on-save model: the result stands until the next save


def test_worker_survives_a_failing_prepare():
    errors, calls = [], []

    def prepare():
        calls.append(1)
        if len(calls) == 1:
            raise RecursionError("deep include chain")
    published = []
    r = Runner(models=lambda f: [f], check=lambda m: "r", publish=lambda *a: published.append(a),
               threshold=2.0, prepare=prepare, report_error=errors.append)
    r.request(Path("a.k"), "open")
    r.step()
    assert isinstance(errors[0], RecursionError)
    r.request(Path("a.k"), "open")
    r.step()
    assert published
