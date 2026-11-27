"""Universal Scalability Law least-squares fit per the assignment's
linearization: y(N) = N/C(N) - 1 = sigma*(N-1) + kappa*N*(N-1),
C(N) = X(N)/X(1)."""

from __future__ import annotations


def usl_throughput(n: int, lam: float, sigma: float, kappa: float) -> float:
    return lam * n / (1 + sigma * (n - 1) + kappa * n * (n - 1))


def fit_usl(points: list[tuple[int, float]], lam: float) -> tuple[float, float]:
    u_vals = []
    v_vals = []
    y_vals = []
    for n, x_n in points:
        c_n = x_n / lam
        y = n / c_n - 1
        u_vals.append(n - 1)
        v_vals.append(n * (n - 1))
        y_vals.append(y)

    sum_u2 = sum(u * u for u in u_vals)
    sum_v2 = sum(v * v for v in v_vals)
    sum_uv = sum(u * v for u, v in zip(u_vals, v_vals))
    sum_uy = sum(u * y for u, y in zip(u_vals, y_vals))
    sum_vy = sum(v * y for v, y in zip(v_vals, y_vals))

    denom = sum_u2 * sum_v2 - sum_uv**2
    sigma = (sum_v2 * sum_uy - sum_uv * sum_vy) / denom
    kappa = (sum_u2 * sum_vy - sum_uv * sum_uy) / denom

    if sigma < 0:
        sigma = 0.0
        kappa = sum_vy / sum_v2 if sum_v2 else 0.0
    elif kappa < 0:
        kappa = 0.0
        sigma = sum_uy / sum_u2 if sum_u2 else 0.0

    return sigma, kappa


def optimal_n(sigma: float, kappa: float) -> float | None:
    if kappa > 0 and sigma < 1:
        return ((1 - sigma) / kappa) ** 0.5
    return None
