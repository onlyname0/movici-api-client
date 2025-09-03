import contextlib
import json
import os
import pathlib
import tempfile
from subprocess import call

from .exceptions import InvalidEditor, InvalidFile, InvalidFileEdit, NoChangeDetected


def read_json_file(file: pathlib.Path) -> dict:
    if not file.is_file():
        raise InvalidFile("not a file", file)
    try:
        return json.loads(file.read_text())  # type: ignore[no-any-return]
    except IOError:
        raise InvalidFile("read error", file)
    except json.JSONDecodeError:
        raise InvalidFile("invalid json", file)


def edit_resource(resource: dict, editor=None, editor_env="EDITOR", default_editor="vim"):
    EDITOR = editor or os.environ.get(editor_env, default_editor)

    initial_message = json.dumps(resource, indent=2)

    with create_tempfile(suffix=".tmp") as file:
        with open(file, "w") as fh:
            fh.write(initial_message)

        try:
            call(make_editor_command(EDITOR, file))
        except FileNotFoundError:
            raise InvalidEditor(EDITOR)

        with open(file, "r") as f:
            result = f.read()

    try:
        rv = json.loads(result)
    except json.JSONDecodeError:
        raise InvalidFileEdit()

    if rv == resource:
        raise NoChangeDetected()
    return rv


@contextlib.contextmanager
def create_tempfile(suffix=None, prefix=None, dir=None, text=False):
    _, file = tempfile.mkstemp(suffix, prefix, dir, text)
    try:
        yield file
    finally:
        try:
            os.remove(file)
        except IOError:
            pass


def make_editor_command(editor: str, file: str):
    additional_args = {
        "vim": ("-c", "set syntax=json"),
        "nano": ("--syntax=json",),
    }.get(editor, ())
    return [editor, *additional_args, file]
