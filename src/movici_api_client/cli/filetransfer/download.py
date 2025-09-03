from __future__ import annotations

import contextlib
import json
import pathlib
import shutil
import typing as t

from tqdm.auto import tqdm

from movici_api_client.api.common import Request
from movici_api_client.api.requests import (
    GetDatasetData,
    GetDatasets,
    GetProjects,
    GetScenarios,
    GetSingleScenario,
    GetSingleUpdate,
    GetUpdates,
    GetViews,
)
from movici_api_client.cli.data_dir import DataDir

from ..exceptions import InvalidFile
from ..utils import echo
from .common import FileTransferTask, ParallelTaskGroup, resolve_question_flag


class DownloadResource(FileTransferTask):
    EXTENSIONS = {
        "application/json": ".json",
        "application/msgpack": ".msgpack",
        "application/x-msgpack": ".msgpack",
        "application/netcdf": ".nc",
        "application/x-netcdf": ".nc",
        "text/csv": ".csv",
        "text/html": ".html",
        "text/plain": ".txt",
        "image/tiff": ".tif",
    }

    def __init__(
        self,
        file: pathlib.Path,
        request: Request,
        progress=True,
        continue_after_failed_overwrite=False,
    ) -> None:
        self.file = file
        self.request = request
        self.progress = progress
        self.continue_after_failed_overwrite = continue_after_failed_overwrite

    async def run(self):
        async with self.client.stream(self.request) as response:
            file = self.file_with_suffix(response)
            if not prepare_overwrite_file(file, self.params.overwrite):
                return self.continue_after_failed_overwrite
            fopen = open(file, "wb")
            if self.progress:
                context = tqdm.wrapattr(
                    fopen,
                    "write",
                    miniters=1,
                    desc=file.name,
                    total=self.infer_file_size(response),
                )
            else:
                context = contextlib.nullcontext(fopen)

            with context as fout:
                async for chunk in response.aiter_bytes(chunk_size=4096):
                    fout.write(chunk)
        return True

    def file_with_suffix(self, response):
        return self.file.with_suffix(
            self.EXTENSIONS.get(response.headers.get("content-type"), ".dat")
        )

    @staticmethod
    def infer_file_size(response):
        for header in ("content-length", "file-size"):
            if (result := response.headers.get(header)) is not None:
                return int(result)
        return 0


class RecursivelyDownloadResource(FileTransferTask):
    def __init__(
        self,
        parent: dict,
        directory: DataDir,
        progress=True,
    ) -> None:
        self.parent = parent
        self.directory = directory
        self.progress = progress

    async def run(self):
        async with self.client:
            all_resources = await self.client.request(self.request_all())

            for task in self.create_subtasks(all_resources):
                result = await task.run()
                if result is False:
                    return

    def request_all(self):
        raise NotImplementedError

    def create_subtasks(self, resources: t.List[dict]) -> t.Iterable[FileTransferTask]:
        raise NotImplementedError


class DownloadDatasets(RecursivelyDownloadResource):
    def request_all(self):
        return GetDatasets(self.parent["uuid"])

    def create_subtasks(self, resources: t.List[dict]) -> t.Iterable[t.Iterable[FileTransferTask]]:
        if self.directory.datasets is None:
            raise RuntimeError("Directory datasets path is not set")
        for ds in resources:
            if ds["has_data"]:
                yield [
                    DownloadResource(
                        file=self.directory.datasets.joinpath(ds["name"]),
                        request=GetDatasetData(ds["uuid"]),
                        progress=self.progress,
                        continue_after_failed_overwrite=True,
                    )
                ]


class DownloadScenarios(RecursivelyDownloadResource):
    def request_all(self):
        return GetScenarios(self.parent["uuid"])

    def create_subtasks(self, resources: t.List[dict]) -> t.Iterable[t.Iterable[FileTransferTask]]:
        yield [
            ParallelTaskGroup(
                (DownloadSingleScenario(parent=r, directory=self.directory) for r in resources),
                progress=False,
                description="Downloading scenarios",
            )
        ]


class DownloadSingleScenario(RecursivelyDownloadResource):
    def request_all(self):
        return GetUpdates(self.parent["uuid"])

    def create_subtasks(self, resources: t.List[dict]) -> t.Iterable[t.Iterable[FileTransferTask]]:
        if self.directory.scenarios is None:
            raise RuntimeError("Directory scenarios path is not set")
        name, uuid = self.parent["name"], self.parent["uuid"]
        yield [
            DownloadResource(
                file=self.directory.scenarios.joinpath(name),
                request=GetSingleScenario(uuid),
                progress=False,
            )
        ]
        if self.params.with_simulation:
            simulation_dir = self.directory.ensure_simulation_dir(name)
            yield [PrepareOverwriteDirectory(simulation_dir)]
            yield [
                ParallelTaskGroup(
                    (
                        DownloadResource(
                            file=simulation_dir.joinpath(
                                f"t{r['timestamp']}_{r['iteration']}_{r['name']}"
                            ),
                            request=GetSingleUpdate(r["uuid"]),
                            progress=False,
                        )
                        for r in resources
                    ),
                    progress=self.progress,
                    description=name,
                )
            ]
        if self.params.with_views:
            yield [
                DownloadViews(
                    scenario=self.parent,
                    directory=self.directory,
                )
            ]


class DownloadViews(FileTransferTask):
    def __init__(
        self,
        scenario: dict,
        directory: DataDir,
    ) -> None:
        self.scenario = scenario
        self.directory = directory

    async def run(self) -> t.Optional[bool]:
        async with self.client:
            views = await self.client.request(GetViews(self.scenario["uuid"]))
        directory = self.directory.ensure_views_dir(self.scenario["name"])
        if views:
            for view in views:
                self.store_view(view, directory=directory)
        return None

    def store_view(self, view: dict, directory: pathlib.Path):
        name = view["name"]
        file = directory.joinpath(name).with_suffix(".json")
        if not prepare_overwrite_file(file, self.params.overwrite):
            return
        file.write_text(json.dumps(view, indent=2))


class DownloadProject(RecursivelyDownloadResource):
    def request_all(self):
        return GetProjects()

    def create_subtasks(self, resources: t.List[dict]) -> t.Iterable[t.Iterable[FileTransferTask]]:
        yield [
            DownloadDatasets(
                parent=self.parent,
                directory=self.directory,
                progress=self.progress,
            )
        ]
        yield [
            DownloadScenarios(
                self.parent,
                directory=self.directory,
                progress=False,
            )
        ]


class PrepareOverwriteDirectory(FileTransferTask):
    def __init__(self, directory: pathlib.Path):
        self.directory = directory

    async def run(self):
        if not self.directory.exists():
            self.directory.mkdir(parents=True, exist_ok=True)

        try:
            is_empty_dir = not list(self.directory.iterdir())
        except NotADirectoryError:
            echo(f"{self.directory!s} is not a valid directory")
            return False

        if is_empty_dir:
            return True

        overwrite = resolve_question_flag(
            self.params.overwrite, f"Directory {self.directory!s} already existing, overwrite?"
        )
        if not overwrite:
            echo(f"Cowardly refusing to overwrite existing directory {self.directory!s}")
            return False
        shutil.rmtree(self.directory)
        self.directory.mkdir()
        return True


def prepare_overwrite_file(file: pathlib.Path, overwrite: t.Optional[bool] = None):
    if file.exists():
        overwrite = resolve_question_flag(
            overwrite, f"File {file.name!s} already exists, overwrite?"
        )
        if not file.is_file():
            raise InvalidFile(msg="not a file", file=file)
        if not overwrite:
            echo(f"Cowardly refusing to overwrite existing file {file.name}")
            return False
    if not (parent := file.parent).is_dir():
        if parent.exists():
            echo(f"{parent!s} is not a valid directory")
            return False
        parent.mkdir(parents=True, exist_ok=True)
    return True
