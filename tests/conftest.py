"""Suite-wide test configuration.

The model executor defaults to worker PROCESSES in production (see app/runtime/model_execution.py).
Most existing tests replace engine functions in-process with ``mock.patch``; a spawned worker
would not see those patches. The suite therefore defaults to the executor's THREAD mode, which
keeps the same admission gate and typed BUSY behaviour. The process-mode tests
(tests/test_p0a_model_execution.py) select process mode explicitly.
"""
import os

os.environ.setdefault("FINCO_MODEL_EXECUTION_MODE", "thread")
