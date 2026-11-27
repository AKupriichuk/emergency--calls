import pytest

from analysis.scalability import fit_usl, optimal_n, usl_throughput


def test_fit_usl_recovers_known_sigma_and_kappa():
    sigma, kappa = 0.05, 0.001
    lam = 500.0
    points = [(n, usl_throughput(n, lam, sigma, kappa)) for n in (2, 3, 4)]
    fitted_sigma, fitted_kappa = fit_usl(points, lam)
    assert fitted_sigma == pytest.approx(sigma, abs=1e-6)
    assert fitted_kappa == pytest.approx(kappa, abs=1e-6)


def test_fit_usl_clamps_negative_sigma_to_zero():
    # kappa-only data: C(N) grows slower than 1/N would from sigma alone
    points = [(2, 480.0), (3, 420.0), (4, 300.0)]
    sigma, kappa = fit_usl(points, lam=260.0)
    assert sigma >= 0
    assert kappa >= 0


def test_optimal_n_matches_formula():
    assert optimal_n(sigma=0.05, kappa=0.001) == pytest.approx(((1 - 0.05) / 0.001) ** 0.5)


def test_optimal_n_is_none_when_kappa_zero():
    assert optimal_n(sigma=0.05, kappa=0.0) is None
