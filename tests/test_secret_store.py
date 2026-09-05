from invoice_processor.secret_store import PREFIX, decrypt, encrypt


def test_secret_store_round_trip_without_real_credentials() -> None:
    encrypted = encrypt("test-secret")

    assert encrypted.startswith(PREFIX)
    assert decrypt(encrypted) == "test-secret"


def test_secret_store_keeps_historical_plaintext_compatibility() -> None:
    assert decrypt("legacy-plain-text") == "legacy-plain-text"
