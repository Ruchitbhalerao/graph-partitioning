"""Resource management utilities for production optimization.

Provides:
  - ResourceMonitor — CPU, memory, disk monitoring
  - TempFileManager — automatic cleanup of temporary files
  - TimeoutManager — timeout and retry mechanisms
  - ConcurrencyLimiter — limit concurrent operations
"""

import os
import psutil
import shutil
import time
import threading
import signal
from datetime import datetime, timedelta
from typing import Optional, Callable, Dict, List, Any
from functools import wraps

from .metrics import get_metrics, METRIC_MEMORY_USAGE, METRIC_DISK_USAGE


class ResourceMonitor:
    """Monitor system resources (CPU, memory, disk) and record to metrics."""

    def __init__(self, check_interval_sec: float = 30.0):
        self._interval = check_interval_sec
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self):
        while self._running:
            self._check()
            time.sleep(self._interval)

    def _check(self):
        try:
            process = psutil.Process(os.getpid())
            mem_info = process.memory_info()
            get_metrics().gauge(METRIC_MEMORY_USAGE, mem_info.rss)

            # Disk usage for output directories
            for path, metric_name in [
                (os.path.expanduser("~"), "disk_home"),
                ("/tmp", "disk_tmp"),
            ]:
                try:
                    usage = shutil.disk_usage(path)
                    get_metrics().gauge(f"{METRIC_DISK_USAGE}_{metric_name}_free", usage.free)
                    get_metrics().gauge(f"{METRIC_DISK_USAGE}_{metric_name}_total", usage.total)
                except Exception:
                    pass
        except Exception:
            pass

    @staticmethod
    def memory_usage_mb() -> float:
        try:
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / 1024 / 1024
        except Exception:
            return 0.0

    @staticmethod
    def cpu_percent() -> float:
        try:
            process = psutil.Process(os.getpid())
            return process.cpu_percent(interval=0.1)
        except Exception:
            return 0.0


class TempFileManager:
    """Manage and clean up temporary files and directories.

    Tracks all created temp dirs/files and provides cleanup on schedule
    or on demand. Limits total disk usage per job.
    """

    def __init__(self, base_dir: str = "/tmp/tos_outputs", max_age_hours: int = 24):
        self.base_dir = base_dir
        self.max_age = timedelta(hours=max_age_hours)
        self._tracked: Dict[str, datetime] = {}
        self._lock = threading.RLock()
        os.makedirs(base_dir, exist_ok=True)

    def register(self, path: str):
        with self._lock:
            self._tracked[path] = datetime.now()

    def unregister(self, path: str):
        with self._lock:
            self._tracked.pop(path, None)

    def cleanup_job(self, job_id: str):
        """Remove all files associated with a job."""
        job_dir = os.path.join(self.base_dir, job_id)
        if os.path.exists(job_dir):
            shutil.rmtree(job_dir, ignore_errors=True)
        self.unregister(job_dir)

    def cleanup_expired(self):
        """Remove all tracked files older than max_age."""
        now = datetime.now()
        with self._lock:
            expired = [
                path for path, created in self._tracked.items()
                if now - created > self.max_age
            ]
            for path in expired:
                if os.path.exists(path):
                    if os.path.isfile(path):
                        os.remove(path)
                    elif os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                del self._tracked[path]

    def cleanup_all(self):
        """Remove all tracked files."""
        with self._lock:
            for path in list(self._tracked.keys()):
                if os.path.exists(path):
                    if os.path.isfile(path):
                        os.remove(path)
                    elif os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
            self._tracked.clear()

    def disk_usage(self, job_id: str) -> int:
        """Get disk usage in bytes for a job."""
        job_dir = os.path.join(self.base_dir, job_id)
        if not os.path.exists(job_dir):
            return 0
        total = 0
        for dirpath, _, filenames in os.walk(job_dir):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
        return total

    def total_disk_usage(self) -> int:
        """Get total disk usage for all tracked jobs."""
        with self._lock:
            return sum(
                self.disk_usage(os.path.basename(p))
                for p in self._tracked
                if os.path.isdir(p)
            )


class TimeoutManager:
    """Manage timeout and retry for long-running operations."""

    def __init__(self, default_timeout_sec: float = 300.0):
        self.default_timeout = default_timeout_sec

    def run_with_timeout(self, func: Callable, timeout_sec: Optional[float] = None, *args, **kwargs):
        """Run a function with a timeout. Raises TimeoutError if exceeded."""
        timeout = timeout_sec or self.default_timeout
        result = [None]
        error = [None]
        event = threading.Event()

        def worker():
            try:
                result[0] = func(*args, **kwargs)
            except Exception as e:
                error[0] = e
            finally:
                event.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            raise TimeoutError(f"Operation timed out after {timeout}s")
        if error[0]:
            raise error[0]
        return result[0]

    @staticmethod
    def retry(max_retries: int = 3, delay_sec: float = 1.0, backoff: float = 2.0):
        """Decorator: retry a function on failure with exponential backoff."""
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                last_error = None
                wait = delay_sec
                for attempt in range(max_retries):
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        last_error = e
                        if attempt < max_retries - 1:
                            get_metrics().increment("retry_attempt", labels={"func": func.__name__})
                            time.sleep(wait)
                            wait *= backoff
                raise last_error
            return wrapper
        return decorator


class ConcurrencyLimiter:
    """Semaphore-based limiter for concurrent operations.

    Limits the number of concurrent SM region processing tasks
    and other parallel operations to prevent resource exhaustion.
    """

    def __init__(self, max_concurrent: int = 4):
        self._semaphore = threading.Semaphore(max_concurrent)
        self._active = 0
        self._lock = threading.RLock()
        self._max = max_concurrent

    def acquire(self, blocking: bool = True) -> bool:
        acquired = self._semaphore.acquire(blocking=blocking)
        if acquired:
            with self._lock:
                self._active += 1
        return acquired

    def release(self):
        with self._lock:
            self._active -= 1
        self._semaphore.release()

    def active_count(self) -> int:
        with self._lock:
            return self._active

    def available(self) -> int:
        return self._max - self.active_count()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()


# Global instances
_temp_file_manager = TempFileManager()
_resource_monitor = ResourceMonitor()
_timeout_manager = TimeoutManager()


def get_temp_file_manager() -> TempFileManager:
    return _temp_file_manager


def get_resource_monitor() -> ResourceMonitor:
    return _resource_monitor


def get_timeout_manager() -> TimeoutManager:
    return _timeout_manager
