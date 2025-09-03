import asyncio
import functools
import typing as t

import gimme

from movici_api_client.api import Client, Response
from movici_api_client.api.requests import CheckAuthToken
from movici_api_client.cli.controllers.common import resolve_data_directory
from movici_api_client.cli.cqrs import Event, Mediator

from . import dependencies
from .common import (
    OPTIONS_COMMAND,
    CLIParameters,
    Controller,
    get_options,
    has_options,
    set_options,
)
from .exceptions import (
    InvalidActiveProject,
    InvalidUsage,
    MoviciCLIError,
    NoActiveProject,
    Unauthenticated,
)
from .ui import format_anything, format_table
from .utils import (
    Choice,
    DirPath,
    assert_current_context,
    echo,
    get_project_uuids,
    handle_movici_error,
    maybe_set_flag,
)


def catch_exceptions(func):
    """Decorator for catching (movici) exceptions, and handling them properly"""

    @functools.wraps(func)
    def _decorated(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except MoviciCLIError as e:
            handle_movici_error(e)

    return _decorated


def authenticated(func):
    def on_error(resp: Response):
        if resp.status_code == 401:
            raise Unauthenticated()

    @functools.wraps(func)
    def _decorated(*args, **kwargs):
        client = dependencies.get(Client)

        context = assert_current_context()
        if context.get("auth"):
            client.request(CheckAuthToken(), on_error=on_error)
        return func(*args, **kwargs)

    return _decorated


def command(func=None, /, name=None, group=None):
    if func is None:
        return functools.partial(command, name=name, group=group)
    set_options(func, OPTIONS_COMMAND, {"name": name, "group_name": group})
    return func


def argument(*args, **kwargs):
    def wrapper(func):
        if not has_options(func, OPTIONS_COMMAND):
            set_options(func, OPTIONS_COMMAND, {})
        opts = get_options(func, OPTIONS_COMMAND)
        opts["arguments"] = [(args, kwargs), *opts.get("arguments", [])]

        return func

    return wrapper


def option(*args, **kwargs):
    def wrapper(func):
        if not has_options(func, OPTIONS_COMMAND):
            set_options(func, OPTIONS_COMMAND, {})
        opts = get_options(func, OPTIONS_COMMAND)

        opts.setdefault("options", []).append((args, kwargs))

        return func

    return wrapper


def format_output(func=None, /, fields=None, header=None):
    if func is None:
        return functools.partial(format_output, fields=fields, header=header)

    @functools.wraps(func)
    def decorated(*args, **kwargs):
        result = func(*args, **kwargs)
        result = format_anything(result, fields)
        if header is not None:
            result = header + "\n" + result
        echo(result)

    return decorated


def tabulate_results(func=None, /, keys=()):
    if func is None:
        return functools.partial(tabulate_results, keys=keys)

    @functools.wraps(func)
    def decorated(*args, **kwargs):
        result = func(*args, **kwargs)
        echo(format_table(result, keys))

    return decorated


def valid_project_uuid(func):
    @functools.wraps(func)
    def decorated(*args, **kwargs):
        context = assert_current_context()
        project = context.get("project")
        if not project:
            raise NoActiveProject()

        projects_dict = get_project_uuids()

        try:
            project_uuid = projects_dict[project]
        except KeyError:
            raise InvalidActiveProject(project)
        if len(args) and isinstance(args[0], Controller):
            self, *args = args
            return func(self, project_uuid, *args, **kwargs)
        return func(project_uuid, *args, **kwargs)

    return decorated


def upload_options(func):
    return combine_decorators(
        [
            option("--overwrite", is_flag=True, help="Always overwrite"),
            option("--create", is_flag=True, help="Always create if necessary"),
            option("-y", "--yes", is_flag=True, help="Answer yes to all questions"),
            option("-n", "--no", is_flag=True, help="Answer no to all questions"),
            option(
                "-o", "--output", type=Choice(["json"], case_sensitive=False), help="output format"
            ),
        ]
    )(func)


def download_options(
    purpose: t.Literal["datasets", "scenarios", "updates", "views"],
):
    def decorator(func):
        return combine_decorators(
            [
                data_directory_option(purpose),
                option("-o", "-y", "--overwrite", is_flag=True, help="Always overwrite"),
                option("-n", "--no-overwrite", is_flag=True, help="Never overwrite"),
            ]
        )(func)

    return decorator


def data_directory_option(purpose):
    return option(
        "-d",
        "--directory",
        type=DirPath(writable=True),
        default=None,
        callback=lambda _, __, path: resolve_data_directory(path, purpose),
    )


def combine_decorators(decorators: t.Iterable[t.Callable]):
    def decorator(func):
        return functools.reduce(
            lambda f, decorator: decorator(f),
            decorators,
            func,
        )

    return decorator


_CLI_OPTIONS = {
    "inspect": option(
        "-i",
        "--inspect",
        is_flag=True,
        help="read files to infer meta data and enforce consistency",
    ),
    "create": option("--create", is_flag=True, help="Always create if necessary"),
    "overwrite": option("--overwrite", is_flag=True, help="Always overwrite"),
    "no_overwrite": option("-n", "--no-overwrite", is_flag=True, help="Never overwrite"),
    "yes": option("-y", "--yes", is_flag=True, help="Answer yes to all questions"),
    "no": option("-n", "--no", is_flag=True, help="Answer no to all questions"),
    "output": option(
        "-o", "--output", type=Choice(["json"], case_sensitive=False), help="output format"
    ),
    "with_simulation": option("--with-simulation", is_flag=True),
    "with_views": option("--with-views", is_flag=True),
}


def cli_options(*options: str):
    click_options = combine_decorators(_CLI_OPTIONS[option] for option in options)

    def decorator(func):
        @click_options
        @functools.wraps(func)
        def wrapped(*args, **kwargs):
            normalize_options(kwargs)
            params = gimme.that(CLIParameters)

            for option in options:
                if option not in kwargs:
                    continue
                result = kwargs.pop(option)
                setattr(params, option, result)
            func(*args, **kwargs)

        return wrapped

    return decorator


def normalize_options(arguments: dict):
    if "overwrite" in arguments and "no_overwrite" in arguments:
        overwrite, no_overwrite = arguments.pop("overwrite"), arguments.pop("no_overwrite")
        if overwrite and no_overwrite:
            raise InvalidUsage("cannot combine --overwrite with --no-overwrite")
        arguments["overwrite"] = maybe_set_flag(False, overwrite, no_overwrite)

    if "yes" in arguments and "no" in arguments:
        yes, no = arguments.pop("yes"), arguments.pop("no")
        if yes and no:
            raise InvalidUsage("cannot combine --yes with --no")

        if "create" in arguments:
            arguments["create"] = maybe_set_flag(arguments["create"], yes, no)

        if "overwrite" in arguments:
            arguments["overwrite"] = maybe_set_flag(arguments["overwrite"], yes, no)

    return arguments


def handle_event(func=None, *, success_message=None):
    if func is None:
        return functools.partial(handle_event, success_message=success_message)

    @functools.wraps(func)
    def _wrapper(*args, **kwargs):
        event = func(*args, **kwargs)
        if not isinstance(event, Event):
            raise TypeError("A function decorated with 'handle_event' must return an Event")

        mediator = gimme.that(Mediator)
        result = asyncio.run(mediator.send(event))
        if success_message is not None:
            echo(success_message)
        return result

    return _wrapper
