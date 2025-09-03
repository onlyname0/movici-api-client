import asyncio
import typing as t

import gimme
from tqdm.auto import tqdm

from movici_api_client.api.common import IAsyncClient
from movici_api_client.cli.common import CLIParameters

from ..utils import confirm


class FileTransferTask:
    client: IAsyncClient = gimme.attribute(IAsyncClient)
    params: CLIParameters = gimme.attribute(CLIParameters)

    async def run(self) -> t.Optional[bool]:
        raise NotImplementedError

    def create_task(self):
        return asyncio.create_task(self.run())

    def __await__(self):
        return self.run().__await__()


class SequentialTaskGroup(FileTransferTask):
    def __init__(
        self, tasks: t.Sequence[FileTransferTask], progress=False, description=None
    ) -> None:
        self.tasks = tasks
        self.progress = progress
        self.description = description

    async def run(self) -> t.Optional[bool]:
        result: t.Optional[bool] = None
        if self.progress:
            tasks = tqdm(self.tasks, desc=self.description)
            for task in tasks:
                result = await task.run()
                if result is False:
                    break
            if result is False:
                tasks.reset()
        else:
            for task in self.tasks:
                result = await task.run()
                if result is False:
                    break
        return result


class ParallelTaskGroup(FileTransferTask):
    def __init__(
        self, tasks: t.Iterable[FileTransferTask], progress=False, description=None
    ) -> None:
        self.tasks = tasks
        self.progress = progress
        self.description = description

    async def run(self) -> t.Optional[bool]:
        tasks = [task.create_task() for task in self.tasks]
        coros = asyncio.as_completed(tasks)

        if self.progress:
            coros = tqdm(coros, total=len(tasks), desc=self.description)
        try:
            for coro in coros:
                await coro
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        return None


def resolve_question_flag(flag, confirm_message):
    result = flag
    if flag is None:
        result = confirm(confirm_message)
    return result
