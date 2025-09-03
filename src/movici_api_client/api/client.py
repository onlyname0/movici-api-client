from __future__ import annotations

import contextlib
import logging
import typing as t
from asyncio import Semaphore
from typing import Literal

import httpx
from httpx import HTTPError, HTTPStatusError, Response, Timeout  # noqa

from .common import (
    Auth,
    BaseClient,
    BaseRequest,
    ErrorCallback,
    IAsyncClient,
    ISyncClient,
    Service,
)

T = t.TypeVar("T")

DEFAULT_TIMEOUT_CONFIG = Timeout(timeout=5.0)


class Client(BaseClient, ISyncClient):
    def __init__(
        self,
        base_url: str,
        auth: t.Union[Auth, None, Literal[False]] = None,
        client: t.Optional[httpx.Client] = None,
        logger: t.Optional[logging.Logger] = None,
        on_error: t.Optional[ErrorCallback] = None,
        service_urls: t.Optional[t.Dict[Service, str]] = None,
    ):
        super().__init__(base_url, auth, logger, on_error, service_urls)
        self.client = client or httpx.Client(timeout=DEFAULT_TIMEOUT_CONFIG)
        self.timeout = self.client.timeout

    def request(
        self, req: BaseRequest[T], on_error: t.Optional[ErrorCallback] = None
    ) -> t.Optional[T]:
        self._assert_auth(req)
        conf = self._prepare_request_config(req)
        resp = self.client.request(**conf)
        self._handle_failure(resp, on_error)
        return req.make_response(resp)

    @contextlib.contextmanager
    def stream(self, req: BaseRequest[T], on_error: t.Optional[ErrorCallback] = None):
        conf = self._prepare_request_config(req)
        with self.client.stream(**conf) as resp:
            self._handle_failure(resp, on_error)
            yield resp


class AsyncClient(BaseClient, IAsyncClient):
    client: t.Optional[httpx.AsyncClient]

    def __init__(
        self,
        base_url: str,
        auth: t.Union[Auth, None, Literal[False]] = None,
        client_factory: t.Type[httpx.AsyncClient] = httpx.AsyncClient,
        logger: t.Optional[logging.Logger] = None,
        on_error: t.Optional[ErrorCallback] = None,
        service_urls: t.Optional[t.Dict[Service, str]] = None,
        max_concurrent=10,
        timeout=DEFAULT_TIMEOUT_CONFIG,
    ):
        super().__init__(base_url, auth, logger, on_error, service_urls)
        self.client_factory = client_factory
        self.client = None
        self.concurrent_requests = Semaphore(max_concurrent)
        self.enter_count = 0
        self.timeout = timeout

    async def request(self, req: BaseRequest[T], on_error: t.Optional[ErrorCallback] = None):
        async with self.concurrent_requests:
            self._ensure_client()
            self._assert_auth(req)
            conf = self._prepare_request_config(req)
            assert self.client is not None
            resp = await self.client.request(**conf)

            self._handle_failure(resp, on_error)
            return req.make_response(resp)

    @contextlib.asynccontextmanager
    async def stream(self, req: BaseRequest[T], on_error: t.Optional[ErrorCallback] = None):
        async with self.concurrent_requests:
            self._ensure_client()
            conf = self._prepare_request_config(req)
            assert self.client is not None
            async with self.client.stream(**conf) as resp:
                self._handle_failure(resp, on_error)
                yield resp

    def _ensure_client(self):
        if self.client is None:
            self.client = self.client_factory(timeout=self.timeout)
        return self.client

    async def close(self):
        if self.client is None:
            return

        await self.client.aclose()
        self.client = None

    async def __aenter__(self):
        if self.client is None:
            self.client = self.client_factory()
        self.enter_count += 1
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.enter_count -= 1
        if self.enter_count <= 0:
            await self.close()

    @classmethod
    def from_sync_client(cls, client: Client):
        return AsyncClient(
            base_url=client.base_url,
            auth=client.auth,
            logger=client.logger,
            on_error=client.on_error,
            service_urls=client.service_urls,
            timeout=client.timeout,
        )
