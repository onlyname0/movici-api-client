from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from movici_api_client.cli.cqrs import Event, EventHandler, Mediator


@pytest.fixture(autouse=True)
def setup_gimme(gimme_repo):
    gimme_repo.register(Event, store=False)


class FakeHandler(EventHandler, AsyncMock):
    async def handle(self, event: FakeEvent, mediator):
        await self(event)
        event.handled = True


class FakeEvent(Event):
    handled = False


class Event1(FakeEvent):
    pass


class Event2(FakeEvent):
    pass


@pytest.fixture
def mediator():
    return Mediator({Event1: FakeHandler})


class TestMediator:
    def test_add_handler(self, mediator):
        assert mediator.handlers[Event1] is FakeHandler

    def test_add_multiple_handlers(self):
        mediator = Mediator()
        mediator.add_handlers({Event1: FakeHandler, Event2: FakeHandler})
        assert mediator.handlers[Event1] is FakeHandler
        assert mediator.handlers[Event2] is FakeHandler

    def test_raises_on_conflicting_handler(self, mediator):
        with pytest.raises(ValueError):
            mediator.add_handler(Event1, FakeHandler)

    @pytest.mark.asyncio
    async def test_runs_handler_with_event(self, mediator):
        event = Event1()
        await mediator.send(event)
        assert event.handled

    @pytest.mark.asyncio
    async def test_injects_dependencies(self, gimme_repo):
        class MyService:
            def __init__(self) -> None:
                self.events: list[str] = []

        service = MyService()
        gimme_repo.add(service)

        class MyHandler(EventHandler):
            def __init__(self, service: MyService) -> None:
                self.service = service

            async def handle(self, event, mediator):
                self.service.events.append(event)

        mediator = Mediator({Event1: MyHandler})

        event = Event1()
        await mediator.send(event)
        assert event in service.events
