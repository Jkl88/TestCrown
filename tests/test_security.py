from app.security import generate_api_key, hash_key, key_prefix


def test_key_format_and_hash_stable():
    raw = generate_api_key()
    assert raw.startswith("crn_")
    assert len(raw) > 20
    assert hash_key(raw) == hash_key(raw)
    assert hash_key(raw) != hash_key(raw + "x")
    assert key_prefix(raw) == raw[:12]
    assert len(hash_key(raw)) == 64
