import uuid
from typing import Tuple, Any, List, Dict, Callable

from tdameritrade import TDClient
from tdameritrade.auth import refresh_token as do_refresh

from magictrade.broker import Broker
from magictrade.broker.registry import register_broker
from magictrade.securities import InvalidOptionError, Option, OptionOrder, Position


class TDOption(Option):
    @property
    def id(self):
        return self.data['symbol']

    @property
    def option_type(self) -> str:
        if 'putCall' in self.data:
            return self.data['putCall'].lower()
        return {'P': 'put', 'C': 'call'}[self.data['contractType']]

    @property
    def probability_otm(self) -> float:
        try:
            return 1.0 - abs(self.data['delta'])
        except TypeError:
            return 0.0

    @property
    def strike_price(self) -> float:
        return self.data['strikePrice']

    @property
    def mark_price(self) -> float:
        return self.data['mark']


class TDOptionOrder(OptionOrder):
    @property
    def id(self) -> str:
        return str(self.data['orderId'])

    @property
    def legs(self):
        new_legs = []
        for leg in self.data['orderLegCollection']:
            leg = {**leg, **leg['instrument'],
                   'id': str(uuid.uuid4()),
                   'side': leg['instruction'].split('_')[0].lower()
                   }
            leg.pop('instrument')
            new_legs.append(leg)
        return new_legs


class TDPosition(Position):
    @property
    def quantity(self) -> int:
        return self.data['longQuantity']

    @property
    def symbol(self) -> str:
        return self.data['instrument']['symbol']


@register_broker
class TDAmeritradeBroker(Broker):
    name = 'tdameritrade'
    option = TDOption

    def __init__(self, client_id: str = None, account_id: str = None, access_token: str = None,
                 refresh_token: str = None):
        self.client = TDClient(access_token=access_token, accountIds=[account_id], refresh_token=refresh_token,
                               client_id=client_id)
        if not access_token:
            self.refresh()
        self.client.accounts()
        self._account_id = account_id

    def refresh(self):
        self.client._token = do_refresh(self.client.refresh_token, self.client.client_id)['access_token']

    def get_quote(self, symbol: str) -> float:
        return self.client.quote(symbol)[symbol]['lastPrice']

    def _get_account(self, **kwargs):
        return self.client.accounts(**kwargs)[self._account_id]['securitiesAccount']

    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def balance(self) -> float:
        return self._get_account()['currentBalances']['liquidationValue']

    @property
    def buying_power(self) -> float:
        return self._get_account()['initialBalances']['totalCash']

    def get_value(self) -> float:
        raise NotImplementedError()

    def _get_positions_of_type(self, position_type: str, wrapper: Callable = lambda x: x):
        return [wrapper(p) for p in self._get_account(positions=True)['positions'] if
                p['instrument']['assetType'] == position_type]

    def options_positions(self) -> List:
        return self._get_positions_of_type('OPTION')

    def options_positions_data(self, options: List) -> List:
        return [TDOption({**o, **self.client.quote(o['symbol'])[o['symbol']]}) for o in options]

    def stock_positions(self) -> List:
        return self._get_positions_of_type('EQUITY', lambda x: TDPosition(x))

    @staticmethod
    def _strip_exp(options: Any) -> Any:
        if isinstance(options, dict):
            return {key.split(':')[0]: value for key, value in options.items()}
        else:
            return [d.split(':')[0] for d in options]

    def get_options(self, symbol: str) -> Dict:
        options = self.client.options(symbol)
        return {
            'expiration_dates': self._strip_exp(options['callExpDateMap'].keys()),
            'put': self._strip_exp(options['putExpDateMap']),
            'call': self._strip_exp(options['callExpDateMap'])
        }

    @staticmethod
    def filter_options(options: Dict, exp_dates: List = [], option_type: str = None):
        if exp_dates:
            puts = {}
            calls = {}
            for exp_date in exp_dates:
                puts.update(options['put'][exp_date])
                calls.update(options['call'][exp_date])
            return {
                'put': puts,
                'call': calls,
            }
        elif option_type:
            return [TDOption(option[0]) for option in options[option_type.lower()].values()]

    def options_transact(self, legs: List[Dict], direction: str, price: float,
                         quantity: int, effect: str = 'open', time_in_force: str = 'DAY',
                         **kwargs) -> OptionOrder:
        if effect not in ('open', 'close'):
            raise InvalidOptionError()

        time_in_force = {
            'gtc': 'GOOD_TILL_CANCEL',
            'gfd': 'DAY',
            'fok': 'FILL_OR_KILL'
        }.get(time_in_force, time_in_force)

        order_type, effect = {
            'open': ('NET_CREDIT', 'TO_OPEN'),
            'close': ('NET_DEBIT', 'TO_CLOSE'),
        }[effect]

        if len(legs) == 1:
            order_type = 'LIMIT'

        strategies = {
            'credit_spread': 'VERTICAL',
            'iron_condor': 'IRON_CONDOR',
            'iron_butterfly': 'CUSTOM',
        }

        strategy = strategies.get(kwargs.get('strategy'), kwargs.get('strategy'))

        new_legs = []
        for leg in legs:
            leg, action = self.parse_leg(leg)
            new_legs.append({
                'instruction': '_'.join((action.upper(), effect)),
                'quantity': quantity * leg.get('quantity', 1),
                'instrument': {
                    'symbol': leg.id,
                    'assetType': 'OPTION',
                },
            })

        return TDOptionOrder(self.client.trade_options(self._account_id, new_legs,
                                                       quantity, round(price, ndigits=2),
                                                       order_type=order_type, duration=time_in_force,
                                                       strategy=strategy))

    def buy(self, symbol: str, quantity: int) -> Tuple[str, Any]:
        raise NotImplementedError

    def sell(self, symbol: str, quantity: int) -> Tuple[str, Any]:
        raise NotImplementedError

    def replace_order(self, order: str):
        pass

    def get_order(self, order: str):
        pass

    def cancel_order(self, ref_id: str):
        pass

    @staticmethod
    def leg_in_options(leg: Dict, options: Dict) -> bool:
        for option in options:
            if option['instrument']['symbol'] == leg['symbol']:
                return True
        return False
