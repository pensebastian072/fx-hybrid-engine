from __future__ import annotations

from fx_hybrid_engine.brokers.base import BrokerOrderRequest
from fx_hybrid_engine.brokers.tastytrade import TastytradeApiClient, TastytradeCredentials


def test_tastytrade_client_parses_accounts_and_balances():
    seen: list[tuple[str, str]] = []

    def _request(method: str, url: str, headers: dict[str, str], payload: dict[str, object] | None):
        seen.append((method, url))
        if url.endswith("/oauth2/token"):
            assert payload is not None
            assert payload["grant_type"] == "refresh_token"
            return {"access_token": "token-123"}
        if url.endswith("/customers/me/accounts"):
            assert headers["Authorization"] == "Bearer token-123"
            return {
                "data": {
                    "items": [
                        {
                            "account": {
                                "account-number": "5WT0001",
                                "account-type-name": "Individual",
                            },
                            "authority-level": "owner",
                        }
                    ]
                }
            }
        if url.endswith("/accounts/5WT0001/balances"):
            assert headers["Authorization"] == "Bearer token-123"
            return {"data": {"cash-balance": "1000.00"}}
        if url.endswith("/accounts/5WT0001/positions"):
            assert headers["Authorization"] == "Bearer token-123"
            return {
                "data": [
                    {
                        "account-number": "5WT0001",
                        "symbol": "/6EM6",
                        "quantity": "2",
                        "quantity-direction": "Long",
                    },
                    {
                        "account-number": "5WT0001",
                        "symbol": "/6BM6",
                        "quantity": "1",
                        "quantity-direction": "Short",
                    },
                ]
            }
        if url.endswith("/accounts/5WT0001/orders/live"):
            assert headers["Authorization"] == "Bearer token-123"
            return {"data": [{"id": "ord-1"}, {"id": "ord-2"}]}
        if url.endswith("/market-data/quotes/6E"):
            assert headers["Authorization"] == "Bearer token-123"
            return {"data": {"symbol": "6E", "bid": "1.11", "ask": "1.12"}}
        if url.endswith("/accounts/5WT0001/orders"):
            assert headers["Authorization"] == "Bearer token-123"
            assert payload is not None
            assert payload["symbol"] == "6E"
            assert payload["side"] == "buy"
            assert payload["quantity"] == 2.0
            return {"data": {"id": "ord-3", "status": "received"}}
        raise AssertionError(f"Unexpected request: {method} {url}")

    client = TastytradeApiClient(
        credentials=TastytradeCredentials(
            client_id="cid", client_secret="secret", refresh_token="refresh"
        ),
        oauth_token_url="https://api.tastytrade.com/oauth2/token",
        accounts_url="https://api.tastytrade.com/customers/me/accounts",
        balances_url_template="https://api.tastytrade.com/accounts/{account_number}/balances",
        requester=_request,
    )

    accounts = client.list_accounts()
    assert [account.account_number for account in accounts] == ["5WT0001"]
    balance = client.get_balances("5WT0001")
    assert balance.account_number == "5WT0001"
    assert balance.raw["cash-balance"] == "1000.00"
    positions = client.list_positions("5WT0001")
    assert [(position.symbol, position.quantity) for position in positions] == [
        ("/6EM6", 2.0),
        ("/6BM6", -1.0),
    ]
    live_orders = client.list_live_orders("5WT0001")
    assert [order["id"] for order in live_orders] == ["ord-1", "ord-2"]
    quotes = client.get_market_quotes(["6E"])
    assert quotes["6E"]["bid"] == "1.11"
    submit = client.submit_order(
        BrokerOrderRequest(
            account_number="5WT0001",
            symbol="6E",
            side="buy",
            quantity=2.0,
        )
    )
    assert submit["id"] == "ord-3"
    assert seen == [
        ("POST", "https://api.tastytrade.com/oauth2/token"),
        ("GET", "https://api.tastytrade.com/customers/me/accounts"),
        ("POST", "https://api.tastytrade.com/oauth2/token"),
        ("GET", "https://api.tastytrade.com/accounts/5WT0001/balances"),
        ("POST", "https://api.tastytrade.com/oauth2/token"),
        ("GET", "https://api.tastytrade.com/accounts/5WT0001/positions"),
        ("POST", "https://api.tastytrade.com/oauth2/token"),
        ("GET", "https://api.tastytrade.com/accounts/5WT0001/orders/live"),
        ("POST", "https://api.tastytrade.com/oauth2/token"),
        ("GET", "https://api.tastytrade.com/market-data/quotes/6E"),
        ("POST", "https://api.tastytrade.com/oauth2/token"),
        ("POST", "https://api.tastytrade.com/accounts/5WT0001/orders"),
    ]
