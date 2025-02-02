import datetime
import random
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
from typing import List

import sys
from time import sleep

from magictrade.trade_queue import RedisTradeQueue


def init_script(args, name) -> None:
    """
    Some functionality commonly needed in scripts.
    :param args: argparse Namespace from CLI.
    :param name: Name of this runner.
    :return:
    """
    print(f"Starting {name} runner at",
          datetime.datetime.now().isoformat())
    if args.run_probability:
        if random.randint(0, 100) > args.run_probability:
            print("Randomly deciding to not trade today.")
            sys.exit(0)
    if args.random_sleep:
        seconds = random.randint(*args.random_sleep)
        print(f"Sleeping for {seconds}s.")
        sleep(seconds)


def get_parser(name: str) -> ArgumentParser:
    parser = ArgumentParser(description=f"Place {name} trades.",
                            formatter_class=ArgumentDefaultsHelpFormatter)
    parser.add_argument('-q', '--trade-queue', help="Name of the magictrade queue to add trades to.")
    parser.add_argument('-d', '--dry-run', action="store_true", help="Set the dry run flag to check for trade "
                                                                     "signals, but not actually place trades.")
    parser.add_argument('-c', '--trade-count', default=0, type=int,
                        help="Max number of trades to place. 0 for unlimited.")
    parser.add_argument('-n', '--ticker-count', default=0, type=int,
                        help="Max number of tickers to consider. 0 for unlimited.")
    parser.add_argument('-l', '--allocation', type=int, default=1, help="Allocation percentage for each trade")
    parser.add_argument('-p', '--run-probability', type=int,
                        help="Probability (out of 100) that any trades should be placed on a given run.")
    parser.add_argument('-r', '--random-sleep', type=int, nargs=2, metavar=('min', 'max'),
                        help="Range of seconds to randomly sleep before running.")
    parser.add_argument('-a', '--account-id', help='If set, will check existing trades to avoid securities '
                                                   'with active trades.')
    parser.add_argument('-e', '--days', default=0, type=int, help="Place trades that are valid for this many days.")
    return parser


def cli(name, parser: ArgumentParser = None):
    if not parser:
        parser = get_parser(name)
    args = parser.parse_args()
    if not (args.dry_run or args.trade_queue):
        print("Error: Either --trade-queue or --dry-run are required.")
        parser.print_usage()
        sys.exit(1)
    return args


def method_from_name(class_, method_name: str):
    """
    Given an imported class, return the given method pointer.
    :param class_: An imported class containing the method.
    :param method_name: The method name to find.
    :return: The method pointer
    """
    try:
        return getattr(class_, method_name)
    except AttributeError:
        raise NotImplementedError()


class MultiTradeQueue(RedisTradeQueue):
    def __init__(self, queues: List[RedisTradeQueue], single_return: bool = False):
        self.queues = queues
        self.single_return = single_return

    def __getattr__(self, item):
        if item == 'queues':
            return self.queues
        elif item == "queue_name":
            return self.queues[0].queue_name

        def _method(*args, **kwargs):
            results = []
            for queue in self.queues:
                results.append(method_from_name(queue, item)(*args, **kwargs))
            return results[0] if self.single_return else results

        return _method
