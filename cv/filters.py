"""Reusable signal filters.

OneEuroFilter is the adaptive low-pass we use on pointer sources to kill jitter
when still and stay responsive when moving fast.
"""

from __future__ import annotations

import math


class OneEuroFilter:
    """1-Euro filter — adaptive low-pass for pointer tracking.

    Filters hard when the signal is still (kills jitter) and lets fast motion
    through cleanly (stays responsive). Casiez, Roussel, Vogel 2012.
    https://gery.casiez.net/1euro/
    """

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.05, d_cutoff: float = 1.0) -> None:
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.x_prev: float | None = None
        self.dx_prev: float = 0.0
        self.t_prev: float | None = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        r = 2 * math.pi * cutoff * dt
        return r / (r + 1)

    def filter(self, x: float, t: float) -> float:
        if self.t_prev is None or self.x_prev is None:
            self.t_prev = t
            self.x_prev = x
            return x
        dt = max(t - self.t_prev, 1e-6)
        dx = (x - self.x_prev) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        dx_hat = a_d * dx + (1 - a_d) * self.dx_prev
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        a = self._alpha(cutoff, dt)
        x_hat = a * x + (1 - a) * self.x_prev
        self.x_prev = x_hat
        self.dx_prev = dx_hat
        self.t_prev = t
        return x_hat

    def reset(self) -> None:
        self.x_prev = None
        self.dx_prev = 0.0
        self.t_prev = None
