from __future__ import annotations

import enum
import functools
import logging
import typing as t
from functools import reduce
from typing import Literal
from urllib.parse import urljoin as urljoin_

from httpx import Response


class MoviciServiceUnavailable(Exception):
    pass


class Service(enum.Enum):
    AUTH = ("auth", "/auth/v1/")
    DATA_ENGINE = ("data_engine", "/data-engine/v4/")
    MODEL_ENGINE = ("model_engine", "/model-engine/v1/")

    @classmethod
    def by_name(cls):
        return {s.value[0]: s for s in cls}

    @classmethod
    def urls(cls):
        return {s: s.value[1] for s in cls}


class Auth:
    def login(self, api: BaseClient):
        raise NotImplementedError

    def __call__(self, config: dict) -> dict:
        raise NotImplementedError


ErrorCallback = t.Callable[[Response], bool]


def parse_service_urls(bases_dict=None, prefix=""):
    if bases_dict is None:
        bases_dict = {}
    service_by_name = Service.by_name()
    rv = {}

    sentinel = object()
    for name, service in service_by_name.items():
        result = bases_dict.get(prefix + name, sentinel)
        if result is None:
            continue
        if result is sentinel:
            rv[service] = service.value[1]
        else:
            rv[service] = result

    return rv


class ISyncClient:
    def request(
        self, req: BaseRequest[T], on_error: t.Optional[ErrorCallback] = None
    ) -> t.Optional[T]:
        raise NotImplementedError

    def stream(self, req: BaseRequest[T], on_error: t.Optional[ErrorCallback] = None):
        raise NotImplementedError


class IAsyncClient:
    async def request(
        self, req: BaseRequest[T], on_error: t.Optional[ErrorCallback] = None
    ) -> t.Optional[T]:
        raise NotImplementedError

    async def stream(self, req: BaseRequest[T], on_error: t.Optional[ErrorCallback] = None):
        raise NotImplementedError

    async def __aenter__(self):
        raise NotImplementedError

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        raise NotImplementedError


class BaseClient:
    auth: t.Union[Auth, None, Literal[False]]

    def __init__(
        self,
        base_url: str,
        auth: t.Union[Auth, None, Literal[False]] = None,
        logger: t.Optional[logging.Logger] = None,
        on_error: t.Optional[ErrorCallback] = None,
        service_urls: t.Optional[t.Dict[Service, str]] = None,
    ):
        self.base_url = base_url
        self.auth = auth
        self.logger = logger
        self.on_error = on_error
        self.service_urls = service_urls if service_urls is not None else parse_service_urls()

    def _handle_failure(self, resp: Response, on_error: t.Optional[ErrorCallback] = None):
        if resp.status_code >= 400:
            run_global_error_callback = True
            if on_error:
                # a "local" error callback can return False to indicate that all error handling
                # has been completed and the global error handling should not take place. We need
                # to specifcally look for False and not just Falsy (ie: None)
                run_global_error_callback = on_error(resp) is not False
            if not run_global_error_callback:
                return
            if self.on_error:
                self.on_error(resp)
            else:
                resp.raise_for_status()

    def resolve_service_url(self, service: t.Optional[Service]) -> str:
        if service is None:
            service_url = ""
        else:
            try:
                service_url = self.service_urls[service]
            except KeyError:
                raise MoviciServiceUnavailable()
        return urljoin(self.base_url, service_url)  # type: ignore[no-any-return]

    def _assert_auth(self, request: BaseRequest[T]):
        if request.auth:
            if self.auth is None:
                raise ValueError(
                    "request is authenticated, but no authenticationprovider configured"
                )

    def _prepare_request_config(self, req: BaseRequest[T]):
        conf = req.generate_config(self)

        if self.auth:
            conf = self.auth(conf)
        if self.logger:
            self.logger.debug(str(conf))
        return conf


T = t.TypeVar("T")


class BaseRequest(t.Generic[T]):
    auth = False

    def generate_config(self, api: BaseClient):
        return self.make_request()

    def make_request(self):
        raise NotImplementedError

    def make_response(self, resp: Response) -> T:
        return resp.json()  # type: ignore[no-any-return]


class Request(BaseRequest):
    auth = True
    service: t.Optional[Service] = None

    def generate_config(self, api: BaseClient):
        request = self.make_request()
        base_url = api.resolve_service_url(self.service)
        return {
            **request,
            "url": urljoin(base_url, request["url"]),
        }


def simple_request(func):
    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        return {"method": "GET", "url": func(*args, **kwargs)}

    return wrapped


def unwrap_envelope(envelope):
    def decorator(cls: Request):
        original = cls.make_response

        def make_response(self, resp: Response):
            result = original(self, resp)  # type: ignore[call-arg]
            return result[envelope]

        cls.make_response = make_response  # type: ignore[method-assign, assignment]
        return cls

    return decorator


def urljoin(*parts):
    return reduce(urljoin_, (str(part) + "/" for part in parts))


def pick(obj, attrs: t.List[str], default=None):
    # TODO: work with dictionaries as well as getattr
    def _get_item_or_attr(obj, key):
        try:
            return obj[key]
        except (KeyError, TypeError):
            return getattr(obj, key, default)

    return {key: _get_item_or_attr(obj, key) for key in attrs}
