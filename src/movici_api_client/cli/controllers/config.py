import gimme

from movici_api_client.cli.config import Config, Context, write_config
from movici_api_client.cli.exceptions import DuplicateContext, NoContextAvailable, NoSuchContext

from ..common import Controller
from ..decorators import argument, command, format_output, option
from ..utils import assert_context, confirm, echo, prompt


class ConfigController(Controller):
    name = "config"
    reverse = False
    config: Config = gimme.attribute(Config)

    @command
    @argument("name", required=False)
    def create(self, name):
        config = self.config

        if config.get_context(name):
            raise DuplicateContext(name)

        echo("Creating a new context, please give the following information")
        name = name or prompt("Name")
        url = prompt("Base URL (eg: https://example.org/)")
        context = Context(name, url)
        config.add_context(context)

        activate = confirm("Do you wish to activate this context?", default=True)
        if activate:
            config.activate_context(name)
        write_config(config)
        echo("Context succesfully created")

    @command
    @argument("context")
    def activate(self, context: str):
        config = self.config
        if not len(config.contexts):
            raise NoContextAvailable()
        try:
            config.activate_context(context)
        except ValueError:
            raise NoSuchContext(context=context)

        write_config(config)

    @command
    @option("-a", "--all", is_flag=True)
    @format_output
    def show(self, all):
        config = self.config
        if all:
            return config.contexts
        else:
            return assert_context(config)

    @command
    @argument("key")
    @argument("value")
    def set(self, key, value):
        config = self.config
        context = assert_context(config)
        context[key] = value

        write_config(config)
        echo("Context succesfully updated")

    @command
    @argument("keys", nargs=-1, required=True)
    def unset(self, keys):
        config = self.config
        context = assert_context(config)

        for key in keys:
            try:
                del context[key]
            except KeyError:
                pass
            except ValueError:
                echo(f"Cannot unset read-only field '{key}'", err=True)

        write_config(config)
        echo("Context succesfully updated")
