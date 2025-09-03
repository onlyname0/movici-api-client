import pathlib
import typing as t

from movici_api_client.api.requests import GetDatasets, GetScenarios
from movici_api_client.cli.data_dir import (
    DatasetsDirectory,
    MoviciDataDir,
    ScenariosDirectory,
    UpdatesDirectory,
    ViewsDirectory,
)
from movici_api_client.cli.exceptions import CustomError

from ..utils import echo, get_resource, get_resource_uuid


def get_dataset_uuid(name_or_uuid, project_uuid, client=None):
    return get_resource_uuid(
        name_or_uuid, request=GetDatasets(project_uuid), resource_type="dataset", client=client
    )


def get_dataset(name_or_uuid, project_uuid, client=None):
    return get_resource(
        name_or_uuid, GetDatasets(project_uuid), client=client, resource_type="dataset"
    )


def get_scenario_uuid(name_or_uuid, project_uuid, client=None):
    return get_resource_uuid(
        name_or_uuid, request=GetScenarios(project_uuid), resource_type="scenario", client=client
    )


def get_scenario(name_or_uuid, project_uuid, client=None):
    return get_resource(
        name_or_uuid, GetScenarios(project_uuid), client=client, resource_type="scenario"
    )


def resolve_data_directory(
    path: t.Union[str, pathlib.Path, None],
    purpose: t.Literal["datasets", "scenarios", "updates", "views", "project"],
):
    if data_dir := MoviciDataDir.resolve_from_subpath(path or pathlib.Path(".")):
        echo("Movici data directory detected")
        return data_dir

    if path is not None:
        path = pathlib.Path(path).resolve()
        return {
            "datasets": DatasetsDirectory,
            "scenarios": ScenariosDirectory,
            "updates": UpdatesDirectory,
            "views": ViewsDirectory,
            "project": MoviciDataDir,
        }[purpose](path)

    raise CustomError("Could not determine directory")
