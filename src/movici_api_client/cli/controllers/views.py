import asyncio
import json
import pathlib
import typing as t

import gimme

from movici_api_client.api.client import AsyncClient, Client
from movici_api_client.api.requests import DeleteView, GetSingleView, GetViews, UpdateView

from ..common import CLIParameters, Controller
from ..data_dir import DataDir
from ..decorators import (
    argument,
    authenticated,
    command,
    download_options,
    format_output,
    option,
    upload_options,
    valid_project_uuid,
)
from ..dependencies import get
from ..exceptions import InvalidUsage, NotYetImplemented
from ..filetransfer import UploadMultipleResources
from ..filetransfer.download import DownloadViews, prepare_overwrite_file
from ..filetransfer.upload import UploadResource, ViewUploadStrategy
from ..helpers import edit_resource
from ..utils import (
    Choice,
    DirPath,
    FilePath,
    confirm,
    echo,
    get_resource_from_list,
    maybe_set_flag,
    validate_uuid,
)
from .common import get_scenario, get_scenario_uuid, resolve_data_directory


class ViewController(Controller):
    name = "view"
    decorators = (valid_project_uuid, authenticated)

    @command(name="views", group="get")
    @argument("scenario_name_or_uuid")
    @format_output(
        fields=(
            "uuid",
            "name",
        )
    )
    def list(self, project_uuid, scenario_name_or_uuid):
        client = get(Client)
        scenario_uuid = get_scenario_uuid(scenario_name_or_uuid, project_uuid, client=client)

        return client.request(GetViews(scenario_uuid))

    @command
    @argument("scenario_name_or_uuid")
    @argument("view_name_or_uuid")
    @option("-o", "--output", type=Choice(["json"], case_sensitive=False), help="output format")
    @format_output(
        fields=(
            "uuid",
            "name",
        )
    )
    def get(self, project_uuid, scenario_name_or_uuid, view_name_or_uuid, output):
        result = get_view(project_uuid, scenario_name_or_uuid, view_name_or_uuid)
        if output == "json":
            result = json.dumps(result, indent=2)
        return result

    @command
    @argument("scenario_name_or_uuid")
    @argument("view_name_or_uuid")
    @format_output
    def create(
        self, project_uuid, scenario_name_or_uuid, view_name_or_uuid, display_name, dataset_type
    ):
        raise NotYetImplemented()

    @command
    @argument("scenario_name_or_uuid")
    @argument("view_name_or_uuid")
    @format_output
    def update(self, project_uuid, scenario_name_or_uuid, view_name_or_uuid):
        raise NotYetImplemented()

    @command
    @argument("scenario_name_or_uuid")
    @argument("view_name_or_uuid")
    @format_output
    def delete(self, project_uuid, scenario_name_or_uuid, view_name_or_uuid):
        client = get(Client)
        view = get_view(project_uuid, scenario_name_or_uuid, view_name_or_uuid)
        uuid = view["uuid"]

        confirm(f"Are you sure you wish to delete view '{view_name_or_uuid}'")
        return client.request(DeleteView(uuid))

    @command
    @argument("scenario_name_or_uuid")
    @argument("view_name_or_uuid", default="")
    @option("-f", "--file", type=FilePath(), required=True)
    @upload_options
    def upload(
        self,
        project_uuid,
        scenario_name_or_uuid,
        view_name_or_uuid,
        file: pathlib.Path,
        overwrite,
        create,
        yes,
        no,
    ):
        client = AsyncClient.from_sync_client(get(Client))
        view_name_or_uuid = view_name_or_uuid or file.stem
        scenario_uuid = get_scenario_uuid(scenario_name_or_uuid, project_uuid, client)

        # Set parameters in CLIParameters
        params = gimme.that(CLIParameters)
        params.overwrite = maybe_set_flag(overwrite, yes, no)
        params.create = maybe_set_flag(create, yes, no)
        params.inspect = True

        asyncio.run(
            UploadResource(
                file,
                parent_uuid=scenario_uuid,
                strategy=ViewUploadStrategy(client=client),
                name_or_uuid=view_name_or_uuid,
            ).run()
        )

        echo("Success!")

    @command(name="views", group="upload")
    @argument("scenario_name_or_uuid")
    @option(
        "-d",
        "--directory",
        type=DirPath(writable=True),
        default=None,
        callback=lambda _, __, path: resolve_data_directory(path, "views"),
    )
    @upload_options
    def upload_multiple(
        self, project_uuid, scenario_name_or_uuid, directory, overwrite, create, yes, no
    ):
        if yes and no:
            raise InvalidUsage("cannot combine --force with --never")
        client = get(Client)
        scenario = get_scenario(scenario_name_or_uuid, project_uuid, client)
        client = AsyncClient.from_sync_client(get(Client))
        strategy = ViewUploadStrategy(client=client, scenario=scenario)

        # Set parameters in CLIParameters
        params = gimme.that(CLIParameters)
        params.overwrite = maybe_set_flag(overwrite, yes, no)
        params.create = maybe_set_flag(create, yes, no)
        params.inspect = True

        asyncio.run(
            UploadMultipleResources(
                directory,
                parent_uuid=scenario["uuid"],
                strategy=strategy,
            ).run()
        )
        echo("Success!")

    @command
    @argument("scenario_name_or_uuid")
    @argument("view_name_or_uuid")
    @download_options(purpose="views")
    def download(
        self,
        project_uuid,
        scenario_name_or_uuid,
        view_name_or_uuid,
        directory: DataDir,
        overwrite,
        no_overwrite,
    ):
        if overwrite and no_overwrite:
            raise InvalidUsage("cannot combine --overwrite with --no-overwrite")
        client = get(Client)

        scenario = get_scenario(
            name_or_uuid=scenario_name_or_uuid, project_uuid=project_uuid, client=client
        )
        view = get_view(project_uuid, scenario_name_or_uuid, view_name_or_uuid, client=client)

        views_dir = directory.ensure_views_dir(scenario["name"])
        file = views_dir.joinpath(view["name"]).with_suffix(".json")

        if not prepare_overwrite_file(
            file, overwrite=maybe_set_flag(False, default_yes=overwrite, default_no=no_overwrite)
        ):
            return
        file.write_text(json.dumps(view, indent=2))
        echo("Success!")

    @command(name="views", group="download")
    @argument("scenario_name_or_uuid")
    @download_options(purpose="views")
    def download_multiple(
        self, project_uuid, scenario_name_or_uuid, directory, overwrite, no_overwrite
    ):
        client = get(Client)

        scenario = get_scenario(scenario_name_or_uuid, project_uuid=project_uuid, client=client)

        client = AsyncClient.from_sync_client(client)
        asyncio.run(
            DownloadViews(
                client,
                scenario,
                directory=directory,
                overwrite=maybe_set_flag(False, default_yes=overwrite, default_no=no_overwrite),
            ).run()
        )
        echo("Success!")

    @command
    @argument("scenario_name_or_uuid")
    @argument("view_name_or_uuid")
    def edit(self, project_uuid, scenario_name_or_uuid, view_name_or_uuid):
        client = get(Client)
        current = get_view(project_uuid, scenario_name_or_uuid, view_name_or_uuid, client=client)
        uuid = current["uuid"]
        result = edit_resource(current)
        client.request(UpdateView(uuid, payload=result))
        echo("Succesfully updated view")


def get_view(
    project_uuid, scenario_name_or_uuid, view_name_or_uuid, client: t.Optional[Client] = None
):
    client = client or get(Client)

    if validate_uuid(view_name_or_uuid):
        return client.request(GetSingleView(view_name_or_uuid))

    scenario_uuid = get_scenario_uuid(scenario_name_or_uuid, project_uuid, client=client)

    all_views = client.request(GetViews(scenario_uuid))
    return get_resource_from_list(view_name_or_uuid, all_views, resource_type="view")
