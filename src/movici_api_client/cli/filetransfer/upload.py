from __future__ import annotations

import contextlib
import pathlib
import re
import typing as t

from tqdm.auto import tqdm
from tqdm.utils import CallbackIOWrapper

from movici_api_client.api import IAsyncClient
from movici_api_client.api.requests import (
    AddDatasetData,
    CreateDataset,
    CreateScenario,
    CreateTimeline,
    CreateUpdate,
    CreateView,
    DeleteTimeline,
    GetDatasets,
    GetDatasetTypes,
    GetScenarios,
    GetSingleScenario,
    GetViews,
    ModifiyDatasetData,
    UpdateScenario,
    UpdateView,
)
from movici_api_client.cli.data_dir import DataDir, MoviciDataDir, ScenariosDirectory

from ..exceptions import InvalidFile, InvalidResource
from ..helpers import read_json_file
from ..utils import echo, prompt_choices_async, validate_uuid
from .common import FileTransferTask, ParallelTaskGroup, resolve_question_flag


class UploadResource(FileTransferTask):
    def __init__(
        self,
        file: pathlib.Path,
        parent_uuid: str,
        strategy: UploadStrategy,
        name_or_uuid: t.Optional[str] = None,
        all_resources: t.Optional[t.Sequence[dict]] = None,
    ) -> None:

        self.file = file
        self.parent_uuid = parent_uuid
        self.name_or_uuid = name_or_uuid
        self.all_resources = all_resources
        self.strategy = strategy

    async def run(self) -> t.Optional[bool]:
        async with self.client:
            name, existing = await self.get_existing()

            if not existing:
                if self.determine_create_new(self.params.create, name):
                    return await self.strategy.create_new(  # type: ignore[no-any-return]
                        self.parent_uuid,
                        file=self.file,
                        name=name,
                        inspect=self.params.inspect,
                    )

            if (
                existing
                and self.strategy.require_overwrite_question(existing)
                and not self.determine_overwrite(self.params.overwrite, name)
            ):
                return None

            if existing:
                return await self.strategy.update_existing(  # type: ignore[no-any-return]
                    existing, self.file, self.params.inspect
                )

            return None

    async def ensure_all_resources(self):
        if self.all_resources is None:
            self.all_resources = await self.strategy.get_all(self.parent_uuid)

    async def get_existing(self) -> t.Tuple[str, t.Optional[dict]]:
        await self.ensure_all_resources()
        name_or_uuid, all_resources = self.name_or_uuid, self.all_resources
        if not name_or_uuid:
            name_or_uuid = self.file.stem
        match_field = "uuid" if validate_uuid(name_or_uuid) else "name"
        if all_resources:
            for res in all_resources:
                if name_or_uuid == res[match_field]:
                    return res["name"], res
        if match_field == "uuid":
            InvalidResource("scenario", name_or_uuid)
        return name_or_uuid, None

    def determine_create_new(self, create_new, name):
        resource_type = self.strategy.resource_type
        do_create = resolve_question_flag(
            create_new,
            (
                f"{resource_type.capitalize()} {name} does not exist, "
                f"do you wish to create this {resource_type}?"
            ),
        )
        if not do_create:
            echo(f"Cowardly refusing to create new {resource_type} {name}")
        return do_create

    def determine_overwrite(self, overwrite, name):
        resource_type = self.strategy.resource_type

        do_overwrite = resolve_question_flag(
            overwrite,
            (
                f"{resource_type.capitalize()} {name} already has data, "
                "do you wish to overwrite?"
            ),
        )
        if not do_overwrite:
            echo(f"Cowardly refusing to overwrite data for {resource_type} '{name}'")
        return do_overwrite


class UploadMultipleResources(FileTransferTask):
    def __init__(
        self,
        directory: DataDir,
        parent_uuid: str,
        strategy: t.Optional[UploadStrategy] = None,
    ):
        self.directory = directory
        self.parent_uuid = parent_uuid
        self.strategy = strategy

    async def run(self) -> t.Optional[bool]:
        if self.strategy is None:
            return None
        if hasattr(self.strategy, "get_all"):
            try:
                all_resources = await self.strategy.get_all(
                    self.parent_uuid
                )  # type: ignore[call-arg]
            except TypeError:
                # Some strategies don't take parent_uuid parameter
                all_resources = await self.strategy.get_all()  # type: ignore[call-arg]
        else:
            all_resources = None
        async with self.client:
            for file in tqdm(
                list(self.strategy.iter_files(self.directory)),
                desc=f"Processing {self.strategy.resource_type} files",
            ):
                task = self.strategy.upload_task(  # type: ignore[call-arg]
                    file, self.parent_uuid, strategy=self.strategy, all_resources=all_resources
                )
                await task.run()
        return None


class UploadScenario(FileTransferTask):
    def __init__(
        self,
        file: pathlib.Path,
        parent_uuid: str,
        name_or_uuid=None,
        all_resources=None,
        strategy: t.Optional[UploadStrategy] = None,
    ):
        self.file = file
        self.parent_uuid = parent_uuid
        self.name_or_uuid = name_or_uuid
        self.all_resources = all_resources
        self.strategy = strategy or ScenarioUploadStrategy(self.client)

    async def run(self) -> t.Optional[bool]:
        uuid = await UploadResource(
            file=self.file,
            parent_uuid=self.parent_uuid,
            strategy=self.strategy,
            name_or_uuid=self.name_or_uuid,
            all_resources=self.all_resources,
        ).run()
        if uuid is None:
            return None
        if self.params.with_simulation:
            await self.upload_simulation(uuid)
        if self.params.with_views:
            await self.upload_views(uuid)
        return None

    async def upload_simulation(self, uuid):
        scenario_dir = ScenariosDirectory(self.file.parent)
        if not scenario_dir.scenarios.joinpath(self.file.stem).is_dir():
            echo(f"Scenario {self.file.name} does not have a valid simulation")
            return
        scenario = None
        if self.all_resources is not None:
            scenarios_by_uuid = {r["uuid"]: r for r in self.all_resources}
            scenario = scenarios_by_uuid.get(uuid)
        await UploadTimeline(
            self.client,
            scenario_dir,
            parent_uuid=uuid,
            scenario=scenario,
        )

    async def upload_views(self, uuid):
        movici_dir = MoviciDataDir.resolve_from_subpath(self.file)
        scenario_name = self.file.stem
        strategy = ViewUploadStrategy(self.client, scenario=scenario_name)
        await UploadMultipleResources(
            directory=movici_dir,
            parent_uuid=uuid,
            strategy=strategy,
        ).run()


class UploadTimeline(FileTransferTask):
    extensions = {".json"}

    def __init__(
        self,
        client: IAsyncClient,
        directory: DataDir,
        parent_uuid: str,
        scenario: t.Optional[dict] = None,
    ):
        self.client = client
        self.directory = directory
        self.parent_uuid = parent_uuid
        self.scenario = scenario

    async def run(self) -> t.Optional[bool]:
        async with self.client:
            scenario = await self.ensure_scenario()
            if scenario is None:
                return None
            await self.recreate_timeline(scenario)
            await ParallelTaskGroup(
                (
                    UploadUpdate(self.parent_uuid, file)
                    for file in self.directory.iter_updates(scenario["name"])
                ),
                progress=True,
                description=scenario["name"],
            ).run()
        return None

    async def recreate_timeline(self, scenario: dict):
        if scenario.get("has_timeline"):
            await self.client.request(DeleteTimeline(self.parent_uuid))
        await self.client.request(CreateTimeline(self.parent_uuid))

    async def ensure_scenario(self):
        self.scenario = self.scenario or await self.client.request(
            GetSingleScenario(self.parent_uuid)
        )
        return self.scenario


class UploadUpdate(FileTransferTask):
    def __init__(self, parent_uuid: str, file: pathlib.Path) -> None:
        self.parent_uuid = parent_uuid
        self.file = file

    async def run(self) -> t.Optional[bool]:
        try:
            payload = self.prepare_payload()
        except ValueError as e:
            echo(f"Error reading {self.file}: {e!s}", err=True)
            return None
        if payload is None:
            return None
        await self.client.request(CreateUpdate(self.parent_uuid, payload))
        return None

    def prepare_payload(self) -> t.Optional[dict]:
        try:
            contents = read_json_file(self.file)
        except InvalidFile:
            raise ValueError("Not a valid update file")

        if {"name", "timestamp", "iteration"} - contents.keys():
            match = re.match(
                r"t(?P<timestamp>\d+)_(?P<iteration>\d+)_(?P<dataset>\w+)\..*", self.file.name
            )
            if not match:
                raise ValueError("Could not determine required update info")

            filename_meta = match.groupdict()
            contents.update(filename_meta)
        if "data" not in contents:
            if contents["name"] not in contents:
                raise ValueError("Could not determine update data")
            contents["data"] = contents["name"]
        return contents


class UploadProject(FileTransferTask):
    def __init__(
        self,
        directory: DataDir,
        uuid: str,
        all_resources=None,
    ):
        self.directory = directory
        self.uuid = uuid
        self.all_resources = all_resources

    async def run(self) -> t.Optional[bool]:
        for strategy_kind in (DatasetUploadStrategy, ScenarioUploadStrategy):
            strategy = strategy_kind(self.client)
            await UploadMultipleResources(
                directory=self.directory,
                parent_uuid=self.uuid,
                strategy=strategy,
            ).run()
        return None


class UploadStrategy:
    extensions: t.Optional[t.Collection]
    messages: dict
    resource_type: str = "resource"
    upload_task: t.Type[FileTransferTask] = UploadResource

    def __init__(self, client: IAsyncClient):
        self.client = client

    def iter_files(self, directory: DataDir):
        raise NotImplementedError

    def require_overwrite_question(self, existing: dict):
        return True

    async def get_all(self):
        raise NotImplementedError

    async def create_new(self, parent_uuid: str, file: pathlib.Path, name=None, inspect=False):
        raise NotImplementedError

    async def update_existing(self, existing: dict, file: pathlib.Path, name=None, inspect=False):
        raise NotImplementedError


class DatasetUploadStrategy(UploadStrategy):
    extensions = {".json", ".msgpack", ".csv", ".nc", ".tiff", ".tif", ".geotif", ".geotif"}
    resource_type = "dataset"

    def __init__(self, client: IAsyncClient, all_dataset_types=None):
        super().__init__(client)
        self.all_dataset_types = all_dataset_types

    def iter_files(self, directory: DataDir):
        yield from directory.iter_datasets()

    async def get_all(self, parent_uuid: str):
        return await self.client.request(GetDatasets(project_uuid=parent_uuid))

    def require_overwrite_question(self, existing: t.Optional[dict]):
        if existing is None:
            return False
        return existing["has_data"]

    async def create_new(self, parent_uuid: str, file: pathlib.Path, name=None, inspect=False):
        name = name or file.stem
        await self.ensure_all_dataset_types()
        dataset_type = await self.infer_dataset_type(file, inspect=inspect)
        response = await self.client.request(
            CreateDataset(parent_uuid, name, type=dataset_type, display_name=name)
        )
        if response is None:
            raise RuntimeError("Failed to create dataset: received None response")
        uuid = response["dataset_uuid"]
        await self.upload_new_data(uuid, file)
        return uuid

    async def update_existing(self, existing: dict, file: pathlib.Path, inspect=False):
        uuid, has_data = existing["uuid"], existing["has_data"]

        if has_data:
            await self.upload_existing_data(uuid, file)
        else:
            await self.upload_new_data(uuid, file)
        return uuid

    async def ensure_all_dataset_types(self):
        if self.all_dataset_types is None:
            self.all_dataset_types = await self.client.request(GetDatasetTypes())

    async def infer_dataset_type(self, file: pathlib.Path, inspect):
        if file.suffix in (".csv"):
            return "parameters"
        if file.suffix in (".nc"):
            return "flooding_tape"
        if file.suffix in (".tiff", ".tif", ".geotif", ".geotif"):
            return "height_map"
        if inspect:
            if file.suffix == ".json":
                try:
                    return read_json_file(file)["type"]
                except (InvalidFile, KeyError):
                    pass
        if not self.all_dataset_types:
            echo(f"Could not determine dataset type for '{file.name}'")
            return
        return await prompt_choices_async(
            f"\nPlease specify the type for dataset '{file.name}'", self.all_dataset_types
        )

    async def upload_new_data(self, uuid, file):
        with read_file_progress_bar(file) as fobj:
            return await self.client.request(AddDatasetData(uuid, fobj))

    async def upload_existing_data(self, uuid, file):
        with read_file_progress_bar(file) as fobj:
            return await self.client.request(ModifiyDatasetData(uuid, fobj))


class ScenarioUploadStrategy(UploadStrategy):
    resource_type = "scenario"
    extensions = {".json"}
    upload_task = UploadScenario

    async def get_all(self, parent_uuid: str):
        return await self.client.request(GetScenarios(project_uuid=parent_uuid))

    def iter_files(self, directory: DataDir):
        yield from directory.iter_scenarios()

    async def create_new(self, parent_uuid: str, file: pathlib.Path, name=None, inspect=False):
        payload = self._prepare_payload(name or file.stem, file, inspect)
        response = await self.client.request(CreateScenario(parent_uuid, payload))
        if response is None:
            raise RuntimeError("Failed to create scenario: received None response")
        return response["scenario_uuid"]

    async def update_existing(self, existing: dict, file: pathlib.Path, name=None, inspect=False):
        payload = self._prepare_payload(name or file.stem, file, inspect)
        await self.client.request(UpdateScenario(existing["uuid"], payload))
        return existing["uuid"]

    def _prepare_payload(self, name, file, inspect):
        payload = read_json_file(file)
        if inspect:
            payload["name"] = name
        return payload


class ViewUploadStrategy(UploadStrategy):
    resource_type = "view"
    extensions = {".json"}

    def __init__(self, client: IAsyncClient, scenario: t.Optional[str] = None):
        super().__init__(client)
        self.scenario = scenario

    async def get_all(self, parent_uuid: str):
        return await self.client.request(GetViews(parent_uuid))

    def iter_files(self, directory: DataDir):
        if self.scenario is None:
            raise ValueError(
                f"{type(self).__name__}.scenario is required to iterate over view-files"
            )
        yield from directory.iter_views(self.scenario)

    async def create_new(self, parent_uuid: str, file: pathlib.Path, name=None, inspect=False):
        payload = self._prepare_payload(name or file.stem, file, inspect)
        response = await self.client.request(CreateView(parent_uuid, payload))
        if response is None:
            raise RuntimeError("Failed to create view: received None response")
        return response["view_uuid"]

    async def update_existing(self, existing: dict, file: pathlib.Path, name=None, inspect=False):
        payload = self._prepare_payload(name or file.stem, file, inspect)
        await self.client.request(UpdateView(existing["uuid"], payload))
        return existing["uuid"]

    def _prepare_payload(self, name, file, inspect):
        payload = read_json_file(file)
        if inspect:
            payload["name"] = name
        return payload


@contextlib.contextmanager
def read_file_progress_bar(file: pathlib.Path):
    with open(file, "rb") as fobj, tqdm(
        total=file.stat().st_size, unit="B", unit_scale=True, unit_divisor=1024, desc=file.name
    ) as t:
        yield CallbackIOWrapper(t.update, fobj, "read")
        t.reset()
