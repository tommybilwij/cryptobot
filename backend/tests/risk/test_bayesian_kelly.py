"""Tests for BayesianKellySizer — Normal-Normal conjugate update + LCI Kelly."""

from __future__ import annotations

from app.risk.bayesian_kelly import BayesianKellySizer


def test_posterior_converges_toward_observed_mean() -> None:
    """After many positive updates the posterior mean drifts toward the obs mean.

    With a vague prior (mu=0, sigma2=1) and a stream of returns averaging 0.05,
    the posterior should land within a small epsilon of 0.05 after enough
    observations — that is the textbook contract for Normal-Normal updates.
    """
    sizer = BayesianKellySizer(mu_prior=0.0, sigma2_prior=1.0, sigma2_obs=1.0)
    for _ in range(500):
        sizer.update(0.05)
    assert abs(sizer.state.mu_posterior - 0.05) < 0.01
    # And the posterior variance shrinks well below the prior.
    assert sizer.state.sigma2_posterior < 0.01
    assert sizer.state.n_observed == 500


def test_negative_observations_drop_posterior_mu() -> None:
    """Streaming negative returns pulls the posterior mean below zero."""
    sizer = BayesianKellySizer(mu_prior=0.1, sigma2_prior=1.0, sigma2_obs=1.0)
    for _ in range(100):
        sizer.update(-0.02)
    assert sizer.state.mu_posterior < 0.0


def test_kelly_fraction_zero_when_lci_drives_mu_negative() -> None:
    """A wide posterior with mu>0 still returns 0 if mu - z*sigma <= 0."""
    sizer = BayesianKellySizer(mu_prior=0.01, sigma2_prior=1.0, sigma2_obs=1.0)
    # No updates: posterior is the prior. LCI = 0.01 - 1.645*1.0 < 0 -> zero size.
    assert sizer.kelly_fraction(confidence=0.95) == 0.0


def test_kelly_fraction_positive_after_enough_updates() -> None:
    """Once the posterior tightens around a positive mean, Kelly turns on."""
    sizer = BayesianKellySizer(mu_prior=0.0, sigma2_prior=1.0, sigma2_obs=1.0)
    for _ in range(1000):
        sizer.update(0.1)
    frac = sizer.kelly_fraction(confidence=0.95)
    assert frac > 0.0


def test_confidence_level_changes_size_monotonically() -> None:
    """Higher confidence (wider LCI) gives a smaller — or zero — Kelly fraction."""
    sizer = BayesianKellySizer(mu_prior=0.0, sigma2_prior=1.0, sigma2_obs=1.0)
    for _ in range(500):
        sizer.update(0.08)
    f_low = sizer.kelly_fraction(confidence=0.90)
    f_mid = sizer.kelly_fraction(confidence=0.95)
    f_high = sizer.kelly_fraction(confidence=0.99)
    # Stricter LCI -> more pessimistic mean -> smaller fraction.
    assert f_low >= f_mid >= f_high >= 0.0
