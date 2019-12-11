import datetime
from typing import Dict

from magictrade import storage


class TradeQueue:
    def __init__(self, queue_name: str):
        self.queue_name = queue_name
        self.index = 0
        self._stage = []

    def _data_name(self, identifer: str) -> str:
        return "{}:{}".format(self.queue_name, identifer)

    def __iter__(self):
        return storage.lrange(self.queue_name, 0, -1)

    def __next__(self):
        if self.index >= self.__len__():
            raise StopIteration
        result = storage.lindex(self.queue_name, self.index)
        self.index += 1
        return result

    def __len__(self):
        return storage.llen(self.queue_name)

    def __repr__(self):
        return self.__iter__()

    def set_data(self, identifier: str, trade: Dict):
        storage.hmset(self._data_name(identifier), trade)

    def add(self, identifier: str, trade: Dict):
        storage.lpush(self.queue_name, identifier)
        self.set_data(identifier, trade)

    def set_status(self, identifier: str, status: str):
        storage.set("{}:status:{}".format(self.queue_name, identifier), status)

    def get_status(self, identifier: str) -> str:
        return storage.get("{}:status:{}".format(self.queue_name, identifier))

    def add_failed(self, identifier: str, error: str):
        storage.lpush(self.queue_name + "-failed", identifier)
        self.set_status(identifier, error)

    def stage_trade(self, identifier: str):
        self._stage.append(identifier)

    def pop(self):
        identifier = storage.rpop(self.queue_name)
        trade = self.get_data(identifier)
        return identifier, trade

    def get_data(self, identifier: str):
        return storage.hgetall(self._data_name(identifier))

    def get_allocation(self, new: bool = False) -> int:
        return int(storage.get("{}:{}allocation".format(self.queue_name, "new_" if new else ""))) or 0

    def pop_new_allocation(self) -> int:
        new_allocation = self.get_allocation(new=True)
        storage.delete(self.queue_name + ":new_allocation")
        return new_allocation

    def set_current_usage(self, buying_power: float, balance: float):
        storage.set(self.queue_name + ":current_usage", f"{buying_power}/{balance}")

    def delete_current_usage(self):
        storage.delete(self.queue_name + ":current_usage")

    def heartbeat(self):
        storage.set(self.queue_name + ":heartbeat", datetime.datetime.now().timestamp())

    def staged_to_queue(self):
        while self._stage:
            storage.lpush(self.queue_name, self._stage.pop())

    def send_trade(self, args: Dict) -> str:
        from magictrade.utils import generate_identifier
        identifier = generate_identifier(args['symbol'])
        self.add(identifier, args)
        return identifier
