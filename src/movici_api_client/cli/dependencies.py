import typing as t

import gimme

T = t.TypeVar("T")
_repository = {}

_fixed_types = set()


def get(tp: t.Type[T]) -> T:
    return gimme.that(tp)  # type: ignore[no-any-return]


def set(obj, tp=None, fixed=False):
    if tp is None:
        tp = type(obj)
    if not fixed and tp in _fixed_types:
        return
    if fixed:
        _fixed_types.add(tp)
    _repository[tp] = obj


def reset():
    _repository.clear()
    _fixed_types.clear()
