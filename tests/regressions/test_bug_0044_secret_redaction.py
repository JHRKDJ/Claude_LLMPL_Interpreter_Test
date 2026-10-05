"""BUG-0044 (second audit, T13): diagnostic capture leaked credentials it should
recognise (V3 7.13.4, 8.20): a password inside a connection URL, `DB_PASSWORD=...`
text, an ("api_key", token) pair, a token not at the start of a string, a value copied
out of a `sensitive` field into a local or parameter, and a secret interpolated into a
program's own assert message. JSON reported `"redacted": false` even when the
diagnostic contained `<redacted>`."""
import json

from lang.diagnostics.render_json import render_json
from lang.diagnostics.render_text import render_all
from tests.helpers import run

SECRETS = ["SuperSecretPass", "envsecret999", "sk-live-abcdefghijklmnop1234567890", "TopSecretValue123",
           "field-secret-pw", "hunter2-secret"]


def everything(r) -> str:
    return render_all(r.diags, "deep") + render_json(r.diags)


def test_credentials_in_locals_are_redacted():
    r = run("""
record Creds { user: Str, sensitive pw: Str }
fn main() {
    let c = Creds(user: "bob", pw: "hunter2-secret")
    let conn = "postgres://admin:SuperSecretPass@db.example.com/prod"
    let pair = ("api_key", "sk-live-abcdefghijklmnop1234567890")
    let env = ["DB_PASSWORD=envsecret999"]
    let copied = c.pw
    let xs = [1]
    print(xs[3])
}""")
    text = everything(r)
    assert r.codes == ["A.INDEX.OUT_OF_RANGE"]
    for s in SECRETS:
        assert s not in text, s
    assert "postgres://admin:<redacted>@db.example.com/prod" in text  # non-secret context kept
    assert json.loads(render_json(r.diags))["diagnostics"][0]["redacted"] is True


def test_secret_copied_into_parameter_and_message():
    r = run("""
record Login { user: Str, password: Str }
record Creds { sensitive pw: Str }
fn id(v) { return v }
fn needInt(n: Int) -> Int { return n }
fn main() {
    let l = Login(user: "u", password: "field-secret-pw")
    let c = Creds(pw: "TopSecretValue123")
    print(needInt(id(c.pw)))
}""")
    assert r.codes == ["A.TYPE.DYNAMIC_MISMATCH"]
    text = everything(r)
    assert "TopSecretValue123" not in text and "field-secret-pw" not in text
    r = run("""
record Login { user: Str, password: Str }
fn main() { let l = Login(user: "u", password: "field-secret-pw")
  assert false, "login failed for {l.password}" }""")
    text = everything(r)
    assert "field-secret-pw" not in text and "login failed for <redacted>" in text


def test_masking_is_linear_on_long_inputs():
    # the first version of the credential patterns backtracked quadratically on long
    # alphanumeric runs (found while fixing this bug); diagnostics must stay cheap
    import time
    from lang.runtime.capture import mask_text
    start = time.monotonic()
    for s in ("x" * 200000, "password" * 25000, "a=b " * 50000, "user:pw@" * 20000):
        mask_text(s)
    assert time.monotonic() - start < 2.0
