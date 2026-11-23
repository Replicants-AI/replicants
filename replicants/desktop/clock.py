"""Development body time. Model calls and host wake limits keep wall time."""
from __future__ import annotations

import math
import os
import time


def time_scale(value) -> float:
    scale = float(value)
    if not math.isfinite(scale) or not 1 <= scale <= 360:
        raise ValueError('Development time scale must be between 1 and 360.')
    return scale


class SimClock:
    def __init__(self, saved=None, *, wall=time.time, monotonic=time.monotonic):
        saved = saved or {}
        self._wall, self._monotonic = wall, monotonic
        self.scale = (1.0 if os.environ.get('REPLICANTS_BETA') == '1' else
                      time_scale(os.environ.get('REPLICANTS_TIME_SCALE', saved.get('scale', 1))))
        self._at = monotonic()
        now = wall()
        self._sim = float(saved.get('sim', now)) + max(0, now - float(saved.get('wall', now))) * time_scale(saved.get('scale', 1))
        if not saved and 'REPLICANTS_START_HOUR' in os.environ:
            hour = float(os.environ['REPLICANTS_START_HOUR'])
            if not math.isfinite(hour) or not 0 <= hour < 24: raise ValueError('Start hour must be in [0, 24).')
            local = time.localtime(now)
            midnight = time.mktime((*local[:3], 0, 0, 0, *local[6:]))
            self._sim = midnight + hour * 3600

    def now(self): return self._sim + (self._monotonic() - self._at) * self.scale

    @property
    def hour(self):
        local = time.localtime(self.now())
        return local.tm_hour + local.tm_min / 60 + local.tm_sec / 3600

    def change_scale(self, value):
        scale = time_scale(value)
        self._sim, self._at = self.now(), self._monotonic()
        self.scale = scale

    def snapshot(self): return {'sim': self.now(), 'wall': self._wall(), 'scale': self.scale}
