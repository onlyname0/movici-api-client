import dataclasses
import typing as t

import tabulate


def format_anything(obj, fields):
    if isinstance(obj, list):
        return format_table(obj, fields)
    if callable(as_dict := getattr(obj, "as_dict", None)):
        return format_dict(as_dict())
    if isinstance(obj, str):
        return obj
    if fields is not None:
        return format_object(obj, fields)

    # if fields is None we can fallback to methods that can determine field names
    if isinstance(obj, dict):
        return format_dict(obj)
    if dataclasses.is_dataclass(obj):
        return format_dataclass(obj)


def format_object(obj, fields: t.Sequence[str], header=None):
    lines = []
    if header is not None:
        lines.append(header)

    max_field_len = max(len(f) for f in fields) if fields else None
    for field in fields:
        lines.append(f"{field:<{max_field_len}s}: {get_value(obj, field)!s}")
    return "\n".join(lines)


def format_dict(
    obj, include: t.Sequence[str] = None, exclude: t.Sequence[str] = None, header=None
):
    if include is not None:
        keys = include
    else:
        keys = set(obj)
        if exclude is not None:
            keys -= set(exclude)
    return format_object(obj, keys, header=header)


def format_dataclass(dc, header=None):
    fields = [f.name for f in dataclasses.fields(dc)]
    return format_object(dc, fields, header=header)


def get_value(obj_or_dict, key, default=None):
    if isinstance(obj_or_dict, dict):
        return obj_or_dict.get(key, default)
    else:
        return getattr(obj_or_dict, key, default)


def pick(obj, attrs: t.List[str], default=None):
    return {key: get_value(obj, key, default) for key in attrs}


def format_table(objects, keys, default=""):
    if keys is not None:
        objects = (pick(o, keys, default) for o in objects)
    return tabulate.tabulate(objects, headers="keys")
