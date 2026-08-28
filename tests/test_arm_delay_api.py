from hantek1008c import acquire


class Tx:
    def __init__(self, rx=b"", timed_out=False):
        self.rx = rx
        self.timed_out = timed_out


class FakeScope:
    def __init__(self):
        self.tx = []
        self.a5 = 0

    def transact(self, payload, read_timeout_ms=1000):
        self.tx.append(bytes(payload))
        if payload == bytes.fromhex("A5 5A"):
            self.a5 += 1
            return Tx(bytes([0, 2 if self.a5 >= 3 else 1]))
        if payload in (bytes.fromhex("C6 02"), bytes.fromhex("C6 03")):
            return Tx(b"\x00\x00")
        return Tx(payload[:1])

    def write(self, payload, timeout_ms=1000):
        self.tx.append(bytes(payload))

    def read(self, size=64, timeout_ms=1000):
        return bytes(size)


def test_wait_ready_with_polls_reports_poll_count(monkeypatch):
    monkeypatch.setattr(acquire.time, "sleep", lambda _: None)
    scope = FakeScope()
    state, polls = acquire.wait_ready_with_polls(scope)
    assert state == 2
    assert polls == 3


def test_acquire_direct_buffers_zero_arm_delay_skips_fixed_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(acquire.time, "sleep", sleeps.append)
    scope = FakeScope()
    b2, b3, state, polls = acquire.acquire_direct_buffers(
        scope, arm_delay_s=0.0, return_ready_info=True
    )
    assert b2 == b""
    assert b3 == b""
    assert state == 2
    assert polls == 3
    assert 0.015 not in sleeps
    assert bytes.fromhex("A4 01") in scope.tx
    assert b"\xC0" in scope.tx
    assert b"\xC2" in scope.tx
