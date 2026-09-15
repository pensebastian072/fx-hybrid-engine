"""Thin tastytrade REST client used by precheck and future live rails."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from fx_hybrid_engine.brokers.base import BrokerAccount, BrokerBalance, BrokerOrderRequest, BrokerPosition

JsonObject = dict[str, Any]
HttpRequester = Callable[[str, str, dict[str, str], JsonObject | None], JsonObject]


class TastytradeApiError(RuntimeError):
    """Raised when the tastytrade API returns an unexpected response."""


@dataclass(frozen=True, slots=True)
class TastytradeCredentials:
    client_id: str
    client_secret: str
    refresh_token: str


def _default_request(
    method: str, url: str, headers: dict[str, str], payload: JsonObject | None
) -> JsonObject:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, method=method)
    for key, value in headers.items():
        req.add_header(key, value)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with request.urlopen(req, timeout=15) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise TastytradeApiError(
            f"Tastytrade API {method} {url} failed: {exc.code} {detail}"
        ) from exc
    except error.URLError as exc:
        raise TastytradeApiError(f"Tastytrade API {method} {url} failed: {exc.reason}") from exc
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise TastytradeApiError(
            f"Tastytrade API {method} {url} returned non-JSON content"
        ) from exc


def _extract_access_token(payload: JsonObject) -> str:
    for candidate in (
        payload.get("access_token"),
        payload.get("token"),
        (payload.get("data") or {}).get("access_token")
        if isinstance(payload.get("data"), dict)
        else None,
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    raise TastytradeApiError("Tastytrade token response did not include an access token")


class TastytradeApiClient:
    """OAuth-backed client for a small subset of the tastytrade REST API."""

    name = "tastytrade"

    def __init__(
        self,
        *,
        credentials: TastytradeCredentials,
        oauth_token_url: str,
        accounts_url: str,
        balances_url_template: str,
        requester: HttpRequester | None = None,
    ) -> None:
        self._credentials = credentials
        self._oauth_token_url = oauth_token_url
        self._accounts_url = accounts_url
        self._balances_url_template = balances_url_template
        self._request = requester or _default_request

    def _access_token(self) -> str:
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self._credentials.refresh_token,
            "client_id": self._credentials.client_id,
            "client_secret": self._credentials.client_secret,
        }
        response = self._request("POST", self._oauth_token_url, {}, payload)
        return _extract_access_token(response)

    def _authorized_request(
        self, method: str, url: str, payload: JsonObject | None = None
    ) -> JsonObject:
        token = self._access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        return self._request(method, url, headers, payload)

    def _authorized_get(self, url: str) -> JsonObject:
        return self._authorized_request("GET", url)

    def _account_url(self, account_number: str, suffix: str) -> str:
        balances_url = self._balances_url_template.format(account_number=account_number)
        if balances_url.endswith("/balances"):
            return f"{balances_url.removesuffix('/balances')}/{suffix.lstrip('/')}"
        return f"{balances_url.rstrip('/')}/{suffix.lstrip('/')}"

    def list_accounts(self) -> list[BrokerAccount]:
        payload = self._authorized_get(self._accounts_url)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise TastytradeApiError("Tastytrade accounts response did not include a data object")
        items = data.get("items")
        if not isinstance(items, list):
            raise TastytradeApiError("Tastytrade accounts response did not include an items list")
        accounts: list[BrokerAccount] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            account = item.get("account")
            if not isinstance(account, dict):
                continue
            account_number = account.get("account-number")
            if not isinstance(account_number, str) or not account_number.strip():
                continue
            accounts.append(
                BrokerAccount(
                    account_number=account_number,
                    account_type=(
                        account.get("account-type-name")
                        if isinstance(account.get("account-type-name"), str)
                        else None
                    ),
                    authority_level=(
                        item.get("authority-level")
                        if isinstance(item.get("authority-level"), str)
                        else None
                    ),
                    raw=item,
                )
            )
        if not accounts:
            raise TastytradeApiError(
                "Tastytrade accounts response did not contain any account records"
            )
        return accounts

    def get_balances(self, account_number: str) -> BrokerBalance:
        url = self._balances_url_template.format(account_number=account_number)
        payload = self._authorized_get(url)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise TastytradeApiError("Tastytrade balances response did not include a data object")
        return BrokerBalance(account_number=account_number, raw=data)

    def list_positions(self, account_number: str) -> list[BrokerPosition]:
        payload = self._authorized_get(self._account_url(account_number, "positions"))
        data = payload.get("data")
        items = data if isinstance(data, list) else None
        if items is None:
            raise TastytradeApiError("Tastytrade positions response did not include a data list")
        positions: list[BrokerPosition] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            symbol = item.get("symbol")
            if not isinstance(symbol, str) or not symbol.strip():
                continue
            qty_raw = item.get("quantity", 0.0)
            try:
                quantity = float(qty_raw)
            except (TypeError, ValueError) as exc:
                raise TastytradeApiError(
                    f"Tastytrade position for {symbol} returned non-numeric quantity {qty_raw!r}"
                ) from exc
            direction = str(item.get("quantity-direction", "")).strip().lower()
            if direction == "short":
                quantity = -abs(quantity)
            elif direction == "long":
                quantity = abs(quantity)
            positions.append(
                BrokerPosition(
                    account_number=account_number,
                    symbol=symbol,
                    quantity=quantity,
                    raw=item,
                )
            )
        return positions

    def list_live_orders(self, account_number: str) -> list[JsonObject]:
        payload = self._authorized_get(self._account_url(account_number, "orders/live"))
        data = payload.get("data")
        items = data if isinstance(data, list) else None
        if items is None:
            raise TastytradeApiError("Tastytrade live-orders response did not include a data list")
        return [item for item in items if isinstance(item, dict)]

    def _market_data_url(self, symbol: str) -> str:
        symbol_key = str(symbol).strip()
        if not symbol_key:
            raise TastytradeApiError("Market-data lookup requires a non-empty symbol")
        return f"{self._accounts_url.removesuffix('/customers/me/accounts')}/market-data/quotes/{symbol_key}"

    def get_market_quotes(self, symbols: list[str]) -> dict[str, JsonObject]:
        quotes: dict[str, JsonObject] = {}
        for symbol in symbols:
            key = str(symbol).strip()
            if not key:
                continue
            payload = self._authorized_get(self._market_data_url(key))
            data = payload.get("data")
            quotes[key] = data if isinstance(data, dict) else payload
        return quotes

    def submit_order(self, request: BrokerOrderRequest) -> JsonObject:
        symbol = str(request.symbol).strip()
        side = str(request.side).strip().lower()
        quantity = float(request.quantity)
        if not symbol:
            raise TastytradeApiError("Order submission requires a non-empty symbol")
        if side not in {"buy", "sell"}:
            raise TastytradeApiError(f"Unsupported order side '{request.side}'")
        if quantity <= 0:
            raise TastytradeApiError("Order submission requires quantity > 0")

        payload: JsonObject = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "order_type": str(request.order_type or "market"),
        }
        if request.raw:
            payload.update(request.raw)
        response = self._authorized_request(
            "POST",
            self._account_url(request.account_number, "orders"),
            payload,
        )
        data = response.get("data")
        return data if isinstance(data, dict) else response
