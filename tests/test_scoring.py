from premarket_scanner.scoring import capped_rvol, compute_acceleration, compute_score


def test_sustained_increasing_ratios():
    # deltas: 100 -> 150 -> 240 -> 400  => ratios 1.5, 1.6, 1.667 (non-decreasing)
    result = compute_acceleration([100, 150, 240, 400])
    assert result.sustained is True
    assert len(result.ratios) == 3
    assert result.score > 1.0


def test_all_growing_but_not_monotonic_ratios_still_sustained():
    # ratios: 2.0, 1.2, 1.5 -- not non-decreasing, but all > 1.0
    result = compute_acceleration([100, 200, 240, 360])
    assert result.sustained is True


def test_declining_ratio_not_sustained():
    # ratios: 2.0, 0.9, 1.1 -- fails both the non-decreasing and all>1 checks
    result = compute_acceleration([100, 200, 180, 198])
    assert result.sustained is False
    assert result.score == 0.0


def test_single_spike_not_sustained():
    # one big spike then flat/declining
    result = compute_acceleration([100, 500, 100, 90])
    assert result.sustained is False


def test_insufficient_windows():
    result = compute_acceleration([100, 200, 300])
    assert result.sustained is False
    assert result.score == 0.0


def test_zero_baseline_window_not_sustained():
    result = compute_acceleration([0, 100, 200, 300])
    assert result.sustained is False


def test_compute_score_weights():
    score = compute_score(
        acceleration_score=2.0,
        rvol=3.0,
        price_change_pct_abs=5.0,
        weight_acceleration=0.6,
        weight_rvol=0.25,
        weight_price=0.15,
    )
    assert score == 2.0 * 0.6 + 3.0 * 0.25 + 5.0 * 0.15


def test_capped_rvol_limits_extreme_values():
    # A 40x RVOL reading (real thing seen on illiquid microcaps) shouldn't be
    # able to single-handedly blow past the alert threshold.
    assert capped_rvol(40.0, cap=5.0) == 5.0


def test_capped_rvol_passes_through_normal_values():
    assert capped_rvol(2.3, cap=5.0) == 2.3


def test_extreme_rvol_no_longer_dominates_score():
    # Zero acceleration contribution, zero price move -- with an uncapped
    # 40x RVOL the score alone would be 10.0, well past any sane threshold.
    # Capped, it should stay well under a 3.0 threshold.
    score = compute_score(
        acceleration_score=0.0,
        rvol=capped_rvol(40.0, cap=5.0),
        price_change_pct_abs=0.0,
        weight_acceleration=0.6,
        weight_rvol=0.25,
        weight_price=0.15,
    )
    assert score < 3.0
