import logging
from typing import Union

from py_order_utils.model import SignedOrder

from .order_builder.builder import OrderBuilder

from .headers.headers import create_level_1_headers, create_level_2_headers
from .order_builder.constants import BUY, SELL
from .signer import Signer

from .endpoints import (
    CANCEL,
    CANCEL_ALL,
    CREATE_API_KEY,
    DELETE_API_KEY,
    DERIVE_API_KEY,
    GET_API_KEYS,
    GET_LAST_TRADE_PRICE,
    GET_ORDER,
    GET_ORDER_BOOK,
    MID_POINT,
    ORDERS,
    POST_ORDER,
    PRICE,
    TIME,
    TRADES,
    GET_MARKETS,
    GET_MARKET
)
from .clob_types import (
    ApiCreds,
    FilterParams,
    OrderArgs,
    RequestArgs,
)
from .exceptions import PolyException
from .http_helpers.helpers import add_query_params, delete, get, post
from py_order_utils.config import get_contract_config
from py_order_utils.model import BUY as UtilsBuy
from .constants import L0, L1, L1_AUTH_UNAVAILABLE, L2, L2_AUTH_UNAVAILABLE
from .order_builder.constants import BUY, SELL


class ClobClient:
    def __init__(
        self,
        host: str,
        chain_id: int = None,
        key: str = None,
        creds: ApiCreds = None,
        signature_type: int = None,
        funder: str = None,
    ):
        """
        Initializes the clob client
        The client can be started in 3 modes:
        1) Level 0: Requires only the clob host url
                    Allows access to open CLOB endpoints

        2) Level 1: Requires the host, chain_id and a private key.
                    Allows access to L1 authenticated endpoints + all unauthenticated endpoints

        3) Level 2: Requires the host, chain_id, a private key, and Credentials.
                    Allows access to all endpoints
        """
        self.host = host[0:-1] if host.endswith("/") else host
        self.signer = Signer(key, chain_id) if key else None
        self.creds = creds
        self.mode = self._get_client_mode()
        if chain_id:
            self.contract_config = get_contract_config(chain_id)
        if self.signer:
            self.builder = OrderBuilder(
                self.signer, sig_type=signature_type, funder=funder
            )
        self.logger = logging.getLogger(self.__class__.__name__)

    def get_address(self):
        """
        Returns the public address of the signer
        """
        return self.signer.address() if self.signer else None

    def get_collateral_address(self):
        """
        Returns the collateral token address
        """
        if self.contract_config:
            return self.contract_config.get_collateral()

    def get_conditional_address(self):
        """
        Returns the conditional token address
        """
        if self.contract_config:
            return self.contract_config.get_conditional()

    def get_exchange_address(self):
        """
        Returns the exchange address
        """
        if self.contract_config:
            return self.contract_config.get_exchange()

    def get_ok(self):
        """
        Health check: Confirms that the server is up
        Does not need authentication
        """
        return get("{}/".format(self.host))

    def get_server_time(self):
        """
        Returns the current timestamp on the server
        Does not need authentication
        """
        return get("{}{}".format(self.host, TIME))

    def create_api_key(self, nonce: int = None):
        """
        Creates a new CLOB API key for the given
        """
        self.assert_level_1_auth()

        endpoint = "{}{}".format(self.host, CREATE_API_KEY)
        headers = create_level_1_headers(self.signer, nonce)

        creds = post(endpoint, headers=headers)
        self.logger.info(creds)
        return creds

    def derive_api_key(self, nonce: int = None):
        """
        Derives an already existing CLOB API key for the given address and nonce
        """
        self.assert_level_1_auth()

        endpoint = "{}{}".format(self.host, DERIVE_API_KEY)
        headers = create_level_1_headers(self.signer, nonce)

        creds = get(endpoint, headers=headers)
        self.logger.info(creds)
        return creds

    def get_api_keys(self):
        """
        Gets the available API keys for this address
        Level 2 Auth required
        """
        self.assert_level_2_auth()

        request_args = RequestArgs(method="GET", request_path=GET_API_KEYS)
        headers = create_level_2_headers(self.signer, self.creds, request_args)
        return get("{}{}".format(self.host, GET_API_KEYS), headers=headers)

    def delete_api_key(self):
        """
        Deletes an API key
        Level 2 Auth required
        """
        self.assert_level_2_auth()

        request_args = RequestArgs(method="DELETE", request_path=DELETE_API_KEY)
        headers = create_level_2_headers(self.signer, self.creds, request_args)
        return delete("{}{}".format(self.host, DELETE_API_KEY), headers=headers)

    def get_midpoint(self, token_id: str):
        """
        Get the mid market price for the given market
        """
        return get("{}{}?token_id={}".format(self.host, MID_POINT, token_id))

    def get_price(self, token_id: str, side: Union[BUY, SELL]):
        """
        Get the market price for the given market
        """
        return get("{}{}?token_id={}&side={}".format(self.host, PRICE, token_id, side))

    def create_order(self, order_args: OrderArgs):
        """
        Creates and signs an order
        Level 2 Auth required
        """
        self.assert_level_2_auth()

        return self.builder.create_order(order_args)

    def post_order(self, order: SignedOrder):
        """
        Posts the order
        """
        self.assert_level_2_auth()
        body = {"order": order.dict(), "owner": self.creds.api_key, "orderType": "GTC"}
        headers = create_level_2_headers(
            self.signer,
            self.creds,
            RequestArgs(method="POST", request_path=POST_ORDER, body=body),
        )
        return post("{}{}".format(self.host, POST_ORDER), headers=headers, data=body)

    def create_and_post_order(self, order_args: OrderArgs):
        """
        Utility function to create and publish an order
        """
        order = self.create_order(order_args)
        return self.post_order(order)

    def cancel(self, order_id: str):
        """
        Cancels an order
        Level 2 Auth required
        """
        self.assert_level_2_auth()
        body = {"orderID": order_id}

        request_args = RequestArgs(method="DELETE", request_path=CANCEL, body=body)
        headers = create_level_2_headers(self.signer, self.creds, request_args)
        return delete("{}{}".format(self.host, CANCEL), headers=headers, data=body)

    def cancel_all(self):
        """
        Cancels all available orders for the user
        Level 2 Auth required
        """
        self.assert_level_2_auth()
        request_args = RequestArgs(method="DELETE", request_path=CANCEL_ALL)
        headers = create_level_2_headers(self.signer, self.creds, request_args)
        return delete("{}{}".format(self.host, CANCEL_ALL), headers=headers)

    def get_orders(self, params: FilterParams = None):
        """
        Gets orders for the API key
        Requires Level 2 authentication
        """
        self.assert_level_2_auth()
        request_args = RequestArgs(method="GET", request_path=ORDERS)
        headers = create_level_2_headers(self.signer, self.creds, request_args)
        url = add_query_params("{}{}".format(self.host, ORDERS), params)
        return get(url, headers=headers)

    def get_order_book(self, token_id: str):
        """
        Fetches the orderbook for the token_id
        """
        return get("{}{}?token_id={}".format(self.host, GET_ORDER_BOOK, token_id))

    def get_order(self, order_id: str):
        """
        Fetches the order corresponding to the order_id
        Requires Level 2 authentication
        """
        self.assert_level_2_auth()
        endpoint = "{}{}".format(GET_ORDER, order_id)
        request_args = RequestArgs(method="GET", request_path=endpoint)
        headers = create_level_2_headers(self.signer, self.creds, request_args)
        return get("{}{}".format(self.host, endpoint), headers=headers)

    def get_trades(self, params: FilterParams = None):
        """
        Fetches the trade history for a user
        Requires Level 2 authentication
        """
        self.assert_level_2_auth()
        request_args = RequestArgs(method="GET", request_path=TRADES)
        headers = create_level_2_headers(self.signer, self.creds, request_args)
        url = add_query_params("{}{}".format(self.host, TRADES), params)
        return get(url, headers=headers)

    def get_last_trade_price(self, token_id: str):
        """
        Fetches the last trade price token_id
        """
        return get("{}{}?token_id={}".format(self.host, GET_LAST_TRADE_PRICE, token_id))

    def get_markets(self):
        """
        Get all available CLOB markets
        """
        return get("{}{}".format(self.host, GET_MARKETS))

    def get_market(self, condition_id: str):
        """
        Get the given CLOB market
        """
        return get("{}{}{}".format(self.host, GET_MARKET, condition_id))

    def assert_level_1_auth(self):
        """
        Level 1 Poly Auth
        """
        if self.mode < L1:
            raise PolyException(L1_AUTH_UNAVAILABLE)

    def assert_level_2_auth(self):
        """
        Level 2 Poly Auth
        """
        if self.mode < L2:
            raise PolyException(L2_AUTH_UNAVAILABLE)

    def _get_client_mode(self):
        if self.signer is not None and self.creds is not None:
            return L2
        if self.signer is not None:
            return L1
        return L0
