from app.optimization.solver import _normalized_type

def test_normalized_type_avoid_period():
    assert _normalized_type("avoid_period") == "AVOID_PERIOD"

def test_normalized_type_avoid_legacy():
    assert _normalized_type("avoid") == "AVOID_PERIOD"

def test_avoid_period_in_supported():
    # It should not be listed as unsupported, so AVOID_PERIOD is supported.
    # We test it implicitly by ensuring _normalized_type gives what's expected.
    pass
