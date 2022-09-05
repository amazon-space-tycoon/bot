import math
import random
import time
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
from space_tycoon_client.models.attack_command import AttackCommand
from space_tycoon_client.models.player import Player
from space_tycoon_client.models.player_id import PlayerId
from space_tycoon_client.models.ship import Ship
from space_tycoon_client.models.static_data import StaticData
from space_tycoon_client.rest import ApiException

CONFIG_FILE = "config.yml"


def compute_distance(a, b):
    (xa, ya) = a
    (xb, yb) = b
    return math.sqrt((xa-xb)**2 + (ya-yb)**2)


class ConfigException(Exception):
    pass


def normalize_vec(vec):
    ln = math.sqrt(vec[0]**2 + vec[1]**2)
    if ln != 0:
        vec[0] /= ln
        vec[1] /= ln
    return vec


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

        self.planet_neighbors = {planet_id: [(neigh_id, neigh)
                                             for neigh_id, neigh in self.data.planets.items()
                                             if compute_distance(planet.position, neigh.position) < 300]
                                 for planet_id, planet in self.data.planets.items()}
        self.last_enemy_target = None

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
                start = time.time()
                self.game_logic()
                print(time.time() - start)
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

    def trade(self):
        currently_buying = {}

        for ship_id, ship in self.my_traders.items():
            nearest_enemy_center = [[], []]
            for enemy in self.other_ships.values():
                if enemy.ship_class == "1" or enemy.ship_class == "4" or enemy.ship_class == "5":
                    if compute_distance(enemy.position, ship.position) < 75:
                        nearest_enemy_center[0].append(enemy.position[0])
                        nearest_enemy_center[1].append(enemy.position[1])

            if nearest_enemy_center[0]:
                nearest_enemy_center[0] = sum(nearest_enemy_center[0]) / len(nearest_enemy_center[0])
                nearest_enemy_center[1] = sum(nearest_enemy_center[1]) / len(nearest_enemy_center[1])

                avoid_vec = normalize_vec([ship.position[0] - nearest_enemy_center[0],
                                           ship.position[1] - nearest_enemy_center[1]])
                if self.center[0]:
                    center_vec = normalize_vec([self.center[0] - ship.position[0],
                                                self.center[1] - ship.position[1]])
                    avoid_vec = normalize_vec([avoid_vec[0] + center_vec[0] * 0.5,
                                               avoid_vec[1] + center_vec[1] * 0.5])

                map_center_vec = normalize_vec([-ship.position[0],
                                                -ship.position[1]])
                avoid_vec = normalize_vec([avoid_vec[0] + map_center_vec[0] * 0.3,
                                           avoid_vec[1] + map_center_vec[1] * 0.3])

                self.commands[ship_id] = MoveCommand(destination=Destination(coordinates=[
                    int(ship.position[0] + avoid_vec[0] * 100),
                    int(ship.position[1] + avoid_vec[1] * 100),
                ]))

                continue

            ship_capacity = self.static_data.ship_classes[ship.ship_class].cargo_capacity

            if len(ship.resources):
                best_trade = 0.
                best_sell_id = ""
                best_sell_res = ""

                for sell_planet_id, sell_planet in self.data.planets.items():
                    for ship_res_id, ship_resource in ship.resources.items():
                        for sell_res_id, sell_resource in sell_planet.resources.items():
                            if ship_res_id != sell_res_id:
                                continue
                            if not sell_resource.sell_price:
                                continue

                            gain_raw = sell_resource.sell_price * ship_resource["amount"]
                            total_distance = compute_distance(ship.position, sell_planet.position)
                            if self.mothership:
                                total_distance += compute_distance(sell_planet.position, self.data.ships[self.mothership].position) * self.center_dist_cost
                            elif self.center[0]:
                                total_distance += compute_distance(sell_planet.position, self.center) * self.center_dist_cost

                            gain = float(gain_raw) / float(total_distance) if total_distance != 0 else gain_raw * 1000.
                            if gain > best_trade:
                                best_trade = gain
                                best_sell_id = sell_planet_id
                                best_sell_res = sell_res_id

                if best_trade:
                    cmd = TradeCommand(target=best_sell_id,
                                       resource=best_sell_res,
                                       amount=-ship.resources[best_sell_res]["amount"])
                    if ship.command and \
                       ship.command.target == cmd.target and \
                       ship.command.resource == cmd.resource and \
                       ship.command.amount == cmd.amount:
                        continue

                    print(f"sending {ship_id} to {self.data.planets[best_sell_id].name}({best_sell_id})")
                    self.commands[ship_id] = cmd
            else:
                best_trade = 0.
                best_buy_id = ""
                best_buy_res = ""
                best_buy_amt = 0

                for buy_planet_id, buy_planet in self.data.planets.items():
                    for sell_planet_id, sell_planet in self.planet_neighbors[buy_planet_id]:
                        for buy_res_id, buy_resource in buy_planet.resources.items():
                            for sell_res_id, sell_resource in sell_planet.resources.items():
                                if buy_res_id != sell_res_id:
                                    continue
                                if not buy_resource.buy_price:
                                    continue
                                if not sell_resource.sell_price:
                                    continue
                                if not buy_resource.amount:
                                    continue

                                max_amt = min(buy_resource.amount - currently_buying.get((
                                    buy_planet_id,
                                    buy_res_id
                                ), 0), ship_capacity)
                                gain_raw = (sell_resource.sell_price - buy_resource.buy_price) * max_amt
                                total_distance = compute_distance(ship.position, buy_planet.position) + \
                                    compute_distance(buy_planet.position, sell_planet.position)
                                if self.mothership:
                                    total_distance += compute_distance(buy_planet.position, self.data.ships[self.mothership].position) * self.center_dist_cost
                                    total_distance += compute_distance(sell_planet.position, self.data.ships[self.mothership].position) * self.center_dist_cost
                                elif self.center[0]:
                                    total_distance += compute_distance(buy_planet.position, self.center) * self.center_dist_cost
                                    total_distance += compute_distance(sell_planet.position, self.center) * self.center_dist_cost

                                gain = float(gain_raw) / float(total_distance)
                                if gain > best_trade:
                                    best_trade = gain
                                    best_buy_id = buy_planet_id
                                    best_buy_res = buy_res_id
                                    best_buy_amt = max_amt

                if best_trade:
                    currently_buying_key = (best_buy_id, best_buy_res)
                    if currently_buying_key not in currently_buying:
                        currently_buying[currently_buying_key] = 0

                    currently_buying[currently_buying_key] += best_buy_amt

                    cmd = TradeCommand(target=best_buy_id, resource=best_buy_res, amount=best_buy_amt)
                    if ship.command and \
                       ship.command.target == cmd.target and \
                       ship.command.resource == cmd.resource and \
                       ship.command.amount == cmd.amount:
                        continue

                    print(f"sending {ship_id} to {self.data.planets[best_buy_id].name}({best_buy_id})")
                    self.commands[ship_id] = TradeCommand(target=best_buy_id,
                                                          resource=best_buy_res,
                                                          amount=best_buy_amt)

    def attack(self):
        my_furthest_ship_dist = 0.
        for ship_id, ship in self.my_traders.items():
            dist = compute_distance(ship.position, self.center)
            if dist > my_furthest_ship_dist:
                my_furthest_ship_dist = dist

        defense_dist = max(100, my_furthest_ship_dist * 2.5)

        if self.mothership:
            if self.closest_enemy_ship and \
               compute_distance(self.data.ships[self.closest_enemy_ship].position, self.center) < defense_dist:
                self.commands[self.mothership] = AttackCommand(target=self.closest_enemy_ship)
                self.last_enemy_target = self.closest_enemy_ship
            # for enemy_id, enemy in self.other_ships.items():
            #     if compute_distance(enemy.position, self.data.ships[self.mothership].position) < 20:
            #         self.commands[self.mothership] = AttackCommand(target=enemy_id)
            #         break
            else:
                if self.center[0]:
                    self.commands[self.mothership] = MoveCommand(destination=Destination(coordinates=self.center))
                self.last_enemy_target = None

        for ship_id, ship in self.my_fighters.items():
            if self.last_enemy_target and \
               compute_distance(self.data.ships[self.last_enemy_target].position, ship.position) < 20:
                self.commands[ship_id] = AttackCommand(target=self.last_enemy_target)
            elif self.closest_enemy_ship:
                closest_enemy_ship = self.data.ships[self.closest_enemy_ship]
                dist_center = compute_distance(closest_enemy_ship.position, self.center)
                dist_ship = compute_distance(closest_enemy_ship.position, ship.position)
                if dist_ship < 20 or (
                   dist_center < defense_dist and (not self.mothership or
                                                   closest_enemy_ship.ship_class == "2" or
                                                   closest_enemy_ship.ship_class == "3")):
                    self.commands[ship_id] = AttackCommand(target=self.closest_enemy_ship)
                elif dist < defense_dist and self.mothership:
                    self.commands[ship_id] = MoveCommand(destination=Destination(target=self.mothership))
                else:
                    if self.center[0]:
                        self.commands[ship_id] = MoveCommand(destination=Destination(coordinates=self.center))
            else:
                if self.center[0]:
                    self.commands[ship_id] = MoveCommand(destination=Destination(coordinates=self.center))

    def buy_ships(self):
        if not self.my_shipyards:
            return

        my_net_worth = self.data.players[self.player_id].net_worth
        my_money = my_net_worth.money
        my_total = my_net_worth.total

        # keep some money for trading
        if len(self.other_ships):
            extra = max(500000, (my_total - 10000000) // 5)
        else:
            extra = len(self.my_traders) * 10000

        if len(self.other_ships):
            fighters_count = sum(1 for ship in self.my_fighters.values() if ship.ship_class == "4")
            bombers_count = sum(1 for ship in self.my_fighters.values() if ship.ship_class == "5")
            traders_count = len(self.my_traders)
            want_fighters = traders_count // 4 - 1
            want_bombers = traders_count // 5 + 1

            buy_fighter = None
            if bombers_count < want_bombers:
                buy_fighter = "5"
            elif fighters_count < want_fighters:
                buy_fighter = "4"

            # we want more fighters!
            if buy_fighter:
                if my_money > self.static_data.ship_classes[buy_fighter].price + extra:
                    shipyard = None
                    if self.mothership:
                        shipyard = self.mothership
                    elif self.my_shipyards:
                        shipyard = random.choice(list(self.my_shipyards.keys()))

                    if shipyard:
                        self.commands[shipyard] = ConstructCommand(ship_class=buy_fighter)
                return

        # no fighters needed, buy more traders
        if my_total > 8000000:
            # hauler
            buy_trader = "2"
        else:
            # shipper
            buy_trader = "3"

        if my_money > self.static_data.ship_classes[buy_trader].price + extra:
            shipyard = None
            if self.mothership:
                shipyard = self.mothership
            elif self.my_shipyards:
                shipyard = random.choice(list(self.my_shipyards.keys()))

            if shipyard:
                self.commands[shipyard] = ConstructCommand(ship_class=buy_trader)

    def calculate_center(self):
        center = [[], []]
        for ship in self.my_traders.values():
            center[0].append(ship.position[0])
            center[1].append(ship.position[1])

        if center[0]:
            center[0] = int(sum(center[0]) / len(center[0]))
            center[1] = int(sum(center[1]) / len(center[1]))
        else:
            center = [0, 0]

        return center

    def calculate_closest_enemy_ship(self):
        closest_enemy_ship = None
        closest_enemy_ship_dist = 1000000.

        for enemy_id, enemy in self.other_ships.items():
            dist = compute_distance(enemy.position, self.center)
            if self.last_enemy_target and enemy_id == self.last_enemy_target:
                dist -= 150
            elif enemy.ship_class == "1":
                dist += 25
            elif enemy.ship_class == "2" or enemy.ship_class == "3":
                dist += 100

            if dist < closest_enemy_ship_dist:
                closest_enemy_ship_dist = dist
                closest_enemy_ship = enemy_id

        return closest_enemy_ship

    def game_logic(self):
        # todo throw all this away
        self.recreate_me()
        self.my_ships: Dict[Ship] = {ship_id: ship for ship_id, ship in
                                     self.data.ships.items() if ship.player == self.player_id}
        self.other_ships: Dict[Ship] = {ship_id: ship for ship_id, ship in
                                        self.data.ships.items() if ship.player != self.player_id}

        self.my_fighters = {ship_id: ship for ship_id, ship in
                            self.my_ships.items() if ship.ship_class == "4" or ship.ship_class == "5"}
        self.my_traders = {ship_id: ship for ship_id, ship in
                           self.my_ships.items() if ship.ship_class == "2" or ship.ship_class == "3"}
        self.my_shipyards = {ship_id: ship for ship_id, ship in
                             self.my_ships.items() if self.static_data.ship_classes[ship.ship_class].shipyard}

        mothership_list = [ship_id for ship_id, ship in self.my_ships.items() if ship.ship_class == "1"]
        self.mothership = mothership_list[0] if mothership_list else None

        self.center = self.calculate_center()
        self.closest_enemy_ship = self.calculate_closest_enemy_ship()

        if self.closest_enemy_ship:
            if self.center[0]:
                dist = compute_distance(self.center, self.data.ships[self.closest_enemy_ship].position)
                if dist != 0:
                    self.center_dist_cost = 1000 / dist
                else:
                    self.center_dist_cost = 1000
            else:
                self.center_dist_cost = 1
        else:
            self.center_dist_cost = 0

        ship_type_cnt = Counter(
            (self.static_data.ship_classes[ship.ship_class].name for ship in self.my_ships.values()))
        pretty_ship_type_cnt = ', '.join(
            f"{k}:{v}" for k, v in ship_type_cnt.most_common())
        print(f"I have {len(self.my_ships)} ships ({pretty_ship_type_cnt})")

        self.commands = {}

        self.trade()
        self.attack()
        self.buy_ships()

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
