"""Deterministic subprocess cleanup ordering without launching a process."""
import subprocess
from unittest.mock import Mock

import pytest

from Middleware.utilities import process_utils


@pytest.mark.parametrize('failure', ['wait', 'construct', 'start', 'timeout', 'normal'])
def test_process_cleanup_orders_stop_reap_join_close(monkeypatch, failure):
    events = []
    process = Mock()
    process.stdout.close.side_effect = lambda: events.append('stdout-close')
    process.stderr.close.side_effect = lambda: events.append('stderr-close')
    process.kill.side_effect = lambda: events.append('kill')

    def wait(timeout=None):
        events.append('wait')
        if events.count('wait') == 1 and failure == 'wait':
            raise GeneratorExit()
        if events.count('wait') == 1 and failure == 'timeout':
            raise subprocess.TimeoutExpired('synthetic', timeout)

    process.wait.side_effect = wait
    created = []

    class Reader:
        ident = None

        def __init__(self, **kwargs):
            if created and failure == 'construct':
                raise RuntimeError('synthetic construction failure')
            created.append(self)

        def start(self):
            if len(created) == 2 and failure == 'start':
                raise RuntimeError('synthetic startup failure')
            self.ident = len(created)
            events.append('start')

        def join(self, timeout=None):
            assert timeout is not None
            assert failure == 'normal' or 'kill' in events
            assert 'wait' in events
            events.append('join')

    monkeypatch.setattr(process_utils.threading, 'Thread', Reader)
    readers = [(Mock(), ()), (Mock(), ())]
    if failure in ('wait', 'construct', 'start'):
        with pytest.raises(GeneratorExit if failure == 'wait' else RuntimeError):
            process_utils.run_process_readers(process, 30, readers)
    else:
        assert process_utils.run_process_readers(process, 30, readers) is (failure == 'timeout')
    assert events[-2:] == ['stdout-close', 'stderr-close']
    if failure == 'normal':
        process.kill.assert_not_called()
    else:
        process.kill.assert_called_once()
    assert events.count('join') == sum(t.ident is not None for t in created)
