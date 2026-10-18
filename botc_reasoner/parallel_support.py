"""把互不依赖的求解任务分到多个进程。

每个进程在 fork 时拿到自己的求解器副本，不共用同一个 Z3 上下文。
任务参数里只放可序列化的编号；求解器和公式放在模块槽里，由子进程继承。
"""

from __future__ import annotations

import multiprocessing as mp
import os
from concurrent.futures import ProcessPoolExecutor

_SLOT: dict = {}
_SNAPSHOT: dict = {}
_TASK_FN = None
_LOCAL_BUDGET: int | None = None


def bind_slot(**kwargs) -> None:
    _SLOT.clear()
    _SLOT.update(kwargs)


def slot() -> dict:
    return _SLOT


def _run_saved(item):
    """每个任务先回到这一批开始时的槽，再执行。函数放在模块层，fork 后仍可调用。"""

    _SLOT.clear()
    _SLOT.update(_SNAPSHOT)
    return _TASK_FN(item)


def _init_budget(budget: int) -> None:
    """池里的子进程只用这个名额，避免再往下拆。"""

    global _LOCAL_BUDGET
    _LOCAL_BUDGET = budget


def group_budget_for(n_parallel: int) -> int:
    """若干路任务同时跑时，每一路能分到多少核。"""

    cpus = os.cpu_count() or 1
    if n_parallel <= 1:
        return cpus
    return max(1, cpus // n_parallel)


def worker_count(ntasks: int, requested: int | None = None) -> int:
    """按任务数、CPU 数和当前进程的名额决定进程数。

    主进程默认用满所有核。世界进程的名额在创建时写好，组进程的名额是 1。
    """

    if ntasks <= 1:
        return 1
    budget = _LOCAL_BUDGET
    if budget is None:
        if mp.current_process().name != "MainProcess":
            return 1
        budget = os.cpu_count() or 1
    if requested is not None:
        budget = min(budget, requested)
    return max(1, min(ntasks, budget))


def map_in_order(fn, items: list, workers: int, child_budget: int = 1) -> list:
    """按输入顺序返回结果，和逐个调用 ``fn`` 相同。

    每个任务开始前都把模块槽恢复成调用这一批任务时的内容。
    这样同一进程接着做下一组或下一个世界时，不会读到上一组改写后的槽。
    """

    global _SNAPSHOT, _TASK_FN
    previous_snapshot = _SNAPSHOT
    previous_fn = _TASK_FN
    _SNAPSHOT = dict(_SLOT)
    _TASK_FN = fn
    try:
        if workers <= 1 or len(items) <= 1:
            return [_run_saved(item) for item in items]
        context = mp.get_context("fork")
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
            initializer=_init_budget,
            initargs=(child_budget,),
        ) as pool:
            return list(pool.map(_run_saved, items, chunksize=1))
    finally:
        _SNAPSHOT = previous_snapshot
        _TASK_FN = previous_fn
