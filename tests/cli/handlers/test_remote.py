import uuid
from unittest.mock import AsyncMock, call, patch

import pytest

import movici_api_client.cli.handlers.remote
from movici_api_client.api import requests as req
from movici_api_client.cli import filetransfer
from movici_api_client.cli.common import CLIParameters
from movici_api_client.cli.config import Context
from movici_api_client.cli.cqrs import Event, EventHandler, Mediator
from movici_api_client.cli.data_dir import MoviciDataDir
from movici_api_client.cli.events.authorization import CreateScope, DeleteScope, GetScopes
from movici_api_client.cli.events.dataset import (
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
from movici_api_client.cli.events.project import (
    CreateProject,
    DeleteProject,
    DownloadProject,
    GetAllProjects,
    GetSingleProject,
    UpdateProject,
    UploadProject,
)
from movici_api_client.cli.events.scenario import (
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
from movici_api_client.cli.exceptions import NoChangeDetected
from movici_api_client.cli.handlers.remote import (
    ALL_HANDLERS,
    RemoteCreateProjectHandler,
    RemoteDeleteProjectHandler,
    RemoteDownloadProjectHandler,
    RemoteGetAllProjectsHandler,
    RemoteGetSingleProjectHandler,
    RemoteRunSimulationHandler,
    RemoteUpdateProjectHandler,
    RemoteUploadProjectHandler,
    requires_valid_project_uuid,
)
from movici_api_client.cli.testing import FakeAsyncClient

uuid1 = str(uuid.UUID(int=1))
project_uuid = str(uuid.UUID(int=2))


@pytest.fixture
def current_context():
    with patch.object(movici_api_client.cli.handlers.remote, "assert_current_context") as mock:
        mock.return_value = Context("dummy", url="", project="some_project")
        yield mock


@pytest.fixture(autouse=True)
def valid_project_uuid(request):
    if "no_valid_project_uuid" in request.keywords:
        yield
        return

    with patch.object(
        movici_api_client.cli.handlers.remote,
        "_valid_project_uuid_from_context",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = project_uuid
        yield project_uuid


@pytest.fixture(autouse=True)
def patch_confirm():
    with patch.object(movici_api_client.cli.handlers.remote, "confirm") as mock:
        yield mock


@pytest.fixture
def client():
    return FakeAsyncClient()


@pytest.fixture
def cli_params():
    return CLIParameters()


@pytest.fixture(autouse=True)
def setup_gimme(gimme_repo, client, cli_params):
    gimme_repo.add(client)
    gimme_repo.add(cli_params)


@pytest.fixture
def mediator():
    return Mediator(ALL_HANDLERS)


@pytest.fixture
def data_dir(tmp_path):
    rv = MoviciDataDir(tmp_path)
    rv.initialize()
    return rv


@pytest.mark.asyncio
@pytest.mark.no_valid_project_uuid
async def test_requires_valid_project_uuid(current_context):
    class DummyGetAllProjectsHandler(EventHandler):
        async def handle(self, event: Event, mediator: Mediator):
            return [{"name": "some_project", "uuid": "0000-0001"}]

    mediator = Mediator({GetAllProjects: DummyGetAllProjectsHandler})

    @requires_valid_project_uuid
    class MyHandler(EventHandler):
        project_uuid: str

        async def handle(self, event: Event, mediator: Mediator):
            pass

    handler = MyHandler()

    await handler.handle(object(), mediator)
    assert handler.project_uuid == "0000-0001"


@pytest.mark.asyncio
async def test_remote_get_all_projects_handler(gimme_repo, mediator, client):
    proj = {"uuid": "0000-0000", "name": "some_project"}
    client.add_response([proj])
    result = await gimme_repo.get(RemoteGetAllProjectsHandler).handle(GetAllProjects(), mediator)
    assert client.request.await_args == call(req.GetProjects())
    assert result == [proj]


@pytest.mark.asyncio
async def test_remote_get_single_project_handler(gimme_repo, mediator, client):
    proj = {"uuid": "0000-0000", "name": "some_project"}
    client.add_response([proj])
    client.add_response(proj)
    result = await gimme_repo.get(RemoteGetSingleProjectHandler).handle(
        GetSingleProject(name_or_uuid="some_project"), mediator
    )
    assert client.request.await_args_list == [
        call(req.GetProjects()),
        call(req.GetSingleProject(uuid="0000-0000")),
    ]
    assert result == proj


@pytest.mark.asyncio
async def test_remote_create_project_handler(gimme_repo, mediator, client):
    expected = {"result": "ok"}
    client.add_response(expected)
    result = await gimme_repo.get(RemoteCreateProjectHandler).handle(
        CreateProject(name="some_project", display_name="Some Project"), mediator
    )
    assert client.request.await_args_list == [
        call(req.CreateProject(name="some_project", display_name="Some Project")),
        call(req.CreateScope(name="project:some_project")),
    ]
    assert result == expected


@pytest.mark.asyncio
async def test_remote_update_project_handler(gimme_repo, mediator, client):
    proj = {"uuid": "0000-0000", "name": "some_project"}
    client.add_response([proj])
    await gimme_repo.get(RemoteUpdateProjectHandler).handle(
        UpdateProject(name_or_uuid="some_project", display_name="New Project"), mediator
    )
    assert client.request.await_args_list == [
        call(req.GetProjects()),
        call(req.UpdateProject(uuid="0000-0000", display_name="New Project")),
    ]


@pytest.mark.asyncio
async def test_remote_update_project_handler_raises_on_no_change(gimme_repo, mediator, client):
    proj = {"uuid": "0000-0000", "name": "some_project"}
    client.add_response([proj])

    with pytest.raises(NoChangeDetected):
        await gimme_repo.get(RemoteUpdateProjectHandler).handle(
            UpdateProject(name_or_uuid="some_project", display_name=None), mediator
        )


@pytest.mark.asyncio
async def test_remote_delete_project_handler(gimme_repo, mediator, client):
    proj = {"uuid": "0000-0000", "name": "some_project"}
    client.add_response([proj])
    client.add_response(None)
    client.add_response([{"uuid": "0000-0001", "name": "project:some_project"}])

    with patch.object(movici_api_client.cli.handlers.remote, "confirm"):
        await gimme_repo.get(RemoteDeleteProjectHandler).handle(
            DeleteProject(name_or_uuid="some_project"), mediator
        )
    assert [r[0][0] for r in client.request.await_args_list] == [
        req.GetProjects(),
        req.DeleteProject(uuid="0000-0000"),
        req.GetScopes(),
        req.DeleteScope(uuid="0000-0001"),
    ]


@pytest.mark.asyncio
async def test_remote_upload_project_handler(
    gimme_repo, mediator, cli_params, data_dir, valid_project_uuid
):
    with patch.object(filetransfer, "UploadProject", new_callable=AsyncMock) as mock:
        await gimme_repo.get(RemoteUploadProjectHandler).handle(
            UploadProject(directory=data_dir), mediator
        )
    assert mock.await_args == call(data_dir, uuid=valid_project_uuid)
    assert cli_params.with_simulation and cli_params.with_views


@pytest.mark.asyncio
async def test_remote_download_project_handler(
    gimme_repo, mediator, cli_params, data_dir, valid_project_uuid
):
    with patch.object(filetransfer, "DownloadProject", new_callable=AsyncMock) as mock:
        await gimme_repo.get(RemoteDownloadProjectHandler).handle(
            DownloadProject(directory=data_dir), mediator
        )
    assert mock.await_args == call(parent={"uuid": valid_project_uuid}, directory=data_dir)

    assert cli_params.with_simulation and cli_params.with_views


def simple_events():
    yield GetDatasetTypes(), req.GetDatasetTypes()
    yield GetAllDatasets(), req.GetDatasets(project_uuid)
    yield GetSingleDataset(uuid1), req.GetSingleDataset(uuid1)

    event = CreateDataset(name="some_dataset", display_name="Some Dataset", type="some_type")
    yield (
        event,
        req.CreateDataset(
            project_uuid=project_uuid,
            name=event.name,
            display_name=event.display_name,
            type=event.type,
        ),
    )
    event = UpdateDataset(
        name_or_uuid=uuid1, name="new_name", display_name="Some Dataset", type="some_type"
    )
    yield (
        event,
        req.UpdateDataset(
            uuid1, name=event.name, type=event.type, display_name=event.display_name
        ),
    )
    yield ClearDataset(uuid1), req.DeleteDatasetData(uuid1)
    yield GetAllScenarios(), req.GetScenarios(project_uuid)
    yield GetSingleScenario(uuid1), req.GetSingleScenario(uuid1)
    payload = {"some": "payload"}
    yield CreateScenario(payload=payload), req.CreateScenario(project_uuid, payload)
    yield GetScopes(), req.GetScopes()
    yield CreateScope("some_scope"), req.CreateScope("some_scope")
    yield DeleteScope(uuid1, confirm=False), req.DeleteScope(uuid1)


def simple_confirmed_events():
    yield DeleteDataset(uuid1), req.DeleteDataset(uuid1)
    yield DeleteScenario(uuid1), req.DeleteScenario(uuid1)
    yield DeleteScope(uuid1, confirm=True), req.DeleteScope(uuid1)


@pytest.mark.parametrize("event, expected", simple_events())
@pytest.mark.asyncio
async def test_remote_simple_events(event, expected, mediator, client):
    await mediator.send(event)
    assert client.request.await_args == call(expected)


@pytest.mark.parametrize("event, expected", simple_confirmed_events())
@pytest.mark.asyncio
async def test_remote_simple_confirmed_events(event, expected, mediator, client, patch_confirm):
    await mediator.send(event)
    assert client.request.await_args == call(expected)
    assert patch_confirm.call_count == 1


@pytest.mark.parametrize(
    "event_cls, request_cls",
    [(EditDataset, req.UpdateDataset), (EditScenario, req.UpdateScenario)],
)
@pytest.mark.asyncio
async def test_remote_edit_resource_handlers(event_cls, request_cls, mediator, client):
    resource = {"name": "some_name", "uuid": uuid1}
    client.add_response(resource)
    sentinel = object()
    with patch.object(movici_api_client.cli.handlers.remote, "edit_resource") as edit_resource:
        edit_resource.return_value = sentinel
        await mediator.send(event_cls(name_or_uuid=uuid1))
    assert client.request.await_args == call(request_cls(uuid1, sentinel))


@patch.object(
    filetransfer.UploadStrategy, "__eq__", lambda self, other: isinstance(other, type(self))
)
@pytest.mark.asyncio
async def test_remote_upload_dataset_handler(mediator, valid_project_uuid):
    with patch.object(filetransfer, "UploadResource", new_callable=AsyncMock) as mock:
        await mediator.send(
            UploadDataset(
                name_or_uuid="some_name",
                file="some_file.json",
            )
        )
    assert mock.await_args == call(
        file="some_file.json",
        parent_uuid=valid_project_uuid,
        strategy=filetransfer.DatasetUploadStrategy(object()),
        name_or_uuid="some_name",
    )


@patch.object(
    filetransfer.UploadStrategy, "__eq__", lambda self, other: isinstance(other, type(self))
)
@pytest.mark.asyncio
async def test_remote_upload_multiple_datasets_handler(mediator, data_dir, valid_project_uuid):
    with patch.object(filetransfer, "UploadMultipleResources", new_callable=AsyncMock) as mock:
        await mediator.send(UploadMultipleDatasets(directory=data_dir))
    assert mock.await_args == call(
        data_dir,
        valid_project_uuid,
        strategy=filetransfer.DatasetUploadStrategy(object()),
    )


@pytest.mark.asyncio
async def test_remote_download_dataset_handler(client, mediator, data_dir):
    dataset = {"uuid": "0000-0000", "name": "some_dataset"}
    client.add_response([dataset])
    with patch.object(filetransfer, "DownloadResource", new_callable=AsyncMock) as mock:
        await mediator.send(DownloadDataset("some_dataset", directory=data_dir))

    assert mock.await_args == call(
        file=data_dir.datasets.joinpath(dataset["name"]),
        request=req.GetDatasetData(dataset["uuid"]),
    )


@pytest.mark.asyncio
async def test_remote_download_multiple_datasets_handler(mediator, data_dir, valid_project_uuid):
    with patch.object(filetransfer, "DownloadDatasets", new_callable=AsyncMock) as mock:
        await mediator.send(DownloadMultipleDatasets(directory=data_dir))

    assert mock.await_args == call({"uuid": valid_project_uuid}, directory=data_dir)


@patch.object(movici_api_client.cli.handlers.remote, "wait_until_simulation_is_reset", AsyncMock())
@pytest.mark.asyncio
async def test_remote_clear_scenario_handler(client, mediator, patch_confirm):
    await mediator.send(ClearScenario(uuid1, confirm=True))
    assert patch_confirm.call_count == 1
    assert [c.args[0] for c in client.request.await_args_list] == [
        req.DeleteTimeline(uuid1),
        req.DeleteSimulation(uuid1),
    ]


@patch.object(movici_api_client.cli.handlers.remote, "wait_until_simulation_is_reset", AsyncMock())
@pytest.mark.asyncio
async def test_remote_clear_scenario_handler_no_confirm(mediator, patch_confirm):
    await mediator.send(ClearScenario(uuid1, confirm=False))
    assert patch_confirm.call_count == 0


@pytest.mark.asyncio
async def test_remote_run_simulation_handler(client, mediator):
    scenario = {"uuid": uuid1, "name": "some_scenario", "has_timeline": False}
    client.add_response([scenario])
    await mediator.send(RunSimulation(uuid1))
    assert client.request.await_args == call(req.RunSimulation(uuid1))


@pytest.mark.asyncio
async def test_remote_run_simulation_handler_with_timeline(gimme_repo, cli_params, client):
    cli_params.overwrite = True
    scenario = {"uuid": uuid1, "name": "some_scenario", "has_timeline": True}
    client.add_response([scenario])
    mediator = AsyncMock()
    await gimme_repo.get(RemoteRunSimulationHandler).handle(RunSimulation(uuid1), mediator)
    assert mediator.send.await_args == call(ClearScenario(uuid1, confirm=False))


@pytest.mark.asyncio
async def test_remote_upload_scenario_handler(mediator, valid_project_uuid):
    with patch.object(filetransfer, "UploadScenario", new_callable=AsyncMock) as mock:
        await mediator.send(
            UploadScenario(
                name_or_uuid="some_name",
                file="some_file.json",
            )
        )
    assert mock.await_args == call(
        file="some_file.json",
        parent_uuid=valid_project_uuid,
        name_or_uuid="some_name",
    )


@patch.object(
    filetransfer.UploadStrategy, "__eq__", lambda self, other: isinstance(other, type(self))
)
@pytest.mark.asyncio
async def test_remote_upload_multiple_scenarios_handler(mediator, data_dir, valid_project_uuid):
    with patch.object(filetransfer, "UploadMultipleResources", new_callable=AsyncMock) as mock:
        await mediator.send(UploadMultipleScenarios(directory=data_dir))
    assert mock.await_args == call(
        data_dir,
        valid_project_uuid,
        strategy=filetransfer.ScenarioUploadStrategy(object()),
    )


@pytest.mark.asyncio
async def test_remote_download_scenario_handler(mediator, client, data_dir):
    scenario = {"uuid": "0000-0000", "name": "some_name"}
    client.add_response([scenario])
    with patch.object(filetransfer, "DownloadSingleScenario", new_callable=AsyncMock) as mock:
        await mediator.send(DownloadScenario(name_or_uuid="some_name", directory=data_dir))
    assert mock.await_args == call(parent=scenario, directory=data_dir)


@pytest.mark.asyncio
async def test_remote_download_multiple_scenarios_handler(mediator, data_dir, valid_project_uuid):
    with patch.object(filetransfer, "DownloadScenarios", new_callable=AsyncMock) as mock:
        await mediator.send(DownloadMultipleScenarios(directory=data_dir))

    assert mock.await_args == call(
        {"uuid": valid_project_uuid}, directory=data_dir, progress=False
    )
