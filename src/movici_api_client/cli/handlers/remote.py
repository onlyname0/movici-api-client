import asyncio
import typing as t

from movici_api_client.api import requests as req
from movici_api_client.api.client import AsyncClient

from .. import filetransfer as ft
from ..common import CLIParameters
from ..cqrs import Event, EventHandler, Mediator
from ..events.authorization import CreateScope, DeleteScope, GetScopes
from ..events.dataset import (
    ClearDataset,
    CreateDataset,
    DeleteDataset,
    DownloadDataset,
    DownloadMultipleDatasets,
    EditDataset,
    GetAllDatasets,
    GetDatasetTypes,
    GetSingleDataset,
    UpdateDataset,
    UploadDataset,
    UploadMultipleDatasets,
)
from ..events.project import (
    CreateProject,
    DeleteProject,
    DownloadProject,
    GetAllProjects,
    GetSingleProject,
    UpdateProject,
    UploadProject,
)
from ..events.scenario import (
    ClearScenario,
    CreateScenario,
    DeleteScenario,
    DownloadMultipleScenarios,
    DownloadScenario,
    EditScenario,
    GetAllScenarios,
    GetSingleScenario,
    RunSimulation,
    UploadMultipleScenarios,
    UploadScenario,
)
from ..exceptions import InvalidActiveProject, InvalidResource, NoActiveProject, NoChangeDetected
from ..filetransfer.common import resolve_question_flag
from ..handlers.common import gather_safe
from ..handlers.query import DatasetQuery, ProjectQuery, ScenarioQuery, ScopeQuery
from ..helpers import edit_resource
from ..utils import assert_current_context, confirm, echo, prompt_choices_async


def requires_valid_project_uuid(cls: t.Type[EventHandler]):
    original = cls.handle

    async def handle(self, event: Event, mediator: Mediator):
        project_uuid = await _valid_project_uuid_from_context(mediator)
        self.project_uuid = project_uuid
        return await original(self, event, mediator)

    cls.handle = handle  # type: ignore[method-assign]
    return cls


async def _valid_project_uuid_from_context(mediator: Mediator):
    context = assert_current_context()
    proj_name = context.get("project")
    if not proj_name:
        raise NoActiveProject()
    projects = await mediator.send(GetAllProjects())
    projects_dict = {p["name"]: p["uuid"] for p in projects}
    try:
        return projects_dict[proj_name]
    except KeyError:
        raise InvalidActiveProject(proj_name)


class RemoteEventHandler(EventHandler):
    def __init__(self, client: AsyncClient, params: CLIParameters) -> None:
        self.client = client
        self.params = params


class RemoteGetAllProjectsHandler(RemoteEventHandler):
    __event__ = GetAllProjects

    async def handle(self, event: GetAllProjects, mediator: Mediator):
        return await self.client.request(req.GetProjects())


class RemoteGetSingleProjectHandler(RemoteEventHandler):
    __event__ = GetSingleProject

    async def handle(self, event: GetSingleProject, mediator: Mediator):
        uuid = await ProjectQuery().get_uuid(event.name_or_uuid)
        return await self.client.request(req.GetSingleProject(uuid))


class RemoteCreateProjectHandler(RemoteEventHandler):
    __event__ = CreateProject

    async def handle(self, event: CreateProject, mediator: Mediator):
        result, *_ = await gather_safe(
            self.client.request(
                req.CreateProject(name=event.name, display_name=event.display_name)
            ),
            mediator.send(CreateScope(f"project:{event.name}")),
        )
        return result


class RemoteUpdateProjectHandler(RemoteEventHandler):
    __event__ = UpdateProject

    async def handle(self, event: UpdateProject, mediator: Mediator):
        async with self.client:
            uuid = await ProjectQuery().get_uuid(event.name_or_uuid)
            if not event.display_name:
                raise NoChangeDetected()
            return await self.client.request(
                req.UpdateProject(uuid, display_name=event.display_name)
            )


class RemoteDeleteProjectHandler(RemoteEventHandler):
    __event__ = DeleteProject

    async def handle(self, event: DeleteProject, mediator: Mediator):
        async with self.client:
            project = await ProjectQuery().by_name_or_uuid(event.name_or_uuid)

            confirm(
                f"Are you sure you wish to delete project '{event.name_or_uuid}' "
                "with all its associated data?"
            )
            result = await self.client.request(req.DeleteProject(project["uuid"]))
            try:
                scope_uuid = await ScopeQuery().get_uuid(f"project:{project['name']}")
            except InvalidResource:
                pass
            else:
                await self.client.request(
                    req.DeleteScope(scope_uuid), on_error=lambda r: r.status_code != 404
                )

            return result


@requires_valid_project_uuid
class RemoteUploadProjectHandler(RemoteEventHandler):
    __event__ = UploadProject
    project_uuid: str

    async def handle(self, event: UploadProject, mediator: Mediator):
        self.params.with_simulation = True
        self.params.with_views = True
        return await ft.UploadProject(event.directory, uuid=self.project_uuid)


@requires_valid_project_uuid
class RemoteDownloadProjectHandler(RemoteEventHandler):
    __event__ = DownloadProject
    project_uuid: str

    async def handle(self, event: DownloadProject, mediator: Mediator):
        event.directory.initialize()
        self.params.with_simulation = True
        self.params.with_views = True
        return await ft.DownloadProject(
            parent={"uuid": self.project_uuid}, directory=event.directory
        )


class RemoteGetDatasetTypesHandler(RemoteEventHandler):
    __event__ = GetDatasetTypes

    async def handle(self, event: GetDatasetTypes, mediator: Mediator):
        return await self.client.request(req.GetDatasetTypes())


@requires_valid_project_uuid
class RemoteGetAllDatasetsHandler(RemoteEventHandler):
    __event__ = GetAllDatasets
    project_uuid: str

    async def handle(self, event: GetAllDatasets, mediator: Mediator):
        return await self.client.request(req.GetDatasets(project_uuid=self.project_uuid))


@requires_valid_project_uuid
class RemoteGetSingleDatasetHandler(RemoteEventHandler):
    __event__ = GetSingleDataset
    project_uuid: str

    async def handle(self, event: GetSingleDataset, mediator: Mediator):
        uuid = await DatasetQuery(self.project_uuid).get_uuid(event.name_or_uuid)
        return await self.client.request(req.GetSingleDataset(uuid))


@requires_valid_project_uuid
class RemoteCreateDatasetHandler(RemoteEventHandler):
    __event__ = CreateDataset
    project_uuid: str

    async def handle(self, event: CreateDataset, mediator: Mediator):
        async with self.client:
            if event.type is None:
                all_types = await mediator.send(GetDatasetTypes())
                event.type = await prompt_choices_async(
                    "Type", sorted([tp["name"] for tp in all_types])
                )
            return await self.client.request(
                req.CreateDataset(
                    project_uuid=self.project_uuid,
                    name=event.name,
                    type=event.type,
                    display_name=event.display_name,
                )
            )


@requires_valid_project_uuid
class RemoteUpdateDatasetHandler(RemoteEventHandler):
    __event__ = UpdateDataset
    project_uuid: str

    async def handle(self, event: UpdateDataset, mediator: Mediator):
        async with self.client:
            uuid = await DatasetQuery(self.project_uuid).get_uuid(event.name_or_uuid)
            if not any((event.name, event.type, event.display_name)):
                raise NoChangeDetected()
            return await self.client.request(
                req.UpdateDataset(
                    uuid, name=event.name, type=event.type, display_name=event.display_name
                )
            )


@requires_valid_project_uuid
class RemoteDeleteDatasetHandler(RemoteEventHandler):
    __event__ = DeleteDataset
    project_uuid: str

    async def handle(self, event: DeleteDataset, mediator: Mediator):
        async with self.client:
            uuid = await DatasetQuery(self.project_uuid).get_uuid(event.name_or_uuid)

            confirm(
                f"Are you sure you wish to delete dataset '{event.name_or_uuid}' and all its data?"
            )
            return await self.client.request(req.DeleteDataset(uuid))


@requires_valid_project_uuid
class RemoteClearDatasetHandler(RemoteEventHandler):
    __event__ = ClearDataset
    project_uuid: str

    async def handle(self, event: ClearDataset, mediator: Mediator):
        async with self.client:
            uuid = await DatasetQuery(self.project_uuid).get_uuid(event.name_or_uuid)

            confirm(
                f"Are you sure you wish to clear dataset '{event.name_or_uuid}' of all its data?"
            )
            return await self.client.request(req.DeleteDatasetData(uuid))


@requires_valid_project_uuid
class RemoteUploadDatasetHandler(RemoteEventHandler):
    __event__ = UploadDataset
    project_uuid: str

    async def handle(self, event: UploadDataset, mediator: Mediator):
        return await ft.UploadResource(
            file=event.file,
            parent_uuid=self.project_uuid,
            strategy=ft.DatasetUploadStrategy(self.client),
            name_or_uuid=event.name_or_uuid,
        )


@requires_valid_project_uuid
class RemoteUploadMultipleDatasetsHandler(RemoteEventHandler):
    __event__ = UploadMultipleDatasets
    project_uuid: str

    async def handle(self, event: UploadMultipleDatasets, mediator: Mediator):
        return await ft.UploadMultipleResources(
            event.directory,
            self.project_uuid,
            strategy=ft.DatasetUploadStrategy(client=self.client),
        )


@requires_valid_project_uuid
class RemoteDownloadDatasetHandler(RemoteEventHandler):
    __event__ = DownloadDataset
    project_uuid: str

    async def handle(self, event: DownloadDataset, mediator: Mediator):
        dataset = await DatasetQuery(self.project_uuid).by_name_or_uuid(event.name_or_uuid)
        if event.directory.datasets is None:
            raise RuntimeError("Directory datasets path is not set")
        file = event.directory.datasets.joinpath(dataset["name"])
        return await ft.DownloadResource(
            file=file,
            request=req.GetDatasetData(dataset["uuid"]),
        )


@requires_valid_project_uuid
class RemoteDownloadMultipleDatasets(RemoteEventHandler):
    __event__ = DownloadMultipleDatasets
    project_uuid: str

    async def handle(self, event: DownloadMultipleDatasets, mediator: Mediator):
        await ft.DownloadDatasets(
            {"uuid": self.project_uuid},
            directory=event.directory,
        )


@requires_valid_project_uuid
class RemoteEditDataset(RemoteEventHandler):
    __event__ = EditDataset
    project_uuid: str

    async def handle(self, event: EditDataset, mediator: Mediator):
        current = await mediator.send(GetSingleDataset(event.name_or_uuid))
        uuid = current["uuid"]
        result = edit_resource(current)
        await self.client.request(req.UpdateDataset(uuid, payload=result))


@requires_valid_project_uuid
class RemoteGetAllScenariosHandler(RemoteEventHandler):
    __event__ = GetAllScenarios
    project_uuid: str

    async def handle(self, event: GetAllScenarios, mediator: Mediator):
        return await self.client.request(req.GetScenarios(project_uuid=self.project_uuid))


@requires_valid_project_uuid
class RemoteGetSingleScenarioHandler(RemoteEventHandler):
    __event__ = GetSingleScenario
    project_uuid: str

    async def handle(self, event: GetSingleScenario, mediator: Mediator):
        uuid = await ScenarioQuery(self.project_uuid).get_uuid(event.name_or_uuid)
        return await self.client.request(req.GetSingleScenario(uuid))


@requires_valid_project_uuid
class RemoteCreateScenarioHandler(RemoteEventHandler):
    __event__ = CreateScenario
    project_uuid: str

    async def handle(self, event: CreateScenario, mediator: Mediator):
        return await self.client.request(req.CreateScenario(self.project_uuid, event.payload))


@requires_valid_project_uuid
class RemoteDeleteScenarioHandler(RemoteEventHandler):
    __event__ = DeleteScenario
    project_uuid: str

    async def handle(self, event: DeleteScenario, mediator: Mediator):
        async with self.client:
            uuid = await ScenarioQuery(self.project_uuid).get_uuid(event.name_or_uuid)

            confirm(
                f"Are you sure you wish to delete scenario '{event.name_or_uuid}' "
                "and all its data?"
            )
            return await self.client.request(req.DeleteScenario(uuid))


@requires_valid_project_uuid
class RemoteClearScenarioHandler(RemoteEventHandler):
    __event__ = ClearScenario
    project_uuid: str

    async def handle(self, event: ClearScenario, mediator: Mediator):
        def on_error(resp):
            return resp.status_code != 404

        async with self.client:
            uuid = await ScenarioQuery(self.project_uuid).get_uuid(event.name_or_uuid)

            if event.confirm:
                confirm(
                    f"Are you sure you wish to clear scenario '{event.name_or_uuid}' "
                    "of its simulation results?"
                )

            await asyncio.gather(
                self.client.request(req.DeleteTimeline(uuid), on_error=on_error),
                self.client.request(req.DeleteSimulation(uuid), on_error=on_error),
                wait_until_simulation_is_reset(self.client, uuid),
            )


@requires_valid_project_uuid
class RemoteRunSimulationHandler(RemoteEventHandler):
    __event__ = RunSimulation
    project_uuid: str

    async def handle(self, event: RunSimulation, mediator: Mediator):
        async with self.client:
            scenario = await ScenarioQuery(self.project_uuid).by_name_or_uuid(event.name_or_uuid)
            uuid, has_timeline = scenario["uuid"], scenario["has_timeline"]
            if has_timeline:
                do_overwrite = resolve_question_flag(
                    self.params.overwrite,
                    (
                        f"Scenario {event.name_or_uuid} already has simulation results, "
                        "do you wish to overwrite?"
                    ),
                )
                if not do_overwrite:
                    echo(
                        "Cowardly refusing to overwrite simulation results for "
                        f"'{event.name_or_uuid}'"
                    )
                    return
                await mediator.send(ClearScenario(event.name_or_uuid, confirm=False))

            await self.client.request(req.RunSimulation(uuid))


async def wait_until_simulation_is_reset(client: AsyncClient, uuid, interval=1):
    has_simulation = True

    def on_error(resp):
        nonlocal has_simulation
        if resp.status_code == 404:
            has_simulation = False
            return False

    while has_simulation:
        await client.request(req.GetSimulation(uuid), on_error=on_error)
        await asyncio.sleep(interval)


@requires_valid_project_uuid
class RemoteUploadScenarioHandler(RemoteEventHandler):
    __event__ = UploadScenario
    project_uuid: str

    async def handle(self, event: UploadScenario, mediator: Mediator):
        return await ft.UploadScenario(
            file=event.file,
            parent_uuid=self.project_uuid,
            name_or_uuid=event.name_or_uuid,
        )


@requires_valid_project_uuid
class RemoteUploadMultipleScenariosHandler(RemoteEventHandler):
    __event__ = UploadMultipleScenarios
    project_uuid: str

    async def handle(self, event: UploadMultipleScenarios, mediator: Mediator):
        return await ft.UploadMultipleResources(
            event.directory,
            self.project_uuid,
            strategy=ft.ScenarioUploadStrategy(client=self.client),
        )


@requires_valid_project_uuid
class RemoteDownloadScenarioHandler(RemoteEventHandler):
    __event__ = DownloadScenario
    project_uuid: str

    async def handle(self, event: DownloadScenario, mediator: Mediator):
        scenario = await ScenarioQuery(self.project_uuid).by_name_or_uuid(event.name_or_uuid)
        return await ft.DownloadSingleScenario(
            parent=scenario,
            directory=event.directory,
        )


@requires_valid_project_uuid
class RemoteDownloadMultipleScenariosHandler(RemoteEventHandler):
    __event__ = DownloadMultipleScenarios
    project_uuid: str

    async def handle(self, event: DownloadMultipleScenarios, mediator: Mediator):
        await ft.DownloadScenarios(
            {"uuid": self.project_uuid}, directory=event.directory, progress=False
        )


@requires_valid_project_uuid
class RemoteEditScenarioHandler(RemoteEventHandler):
    __event__ = EditScenario
    project_uuid: str

    async def handle(self, event: EditScenario, mediator: Mediator):
        current = await mediator.send(GetSingleScenario(event.name_or_uuid))
        uuid = current["uuid"]
        result = edit_resource(current)
        await self.client.request(req.UpdateScenario(uuid, payload=result))


class RemoteGetScopesHandler(RemoteEventHandler):
    __event__ = GetScopes

    async def handle(self, event: GetScopes, mediator: Mediator):
        return await self.client.request(req.GetScopes())


class RemoteCreateScopeHandler(RemoteEventHandler):
    __event__ = CreateScope

    async def handle(self, event: CreateScope, mediator: Mediator):
        return await self.client.request(req.CreateScope(event.name))


class RemoteDeleteScopeHandler(RemoteEventHandler):
    __event__ = DeleteScope

    async def handle(self, event: DeleteScope, mediator: Mediator):
        uuid = await ScopeQuery().get_uuid(event.name_or_uuid)

        if event.confirm:
            confirm(f"Are you sure you wish to delete scope '{event.name_or_uuid}'")
        return await self.client.request(req.DeleteScope(uuid))


ALL_HANDLERS = {
    obj.__event__: obj
    for obj in globals().values()
    if isinstance(obj, type) and obj is not EventHandler and issubclass(obj, EventHandler)
}
