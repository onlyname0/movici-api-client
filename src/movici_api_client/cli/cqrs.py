from __future__ import annotations

import typing as t

import gimme


class Event:
    pass


class EventHandler:
    __event__: t.Optional[t.Type[Event]] = None
    __result_type__: t.Optional[t.Type] = None

    async def handle(self, event: Event, mediator: Mediator) -> t.Any:
        raise NotImplementedError


class Mediator:
    def __init__(self, handlers=None) -> None:
        self.handlers: t.Dict[t.Type[Event], t.Type[EventHandler]] = handlers or {}

    async def send(self, event: Event):
        try:
            cls = self.handlers[type(event)]
        except KeyError:
            raise TypeError(f"No handler registered for Event of type {type(event).__name__}")
        handler = gimme.that(cls)
        return await handler.handle(event, self)

    def add_handler(self, event: t.Type[Event], handler: t.Type[EventHandler]):
        if event in self.handlers:
            raise ValueError(f"Event type {event.__name__} already has a registered handler")
        self.handlers[event] = handler

    def add_handlers(self, handlers: t.Dict[t.Type[Event], t.Type[EventHandler]]):
        for event, handler in handlers.items():
            self.add_handler(event, handler)
