from unittest.mock import AsyncMock

import pytest

from movici_api_client.cli.filetransfer.common import (
    FileTransferTask,
    ParallelTaskGroup,
    SequentialTaskGroup,
)


class FakeTask(FileTransferTask, AsyncMock):
    async def run(self):
        await self()


def mock_task():
    return FakeTask()


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [SequentialTaskGroup, ParallelTaskGroup])
async def test_task_group_runs_all_tasks(group):
    mock_1 = mock_task()
    mock_2 = mock_task()
    await group([mock_1, mock_2]).run()
    assert mock_1.await_count == 1
    assert mock_2.await_count == 1


@pytest.mark.asyncio
async def test_parallel_task_group_finishes_up_on_error():
    mock_1 = mock_task()
    mock_2 = mock_task()
    mock_2.side_effect = RuntimeError()
    with pytest.raises(RuntimeError):
        await ParallelTaskGroup([mock_1, mock_2]).run()

    assert mock_1.await_count == 1
    assert mock_2.await_count == 1
