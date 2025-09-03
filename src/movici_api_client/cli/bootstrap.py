import functools
import sys
import typing as t

import click

from movici_api_client.cli.decorators import catch_exceptions
from movici_api_client.cli.utils import iter_commands

from .common import OPTIONS_COMMAND, Controller, get_options


def create_click_command(func, opts=None, factory=click.command):
    if opts is None:
        opts = get_options(func, OPTIONS_COMMAND)
    command = factory(func)
    for args, kwargs in opts.get("arguments") or []:
        command = click.argument(*args, **kwargs)(command)
    for args, kwargs in opts.get("options") or []:
        command = click.option(*args, **kwargs)(command)
    return command


def register_controller(group: click.Group, controller: Controller):
    if controller.reverse:
        register_controller_reversed(group, controller)

    for name, func in iter_commands(controller):
        opts = get_options(func, OPTIONS_COMMAND)
        command_name = opts.get("name") if opts is not None else None
        command_name = command_name or name
        func = functools.reduce(lambda f, dec: dec(f), controller.decorators, func)
        register_command_in_subgroup(
            group,
            subgroup_name=controller.name,
            command=func,
            command_name=command_name,
        )


def register_controller_reversed(group: click.Group, controller: Controller):
    for group_name, func in iter_commands(controller):
        opts = get_options(func, OPTIONS_COMMAND)
        command_name = opts.get("name") if opts is not None else None
        command_name = command_name or controller.name
        func = functools.reduce(lambda f, dec: dec(f), controller.decorators, func)

        register_command_in_subgroup(group, group_name, func, command_name)


def register_command_in_subgroup(
    group: click.Group, subgroup_name, command: t.Callable, command_name=None
):
    if subgroup := group.commands.get(subgroup_name):
        if not isinstance(subgroup, click.Group):
            raise TypeError(f"Command {subgroup_name} is not group")
        is_new = False
    else:
        subgroup = click.Group(subgroup_name)
        is_new = True
    register_command(subgroup, command, command_name)

    if is_new:
        group.add_command(subgroup)


def register_command(group: click.Group, command, name=None):
    if name is None:
        opts = get_options(command, OPTIONS_COMMAND)
        name = opts.get("name") if opts is not None else None
    command = catch_exceptions(command)
    command = create_click_command(command)
    group.add_command(command, name)


def cli_factory(main, commands=None, controller_types=None, result_callback=None, on_error=None):
    main = create_click_command(catch_exceptions(main), factory=click.group)
    for cmd in commands or []:
        register_command(main, cmd)

    for ct in controller_types or []:
        register_controller(main, ct())
    if result_callback:
        main.result_callback()(result_callback)
    if on_error:

        def safe_invoke():
            try:
                return main()
            except Exception as e:
                on_error(e)
                sys.exit(1)

        return safe_invoke
    return main
