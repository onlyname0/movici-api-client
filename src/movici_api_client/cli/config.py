from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import typing as t

import gimme

from movici_api_client.cli.helpers import read_json_file

from .exceptions import DuplicateContext, InvalidConfigFile, InvalidFile

# "~" is properly expanded using pathlib.Path.expanduser() on all platforms including windows
DEFAULT_CONFIG_LOCATION = "~/.movici.conf"
CONFIG_LOCATION_ENV = "MOVICI_CLI_CONFIG"


def get_config_path(env=CONFIG_LOCATION_ENV, default=DEFAULT_CONFIG_LOCATION):
    return pathlib.Path(os.getenv(env, default=default)).expanduser()


def get_config(file: t.Optional[pathlib.Path] = None):
    file = pathlib.Path(file) if file is not None else get_config_path()
    try:
        if not file.is_file():
            return initialize_config(file)

        return Config.from_dict(read_json_file(file))

    except IOError:
        raise InvalidConfigFile("read error", file)
    except InvalidFile as e:
        raise InvalidConfigFile(e.msg, e.file)
    except (KeyError, TypeError):
        raise InvalidConfigFile("invalid values", file)
    except Exception:
        raise InvalidConfigFile("unknown cause", file)


def initialize_config(file: pathlib.Path):
    config = Config.from_dict({"version": 1, "current_context": None, "contexts": []})
    write_config(config, file)
    return config


def read_config(file: pathlib.Path) -> Config:
    return Config.from_dict(json.loads(file.read_text()))  # type: ignore[no-any-return]


def write_config(config: t.Optional[Config] = None, file: t.Optional[pathlib.Path] = None):
    config = config or gimme.that(Config)
    file = pathlib.Path(file) if file is not None else get_config_path()
    file.write_text(json.dumps(config.as_dict(), indent=2))


class Config:
    """An in memory representation of the config file"""

    def __init__(
        self, contexts: t.Sequence[Context], current_context: t.Optional[str] = None, version=1
    ) -> None:
        self.version = version
        self.contexts = list(contexts)
        self.current_context = self.get_context(current_context)

    def activate_context(self, name):
        context = self.get_context(name)
        if not context:
            raise ValueError(f"Invalid config name {name}")
        self.current_context = context

    def get_context(self, name) -> t.Optional[Context]:
        for context in self.contexts:
            if context.name == name:
                return context
        return None

    def add_context(self, context: Context):
        if self.get_context(context.name) is not None:
            raise DuplicateContext(context.name)
        self.contexts.append(context)

    def remove_context(self, item: t.Union[str, Context]):
        try:
            if isinstance(item, str):
                name = item
                context = self.get_context(name)
                if context is not None:
                    self.contexts.remove(context)
            else:
                name = item.name
                self.contexts.remove(item)
        except (KeyError, ValueError):
            pass
        else:
            if self.current_context is not None and name == self.current_context.name:
                self.current_context = None

    def as_dict(self):
        return {
            "version": self.version,
            "current_context": (
                self.current_context.name if self.current_context is not None else None
            ),
            "contexts": [context.as_dict() for context in self.contexts],
        }

    @classmethod
    def from_dict(cls, config: dict):
        return cls(
            current_context=config["current_context"],
            contexts=[Context(**context) for context in config["contexts"]],
            version=config["version"],
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, type(self)):
            return False
        return (
            self.version == other.version
            and self.current_context == other.current_context
            and self.contexts == other.contexts
        )


def parse_bool(value, allow_none=False):
    falsy = {"False", "f", "false"}
    if value is None and allow_none:
        return None
    if value in falsy:
        return False
    return bool(value)


_MISSING = object()


@dataclasses.dataclass
class SpecialKey:
    parse: t.Optional[t.Callable] = None
    default: t.Any = _MISSING
    required: bool = False


class Context(dict):
    __special_keys__ = {
        "auth": SpecialKey(parse=parse_bool, default=True),
        "name": SpecialKey(required=True),
        "url": SpecialKey(required=True),
    }

    def __init__(self, name: str, url: str, **kwargs) -> None:
        super().__init__(name=name, url=url, **kwargs)

    def __getattribute__(self, name):
        if name in type(self).__special_keys__:
            return self[name]
        return super().__getattribute__(name)

    def __setattr__(self, name: str, value):
        if name in self.__special_keys__:
            self[name] = value
        else:
            super().__setattr__(name, value)

    def __getitem__(self, key):
        if (special := self.__special_keys__.get(key)) and special.default:
            return self.get(key, special.default)
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        if (special := self.__special_keys__.get(key)) and special.parse:
            value = special.parse(value)
        super().__setitem__(key, value)

    def __delitem__(self, key):
        if (special := self.__special_keys__.get(key)) and special.required:
            raise ValueError("Cannot detele required key")

        return super().__delitem__(key)

    def get(self, key, default=None):
        if (special := self.__special_keys__.get(key)) and special.default:
            default = special.default

        return super().get(key, default)

    def __eq__(self, __o: object) -> bool:
        if not isinstance(__o, Context):
            return False

        return all((self.name == __o.name, self.url == __o.url, super().__eq__(__o)))

    def as_dict(self):
        return {"name": self.name, "url": self.url, **self}
