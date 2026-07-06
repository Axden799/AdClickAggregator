from app.security import sign_impression, verify_impression

# These are the SIMPLEST tests to write: sign_impression / verify_impression
# are pure functions — no Redis, no HTTP, no async. Plain sync tests.


def test_sign_is_deterministic():
    # TODO (you): signing the same (impression_id, ad_id) twice must produce
    # the SAME signature. Assert that.
    impression_id = "test-imp-1"
    ad_id = 234
    req1 = sign_impression(impression_id, ad_id)
    req2 = sign_impression(impression_id, ad_id)
    assert req1 == req2

def test_verify_accepts_a_genuine_signature():
    # TODO (you): a signature produced by sign_impression(...) must verify
    # True for the same impression_id + ad_id.
    impression_id = "test-imp-1"
    ad_id = 234
    sig = sign_impression(impression_id, ad_id)
    assert verify_impression(impression_id, ad_id, sig) is True


def test_verify_rejects_a_tampered_ad_id():
    # TODO (you): a signature made for one ad_id must NOT verify against a
    # different ad_id (this is the tamper-protection you built).
    impression_id = "test-imp-1"
    sig = sign_impression(impression_id, 234)
    assert verify_impression(impression_id, 235, sig) is False
