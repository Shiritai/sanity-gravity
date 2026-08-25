from unittest.mock import MagicMock

from sanity_gravity.core.orchestrator import Orchestrator
from sanity_gravity.effects.executor import Executor


def test_executor_context_manager():
    executor = Executor(runtime=MagicMock(), reporter=MagicMock())
    executor.close = MagicMock()
    with executor as ex:
        assert ex is executor
    executor.close.assert_called_once()

def test_orchestrator_context_manager():
    mock_executor = MagicMock()
    orch = Orchestrator(bus=MagicMock(), reporter=MagicMock(), executor=mock_executor)
    with orch as o:
        assert o is orch
    mock_executor.close.assert_called_once()
