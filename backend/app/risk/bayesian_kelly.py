"""Bayesian Kelly sizer — Normal-Normal conjugate update.

Prior: ``N(mu_prior, sigma_prior^2)``
Likelihood for each observation: ``N(mu, sigma_obs^2)``
Posterior after k observations: standard conjugate formula —
``precision_post = precision_prior + precision_obs``,
``mu_post = (mu_prior * precision_prior + obs_mean * precision_obs) / precision_post``.

The Kelly fraction is then computed from the posterior mean + variance with a
configurable lower-confidence-interval shrinkage. Using ``mu_post - z*sigma_post``
in place of the raw mean gives a "pessimistic Kelly" that is robust to the
small-sample over-confidence we see early in a strategy's life: when the
posterior is wide, the LCI lowers the size; once data narrows the posterior,
the size converges toward classical Kelly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Numerical floor so a degenerate (zero) variance never produces an
# infinite precision update. 1e-9 is well below any plausible return variance
# yet above float64 underflow risk.
_MIN_VARIANCE = 1e-9
# Default LCI confidence: 1.645 sigma below the posterior mean.
_DEFAULT_CONFIDENCE = 0.95


@dataclass
class BayesianKellyState:
    """Posterior state — mean, variance, and observation count."""

    mu_posterior: float
    sigma2_posterior: float
    n_observed: int


class BayesianKellySizer:
    """Online Normal-Normal posterior + LCI-shrunk Kelly fraction.

    The sizer is mutable — each ``update()`` advances the posterior in place
    so a long-lived live strategy can call ``kelly_fraction()`` at any tick
    and get a fresh sizing recommendation reflecting all observed returns.
    """

    def __init__(
        self,
        *,
        mu_prior: float = 0.0,
        sigma2_prior: float = 1.0,
        sigma2_obs: float = 1.0,
    ) -> None:
        self._state = BayesianKellyState(
            mu_posterior=mu_prior,
            sigma2_posterior=sigma2_prior,
            n_observed=0,
        )
        self._sigma2_obs = sigma2_obs

    @property
    def state(self) -> BayesianKellyState:
        """Read-only snapshot of the current posterior."""
        return self._state

    def update(self, observed_return: float) -> None:
        """Apply one Normal-Normal conjugate update.

        Each observation contributes precision ``1/sigma2_obs``; the posterior
        mean is the precision-weighted average of the prior mean and the new
        observation. Variance shrinks monotonically with each update.
        """
        s = self._state
        prior_precision = 1.0 / max(s.sigma2_posterior, _MIN_VARIANCE)
        obs_precision = 1.0 / max(self._sigma2_obs, _MIN_VARIANCE)
        new_precision = prior_precision + obs_precision
        new_mu = (
            (s.mu_posterior * prior_precision + observed_return * obs_precision)
            / new_precision
        )
        new_sigma2 = 1.0 / new_precision
        self._state = BayesianKellyState(
            mu_posterior=new_mu,
            sigma2_posterior=new_sigma2,
            n_observed=s.n_observed + 1,
        )

    def kelly_fraction(self, *, confidence: float = _DEFAULT_CONFIDENCE) -> float:
        """Pessimistic Kelly using the lower-confidence-interval of mu.

        Returns ``(mu_post - z*sigma_post) / sigma2_post`` clamped at zero —
        a wide posterior with mu just above zero collapses to zero size,
        which is the desired "no conviction, no bet" behaviour for a
        cold-start sizer. The classical Kelly ``mu / sigma^2`` is recovered
        as the posterior tightens.
        """
        z_table = {0.90: 1.282, 0.95: 1.645, 0.99: 2.326}
        z = z_table.get(round(confidence, 2), z_table[_DEFAULT_CONFIDENCE])
        s = self._state
        std = math.sqrt(max(s.sigma2_posterior, _MIN_VARIANCE))
        adjusted_mu = s.mu_posterior - z * std
        if adjusted_mu <= 0.0:
            return 0.0
        if s.sigma2_posterior <= _MIN_VARIANCE:
            return 0.0
        return adjusted_mu / s.sigma2_posterior
