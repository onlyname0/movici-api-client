import pathlib
from json import JSONDecodeError
from typing import Literal, Union

import gimme
import httpx

from movici_api_client.api import Client, HTTPError, MoviciTokenAuth, Response
from movici_api_client.api.client import AsyncClient
from movici_api_client.api.common import parse_service_urls
from movici_api_client.cli.cqrs import Mediator
from movici_api_client.cli.data_dir import MoviciDataDir
from movici_api_client.cli.exceptions import InvalidResource
from movici_api_client.cli.handlers import REMOTE_HANDLERS

from . import dependencies
from .config import Config, get_config, write_config
from .controllers.login import LoginController
from .decorators import argument, authenticated, command, option
from .utils import (
    Abort,
    PathType,
    assert_context,
    assert_current_context,
    echo,
    get_project_uuids,
    prompt_choices,
)


def setup_dependencies():
    gimme.register(Config, get_config)
    gimme.register(Client, setup_client)
    gimme.register(AsyncClient, AsyncClient.from_sync_client)
    gimme.register(Mediator, setup_mediator)


def setup_client(config: Config):
    context = config.current_context

    if context is None:
        return Client(base_url="")
    auth: Union[MoviciTokenAuth, Literal[False]] = (
        MoviciTokenAuth(auth_token=context.get("auth_token")) if context.get("auth") else False
    )
    return Client(
        base_url=context.url,
        auth=auth,
        on_error=handle_http_error,
        service_urls=parse_service_urls(context, prefix="service."),
        client=httpx.Client(timeout=httpx.Timeout(10.0, read=60.0)),
    )


def setup_mediator(config: Config):
    context = config.current_context

    if context is not None and not context.get("local"):
        return Mediator(REMOTE_HANDLERS)
    return Mediator()


@option("project_override", "-p", "--project", default="")
def main(project_override):
    setup_dependencies()

    config = gimme.that(Config)
    context = config.current_context

    if project_override:
        context["project"] = project_override


def handle_http_error(resp: Response):
    try:
        msg = resp.json()
    except JSONDecodeError:
        msg = resp.status_code

    echo(f"HTTP Error: {msg}")
    raise Abort()


def handle_global_error(exc: Exception):
    if isinstance(exc, HTTPError):
        echo(f"A HTTP Error occured: {type(exc).__name__}({exc!s})")
    else:
        raise exc from None


@command
@option("-U", "--user", "ask_username", is_flag=True, help="always ask for a username")
def login(ask_username):
    client = dependencies.get(Client)
    context = assert_current_context()
    echo(f"Login to {context.url}:")
    LoginController(client, context).login(ask_username)
    write_config()
    echo("Success!")


@command(name="activate-project")
@argument("project", default="")
@authenticated
def activate_project(project):
    config = dependencies.get(Config)
    context = assert_context(config)

    projects_dict = get_project_uuids()
    if not project:
        project = prompt_choices("Choose a project", sorted(projects_dict))
    if project not in projects_dict:
        raise InvalidResource("project", project)

    context["project"] = project
    write_config(config)
    echo(f"Project {project} succefully activated!")


@command(name="initialize-data-dir")
@argument("directory", type=PathType(), default=pathlib.Path("."))
def initialize_data_dir(directory):
    MoviciDataDir.initialize(pathlib.Path(directory))
    echo("Succesfully initialized movici data directory")
