import itertools
import multiprocessing
import pytest
import threading
import time
from typing import Any, Tuple  # NOQA
from typing import Callable  # NOQA
from typing import Dict  # NOQA
from typing import Optional  # NOQA

import pfnopt
from pfnopt import client as client_module  # NOQA
from pfnopt.storage import InMemoryStorage
from pfnopt.storage import RDBStorage
from pfnopt import trial as trial_module


def func(x, y):
    # type: (float, float) -> float
    return (x - 2) ** 2 + (y - 25) ** 2


class Func(object):

    def __init__(self, sleep_sec=None):
        # type: (Optional[float]) -> None
        self.n_calls = 0
        self.sleep_sec = sleep_sec
        self.lock = threading.Lock()

    def __call__(self, client):
        # type: (client_module.BaseClient) -> float
        with self.lock:
            self.n_calls += 1

        # Sleep for testing parallelism
        if self.sleep_sec is not None:
            time.sleep(self.sleep_sec)

        x = client.sample_uniform('x', -10, 10)
        y = client.sample_uniform('y', 20, 30)
        return func(x, y)


def check_params(params):
    # type: (Dict[str, Any]) -> None
    assert sorted(params.keys()) == ['x', 'y']


def check_value(value):
    # type: (float) -> None
    assert isinstance(value, float)
    assert 0.0 <= value <= 12.0 ** 2 + 5.0 ** 2


def check_trial(trial):
    # type: (trial_module.Trial) -> None

    if trial.state == trial_module.State.COMPLETE:
        check_params(trial.params)
        check_value(trial.value)


def check_study(study):
    # type: (pfnopt.Study) -> None
    check_params(study.best_params)
    check_value(study.best_value)
    check_trial(study.best_trial)

    for trial in study.trials:
        check_trial(trial)


@pytest.mark.parametrize('n_trials, n_jobs, storage_class_kwargs', itertools.product(
    (1, 2, 50),  # n_trials
    (1, 2, 10, -1),  # n_jobs
    ((InMemoryStorage, {}), (RDBStorage, {'url': 'sqlite:///:memory:'})),  # storage_class_kwargs
))
def test_minimize(n_trials, n_jobs, storage_class_kwargs):
    # type: (int, int, Tuple[Callable, Dict[str, Any]])-> None

    f = Func()
    storage = storage_class_kwargs[0](**storage_class_kwargs[1])

    if isinstance(storage, RDBStorage) and n_jobs != 1:
        with pytest.raises(TypeError):
            pfnopt.minimize(f, n_trials=n_trials, n_jobs=n_jobs, storage=storage)
        storage.close()
        return

    study = pfnopt.minimize(f, n_trials=n_trials, n_jobs=n_jobs, storage=storage)
    assert f.n_calls == len(study.trials) == n_trials
    check_study(study)

    storage.close()


@pytest.mark.parametrize('n_trials, n_jobs, storage_class_kwargs', itertools.product(
    (1, 2, 50, None),  # n_trials
    (1, 2, 10, -1),  # n_jobs
    ((InMemoryStorage, {}), (RDBStorage, {'url': 'sqlite:///:memory:'})),  # storage_class_kwargs
))
def test_minimize_timeout(n_trials, n_jobs, storage_class_kwargs):
    # type: (int, int, Tuple[Callable, Dict[str, Any]]) -> None

    sleep_sec = 0.1
    timeout_sec = 1.0

    f = Func(sleep_sec=sleep_sec)
    storage = storage_class_kwargs[0](**storage_class_kwargs[1])

    if isinstance(storage, RDBStorage) and n_jobs != 1:
        with pytest.raises(TypeError):
            pfnopt.minimize(
                f, n_trials=n_trials, n_jobs=n_jobs, storage=storage, timeout_seconds=timeout_sec)
        storage.close()
        return

    study = pfnopt.minimize(
        f, n_trials=n_trials, n_jobs=n_jobs, storage=storage, timeout_seconds=timeout_sec)

    assert f.n_calls == len(study.trials)

    if n_trials is not None:
        assert f.n_calls <= n_trials

    # A thread can process at most (timeout_sec / sleep_sec + 1) trials
    max_calls = timeout_sec / sleep_sec + 1
    if n_jobs != -1:
        max_calls *= n_jobs
    else:
        max_calls *= multiprocessing.cpu_count()
    assert f.n_calls <= max_calls

    check_study(study)

    storage.close()
