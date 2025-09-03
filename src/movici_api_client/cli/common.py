from __future__ import annotations

import dataclasses
import typing as t

import gimme

from movici_api_client.api import AsyncClient, Client
from movici_api_client.cli.cqrs import Mediator

__MOVICI_CLI_OPTIONS__ = "__movici_cli_options__"

OPTIONS_COMMAND = "command"


def set_options(obj, key: str, options: dict):
    opts = getattr(obj, __MOVICI_CLI_OPTIONS__, {})
    opts[key] = {**opts.get(key, {}), **options}
    setattr(obj, __MOVICI_CLI_OPTIONS__, opts)


def get_options(obj, key: str) -> t.Optional[dict]:
    return getattr(obj, __MOVICI_CLI_OPTIONS__, {}).get(key, None)  # type: ignore[no-any-return]


def has_options(obj, key: str) -> bool:
    return key in getattr(obj, __MOVICI_CLI_OPTIONS__, {})


def remove_options(obj, key: str):
    options: t.Optional[dict]
    if options := getattr(obj, __MOVICI_CLI_OPTIONS__, None):
        del options[key]


@dataclasses.dataclass
class CLIParameters:
    overwrite: t.Optional[bool] = None
    no_overwrite: t.Optional[bool] = None
    create: t.Optional[bool] = None
    inspect: t.Optional[bool] = None
    yes: t.Optional[bool] = None
    no: t.Optional[bool] = None
    with_simulation: t.Optional[bool] = None
    with_views: t.Optional[bool] = None
    output: t.Optional[str] = None


class Controller:
    name: str
    reverse: bool = True
    decorators: t.Iterable[t.Callable] = ()
    __commands__: t.Set[str]

    mediator: Mediator = gimme.attribute(Mediator)
    client: Client = gimme.attribute(Client)
    async_client: AsyncClient = gimme.attribute(AsyncClient)
    params: CLIParameters = gimme.attribute(CLIParameters)

    def __init_subclass__(cls) -> None:
        __commands__ = set()
        for key in dir(cls):
            val = getattr(cls, key)
            if get_options(val, OPTIONS_COMMAND):
                __commands__.add(key)
        cls.__commands__ = __commands__
