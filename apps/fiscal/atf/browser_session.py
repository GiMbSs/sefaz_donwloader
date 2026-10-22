"""Keep Playwright's event loop off the Django worker's database thread."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import AbstractContextManager
from queue import Empty, Queue
from typing import TYPE_CHECKING, Any, TypeVar

from .types import IssuerIdentity, Period, SubmissionReceipt

if TYPE_CHECKING:
    from .nfce_browser import NfceBrowserQuery

T = TypeVar("T")


class BrowserSession:
    def __init__(
        self,
        factory: Callable[
            [Callable[[], None]], AbstractContextManager[NfceBrowserQuery]
        ],
        *,
        heartbeat: Callable[[], Any] | None,
    ) -> None:
        self.heartbeat = heartbeat
        self.closed = False
        self._pulses: Queue[Future[None]] = Queue()
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="atf-nfce-browser"
        )
        self._query: NfceBrowserQuery
        self._context: AbstractContextManager[NfceBrowserQuery]

        def start() -> None:
            self._context = factory(self._pulse)
            self._query = self._context.__enter__()

        try:
            self._call(start)
        except BaseException:
            self.closed = True
            self._executor.shutdown(wait=True, cancel_futures=True)
            raise

    def _pulse(self) -> None:
        # Only the caller thread may touch its database connection/transaction.
        acknowledgement: Future[None] = Future()
        self._pulses.put(acknowledgement)
        acknowledgement.result()

    def _call(self, action: Callable[[], T]) -> T:
        result = self._executor.submit(action)
        while not result.done():
            try:
                acknowledgement = self._pulses.get(timeout=0.1)
            except Empty:
                continue
            try:
                if self.heartbeat:
                    self.heartbeat()
            except BaseException as error:
                acknowledgement.set_exception(error)
            else:
                acknowledgement.set_result(None)
        return result.result()

    def lookup_issuer(self, cnpj: str) -> IssuerIdentity:
        return self._call(lambda: self._query.lookup_issuer(cnpj))

    def submit_query(
        self, issuer: IssuerIdentity, period: Period, format: str
    ) -> SubmissionReceipt:
        return self._call(lambda: self._query.submit_query(issuer, period, format))

    def prepare_query(
        self, issuer: IssuerIdentity, period: Period, format: str
    ) -> None:
        self._call(lambda: self._query.prepare_query(issuer, period, format))

    def close(self) -> None:
        if not self.closed:
            try:
                self._call(lambda: self._context.__exit__(None, None, None))
            finally:
                self.closed = True
                self._executor.shutdown(wait=True, cancel_futures=True)
