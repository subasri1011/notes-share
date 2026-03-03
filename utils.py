import time
import logging
import random
import functools
from datetime import datetime, timedelta

# ─────────────────────────── Logging Configuration ──────────────────
logger = logging.getLogger('noteshare.utils')

# ─────────────────────────── Monitoring State ───────────────────────
_MONITORING_STATS = {
    'total_calls': 0,
    'total_failures': 0,
    'total_retries': 0,
    'circuit_trips': 0,
    'success_rate': 100.0,
    'recent_errors': []
}

def get_monitoring_stats():
    """Returns the current monitoring statistics."""
    if _MONITORING_STATS['total_calls'] > 0:
        _MONITORING_STATS['success_rate'] = (
            (_MONITORING_STATS['total_calls'] - _MONITORING_STATS['total_failures']) 
            / _MONITORING_STATS['total_calls'] * 100
        )
    return _MONITORING_STATS

# ─────────────────────────── Circuit Breaker ────────────────────────
class CircuitBreaker:
    """Implements a basic Circuit Breaker pattern."""
    def __init__(self, failure_threshold=5, recovery_timeout=60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = 'CLOSED'  # CLOSED, OPEN, HALF_OPEN

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        if self.failure_count >= self.failure_threshold:
            if self.state != 'OPEN':
                logger.warning(f"Circuit Breaker TRIP: State changed from {self.state} to OPEN")
                _MONITORING_STATS['circuit_trips'] += 1
            self.state = 'OPEN'

    def record_success(self):
        self.failure_count = 0
        if self.state != 'CLOSED':
            logger.info(f"Circuit Breaker RESET: State changed from {self.state} to CLOSED")
        self.state = 'CLOSED'

    def can_execute(self):
        if self.state == 'OPEN':
            if datetime.now() - self.last_failure_time > timedelta(seconds=self.recovery_timeout):
                self.state = 'HALF_OPEN'
                logger.info("Circuit Breaker HALF-OPEN: Testing recovery...")
                return True
            return False
        return True

# ─────────────────────────── Retry Decorator ────────────────────────
def with_retry(max_attempts=3, base_delay=1, max_delay=10, 
               exceptions=(Exception,), circuit_breaker=None):
    """
    Decorator for robust retry logic with exponential backoff and optional circuit breaker.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            _MONITORING_STATS['total_calls'] += 1
            
            if circuit_breaker and not circuit_breaker.can_execute():
                logger.error(f"Circuit OPEN: Skipping execution of {func.__name__}")
                _MONITORING_STATS['total_failures'] += 1
                raise Exception(f"Circuit is open for {func.__name__}")

            attempt = 1
            while attempt <= max_attempts:
                try:
                    result = func(*args, **kwargs)
                    if circuit_breaker:
                        circuit_breaker.record_success()
                    return result
                except exceptions as e:
                    logger.warning(f"Attempt {attempt}/{max_attempts} failed for {func.__name__}: {str(e)}")
                    
                    if attempt == max_attempts:
                        if circuit_breaker:
                            circuit_breaker.record_failure()
                        _MONITORING_STATS['total_failures'] += 1
                        _MONITORING_STATS['recent_errors'].append({
                            'func': func.__name__,
                            'error': str(e),
                            'time': datetime.now().isoformat()
                        })
                        if len(_MONITORING_STATS['recent_errors']) > 10:
                            _MONITORING_STATS['recent_errors'].pop(0)
                        raise

                    # Exponential backoff with jitter
                    delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                    jitter = random.uniform(0, 0.1 * delay)
                    sleep_time = delay + jitter
                    
                    logger.info(f"Retrying in {sleep_time:.2f}s...")
                    _MONITORING_STATS['total_retries'] += 1
                    time.sleep(sleep_time)
                    attempt += 1
            
            return None # Should not reach here
        return wrapper
    return decorator
