from __future__ import annotations
import random
import time


def sleep_with_jitter(seconds: float, jitter_range: float= 0.0) -> None:
    """Sleep for a given time plus a random jitter."""
    time.sleep(max(0.0, seconds + random.uniform(0.0, jitter_range)))

    
   
