import functools
import pathlib
import typing as t
import uuid

import gimme
import questionary
from click import Abort, Choice
from click import Path as PathType
from click import confirm, echo, prompt

from movici_api_client.api.client import Client
from movici_api_client.api.common import Request
from movici_api_client.api.requests import GetProjects
from movici_api_client.cli import dependencies
from movici_api_client.cli.common import OPTIONS_COMMAND, Controller, get_options
from movici_api_client.cli.config import Config
from movici_api_client.cli.exceptions import (
    InvalidResource,
    MoviciCLIError,
    NoActiveProject,
    NoConfig,
    NoCurrentContext,
)

# Show static analysis tools that we're using these imports with the intent to export, proxy and
# possibly adapt them
confirm = confirm
prompt = prompt
echo = echo
Abort = Abort
confirm = confirm
Choice = Choice

DirPath = functools.partial(
    PathType, file_okay=False, readable=True, exists=True, path_type=pathlib.Path
)
FilePath = functools.partial(
    PathType, dir_okay=False, readable=True, exists=True, path_type=pathlib.Path
)


def assert_context(config: Config):
    if config is None:
        raise NoConfig()
    if (rv := config.current_context) is None:
        raise NoCurrentContext()
    return rv


def assert_current_context():
    config = gimme.get(Config)
    return assert_context(config)


def assert_active_project(project=None):
    if project is None:
        context = assert_current_context()
        try:
            return assert_project_uuid(context["project"])
        except KeyError:
            raise NoActiveProject()


def assert_resource_uuid(resource: str, request: Request, resource_type="resource"):
    resources = get_resource_uuids(request)
    try:
        return resources[resource]
    except KeyError:
        raise InvalidResource(resource_type, resource)


def assert_project_uuid(project: str):
    return assert_resource_uuid(project, GetProjects(), resource_type="project")


def get_resource_uuids(request: Request):
    client = dependencies.get(Client)
    all_resources = client.request(request)
    if all_resources is None:
        return {}
    return {p["name"]: p["uuid"] for p in all_resources}


def get_resource_uuid(name_or_uuid, request, resource_type="resource", client=None):
    client = client or dependencies.get(Client)
    return (
        name_or_uuid
        if validate_uuid(name_or_uuid)
        else assert_resource_uuid(name_or_uuid, request=request, resource_type=resource_type)
    )


def get_resource(name_or_uuid, request, client=None, resource_type="resource"):
    client = client or dependencies.get(Client)
    all_resources = client.request(request)
    return get_resource_from_list(name_or_uuid, all_resources, resource_type=resource_type)


def get_project_uuids():
    return get_resource_uuids(GetProjects())


def get_resource_from_list(name_or_uuid, all_resources, resource_type="resource"):
    match_field = "uuid" if validate_uuid(name_or_uuid) else "name"
    for res in all_resources:
        if name_or_uuid == res[match_field]:
            return res
    else:
        raise InvalidResource(resource_type, name_or_uuid)


def handle_movici_error(e: MoviciCLIError):
    echo(str(e), err=True)
    raise Abort()


def iter_commands(obj: Controller):
    for key in obj.__commands__:
        val = getattr(obj, key)
        opts = get_options(val, OPTIONS_COMMAND)
        group_name = opts.get("group_name") if opts is not None else None
        group_name = group_name or key
        yield (group_name, val)


def prompt_choices(question: str, choices: t.Sequence[str]):
    return questionary.select(
        question,
        choices=choices,
        use_shortcuts=len(choices) < 36,
        use_arrow_keys=True,
    ).unsafe_ask()


async def prompt_choices_async(question: str, choices: t.Sequence[str]):
    return await questionary.select(
        question,
        choices=choices,
        use_shortcuts=len(choices) < 36,
        use_arrow_keys=True,
    ).unsafe_ask_async()


def validate_uuid(entry: t.Union[str, uuid.UUID]):
    if isinstance(entry, uuid.UUID):
        return True
    try:
        uuid.UUID(entry)
    except ValueError:
        return False

    return True


def maybe_set_flag(flag: bool, default_yes: bool, default_no: bool) -> t.Optional[bool]:
    """Returns the value for a question-like flag. These flags can be set to either True/False or
    None in which case the user should be asked. If the flag is not specifically set to True and no
    default is given, flag is set to None. A positive flag value has precedence over a default no.
    Behaviour for when both default_yes and default_no are True is undefined and should be
    discouraged
    """
    if flag:
        return flag

    default: t.Optional[bool] = default_yes or not default_no
    if not default_yes and not default_no:
        default = None

    return default
