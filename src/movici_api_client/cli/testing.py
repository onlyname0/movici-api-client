import dataclasses
import typing as t
from collections import deque
from unittest.mock import AsyncMock, Mock

from movici_api_client.api.client import AsyncClient, Client


class FakeClient(Client):
    mock_cls = Mock

    def __init__(self, *args, **kwargs) -> None:
        self.responses: deque = deque()
        self.request = self.mock_cls(side_effect=self._request)  # type: ignore[method-assign]

    def _request(self, req, on_error=None):
        response = self.next_response()

        if response is None:
            return
        if response.status_code >= 400 and on_error is not None:
            on_error(response)
        else:
            return response.data

    def set_response(self, response_data=None, status_code=200):
        self.responses = deque([FakeResponse(response_data, status_code)])

    def add_response(self, response_data=None, status_code=200):
        self.responses.append(FakeResponse(response_data, status_code))

    def next_response(self):
        try:
            return self.responses.popleft()
        except IndexError:
            return None


class FakeAsyncClient(FakeClient, AsyncClient):  # type: ignore[misc]
    mock_cls = AsyncMock

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return


@dataclasses.dataclass
class FakeResponse:
    data: t.Optional[dict] = None
    status_code: int = 200
