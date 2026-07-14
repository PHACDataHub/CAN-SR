"""Generic scheduler persistence compatibility layer.

The physical tables and legacy import names remain ``run_all_*`` during the
additive migration. New scheduler code should depend on this module so those
names can be changed later without another orchestration refactor.
"""

from .run_all_repo import RunAllRepo as SchedulerRepository
from .run_all_repo import run_all_repo as scheduler_repo

__all__ = ['SchedulerRepository', 'scheduler_repo']