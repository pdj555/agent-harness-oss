from tracker import classify_priority


def test_high_priority():
    assert classify_priority(5, 5) == "high"
    assert classify_priority(4, 4) == "high"


def test_medium_priority():
    assert classify_priority(3, 1) == "medium"
    assert classify_priority(1, 3) == "medium"
    assert classify_priority(5, 2) == "medium"


def test_low_priority():
    assert classify_priority(1, 1) == "low"
    assert classify_priority(2, 2) == "low"


def test_rejects_out_of_range():
    try:
        classify_priority(0, 3)
    except ValueError:
        return
    raise AssertionError("expected ValueError")
