import random
import traceback
from collections import Counter
from pprint import pprint
from typing import Dict
from typing import Optional

import yaml
from space_tycoon_client import ApiClient
from space_tycoon_client import Configuration
from space_tycoon_client import GameApi
from space_tycoon_client.models.credentials import Credentials
from space_tycoon_client.models.current_tick import CurrentTick
from space_tycoon_client.models.data import Data
from space_tycoon_client.models.destination import Destination
from space_tycoon_client.models.end_turn import EndTurn
from space_tycoon_client.models.move_command import MoveCommand
from space_tycoon_client.models.trade_command import TradeCommand
from space_tycoon_client.models.construct_command import ConstructCommand
from space_tycoon_client.models.player import Player
from space_tycoon_client.models.player_id import PlayerId
from space_tycoon_client.models.ship import Ship
from space_tycoon_client.models.static_data import StaticData
from space_tycoon_client.rest import ApiException

CONFIG_FILE = "config.yml"


class ConfigException(Exception):
    pass


class Game:
    def __init__(self, api_client: GameApi, config: Dict[str, str]):
        self.me: Optional[Player] = None
        self.config = config
        self.client = api_client
        self.player_id = self.login()
        self.static_data: StaticData = self.client.static_data_get()
        self.data: Data = self.client.data_get()
        self.season = self.data.current_tick.season
        self.tick = self.data.current_tick.tick
        # this part is custom logic, feel free to edit / delete
        if self.player_id not in self.data.players:
            raise Exception("Logged as non-existent player")
        self.recreate_me()
        print(f"playing as [{self.me.name}] id: {self.player_id}")

    def recreate_me(self):
        self.me: Player = self.data.players[self.player_id]

    def game_loop(self):
        while True:
            print("-" * 30)
            try:
                print(f"tick {self.tick} season {self.season}")
                self.data: Data = self.client.data_get()
                if self.data.player_id is None:
                    raise Exception("I am not correctly logged in. Bailing out")
                self.game_logic()
                current_tick: CurrentTick = self.client.end_turn_post(EndTurn(
                    tick=self.tick,
                    season=self.season
                ))
                self.tick = current_tick.tick
                self.season = current_tick.season
            except ApiException as e:
                if e.status == 403:
                    print(f"New season started or login expired: {e}")
                    break
                else:
                    raise e
            except Exception as e:
                print(f"!!! EXCEPTION !!! Game logic error {e}")
                print(traceback.format_exc())

    def defend_mothership(self):
        ...

    def trade(self):
        average = {}
        for planet_id, planet in self.data.planets.items():
            for res_id, resource in planet.resources.items():
                if res_id not in average:
                    average[res_id] = []
                else:
                    if resource.buy_price:
                        average[res_id].append(resource.buy_price)
                    if resource.sell_price:
                        average[res_id].append(resource.sell_price)
        for k in average.keys():
            average[k] = sum(average[k]) / len(average[k])

        for ship_id, ship in self.my_ships.items():
            if ship.command is not None:
                if ship.command.type == "trade":
                    if ship.command.amount > 0 and self.data.planets[ship.command.target].resources[ship.command.resource].buy_price:
                        continue
                    elif ship.command.amount < 0 and self.data.planets[ship.command.target].resources[ship.command.resource].sell_price:
                        continue

            if len(ship.resources):
                for planet_id, planet in self.data.planets.items():
                    for res_id, resource in planet.resources.items():
                        if res_id == list(ship.resources.keys())[0] and resource.sell_price and resource.sell_price > average[res_id]:
                            self.commands[ship_id] = TradeCommand(target=planet_id, resource=res_id, amount=-ship.resources[res_id]["amount"])
            else:
                random_planet_id = random.choice(list(self.data.planets.keys()))
                random_planet = self.data.planets[random_planet_id]

                buy_id = 0
                buy_amt = 0
                for res_id, resource in random_planet.resources.items():
                    if ship.ship_class == "2" or ship.ship_class == "3":  # shiper or hauler
                        capacity = self.static_data.ship_classes[ship.ship_class].cargo_capacity
                        if resource.buy_price and resource.amount > 0 and resource.buy_price < average[res_id]:
                            buy_id = res_id
                            buy_amt = min(resource.amount, capacity)
                            break
                else:
                    continue

                print(f"sending {ship_id} to {self.data.planets[random_planet_id].name}({random_planet_id})")
                self.commands[ship_id] = TradeCommand(target=random_planet_id, resource=buy_id, amount=buy_amt)

    def attack(self):
        ...

    def buy_ships(self):
        my_shipyards: Dict[Ship] = {ship_id: ship for ship_id, ship in
                                    self.my_ships.items() if self.static_data.ship_classes[ship.ship_class].shipyard}

        trading_ships_total = 0
        for ship in self.my_ships.values():
            if ship.ship_class == "2" or ship.ship_class == "3":  # shiper or hauler
                trading_ships_total += self.static_data.ship_classes[ship.ship_class].price
        if trading_ships_total < (self.data.players[self.player_id].net_worth.money // 3):
            random_shipyard = random.choice(list(my_shipyards.keys()))
            self.commands[random_shipyard] = ConstructCommand(ship_class="3")

    def game_logic(self):
        # todo throw all this away
        self.recreate_me()
        self.my_ships: Dict[Ship] = {ship_id: ship for ship_id, ship in
                                     self.data.ships.items() if ship.player == self.player_id}
        ship_type_cnt = Counter(
            (self.static_data.ship_classes[ship.ship_class].name for ship in self.my_ships.values()))
        pretty_ship_type_cnt = ', '.join(
            f"{k}:{v}" for k, v in ship_type_cnt.most_common())
        print(f"I have {len(self.my_ships)} ships ({pretty_ship_type_cnt})")

        self.commands = {}
        self.buy_ships()
        self.defend_mothership()
        self.trade()
        self.attack()

        pprint(self.commands) if self.commands else None
        try:
            self.client.commands_post(self.commands)
        except ApiException as e:
            if e.status == 400:
                print("some commands failed")
                print(e.body)

    def login(self) -> str:
        if self.config["user"] == "?":
            raise ConfigException
        if self.config["password"] == "?":
            raise ConfigException
        player, status, headers = self.client.login_post_with_http_info(Credentials(
            username=self.config["user"],
            password=self.config["password"],
        ), _return_http_data_only=False)
        self.client.api_client.cookie = headers['Set-Cookie']
        player: PlayerId = player
        return player.id


def main_loop(api_client, config):
    game_api = GameApi(api_client=api_client)
    while True:
        try:
            game = Game(game_api, config)
            game.game_loop()
            print("season ended")
        except ConfigException as e:
            print(f"User / password was not configured in the config file [{CONFIG_FILE}]")
            return
        except Exception as e:
            print(f"Unexpected error {e}")


def main():
    config = yaml.safe_load(open(CONFIG_FILE))
    print(f"Loaded config file {CONFIG_FILE}")
    print(f"Loaded config values {config}")
    configuration = Configuration()
    if config["host"] == "?":
        print(f"Host was not configured in the config file [{CONFIG_FILE}]")
        return

    configuration.host = config["host"]

    main_loop(ApiClient(configuration=configuration, cookie="SESSION_ID=1"), config)


if __name__ == '__main__':
    main()
