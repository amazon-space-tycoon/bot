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
from space_tycoon_client.models.repair_command import RepairCommand
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
            # enemy ship avoidance
            # calculate nearest enemies average position
            nearest_enemy_center = [[], []]
            for enemy in self.other_ships.values():
                if enemy.ship_class == "1" or enemy.ship_class == "4" or enemy.ship_class == "5":
                    if compute_distance(enemy.position, ship.position) < 75:
                        nearest_enemy_center[0].append(enemy.position[0])
                        nearest_enemy_center[1].append(enemy.position[1])

            # if there are enemies nearby
            if nearest_enemy_center[0]:
                nearest_enemy_center[0] = sum(nearest_enemy_center[0]) / len(nearest_enemy_center[0])
                nearest_enemy_center[1] = sum(nearest_enemy_center[1]) / len(nearest_enemy_center[1])

                # run away from their average position
                avoid_vec = normalize_vec([ship.position[0] - nearest_enemy_center[0],
                                           ship.position[1] - nearest_enemy_center[1]])
                # if we have a mothership, steer towards it for defense
                if self.mothership:
                    mothership = self.data.ships[self.mothership]
                    mothership_vec = normalize_vec([mothership.position[0] - ship.position[0],
                                                    mothership.position[1] - ship.position[1]])
                    avoid_vec = normalize_vec([avoid_vec[0] + mothership_vec[0] * 0.5,
                                               avoid_vec[1] + mothership_vec[1] * 0.5])
                # if not, steer using our traders average position
                elif self.center[0]:
                    center_vec = normalize_vec([self.center[0] - ship.position[0],
                                                self.center[1] - ship.position[1]])
                    # if we have defense in our average position, steer towards it
                    if self.my_fighters_and_mothership:
                        avoid_vec = normalize_vec([avoid_vec[0] + center_vec[0] * 0.5,
                                                   avoid_vec[1] + center_vec[1] * 0.5])
                    # otherwise steer away from others
                    else:
                        avoid_vec = normalize_vec([avoid_vec[0] - center_vec[0] * 0.5,
                                                   avoid_vec[1] - center_vec[1] * 0.5])

                # if we have defense, also steer slightly towards the center of the galaxy
                if self.my_fighters_and_mothership:
                    map_center_vec = normalize_vec([-ship.position[0],
                                                    -ship.position[1]])
                # otherwise lead enemy ships outside of the galaxy
                else:
                    map_center_vec = normalize_vec([ship.position[0],
                                                    ship.position[1]])

                avoid_vec = normalize_vec([avoid_vec[0] + map_center_vec[0] * 0.3,
                                           avoid_vec[1] + map_center_vec[1] * 0.3])

                # run away!
                self.commands[ship_id] = MoveCommand(destination=Destination(coordinates=[
                    int(ship.position[0] + avoid_vec[0] * 100),
                    int(ship.position[1] + avoid_vec[1] * 100),
                ]))

                continue

            ship_capacity = self.static_data.ship_classes[ship.ship_class].cargo_capacity

            # we have resources that we can sell
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
                            # if we have a mothership, try to keep close
                            if self.mothership:
                                total_distance += compute_distance(sell_planet.position, self.data.ships[self.mothership].position) * self.center_dist_cost
                            # if not, but we have other fighters, try to keep close as well
                            elif self.my_fighters and self.center[0]:
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
                    # don't resend the same command
                    if ship.command and \
                       ship.command.type == "trade" and \
                       ship.command.target == cmd.target and \
                       ship.command.resource == cmd.resource and \
                       ship.command.amount == cmd.amount:
                        continue

                    print(f"sending {ship_id} to {self.data.planets[best_sell_id].name}({best_sell_id})")
                    self.commands[ship_id] = cmd
            # we are looking for resources to buy
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
                                # if we have a mothership, try to keep close
                                if self.mothership:
                                    total_distance += compute_distance(buy_planet.position, self.data.ships[self.mothership].position) * self.center_dist_cost
                                    total_distance += compute_distance(sell_planet.position, self.data.ships[self.mothership].position) * self.center_dist_cost
                                # if not, but we have other fighters, try to keep close as well
                                elif self.my_fighters and self.center[0]:
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
                    # don't resend the same command
                    if ship.command and \
                       ship.command.type == "trade" and \
                       ship.command.target == cmd.target and \
                       ship.command.resource == cmd.resource and \
                       ship.command.amount == cmd.amount:
                        continue

                    print(f"sending {ship_id} to {self.data.planets[best_buy_id].name}({best_buy_id})")
                    self.commands[ship_id] = TradeCommand(target=best_buy_id,
                                                          resource=best_buy_res,
                                                          amount=best_buy_amt)

    def attack_or_defend_with(self, ship_id, ship):
        is_mothership = self.mothership and ship_id == self.mothership

        if is_mothership:
            if not self.last_enemy_target or (self.last_enemy_target and
               self.last_enemy_target in self.data.ships and (
                    self.data.ships[self.last_enemy_target].ship_class != "5" or
                    self.data.ships[self.last_enemy_target].ship_class != "4")):
                closest_fighter = None
                closest_fighter_class = None
                closest_fighter_dist = 20.

                for enemy_id, enemy in self.other_ships.items():
                    if enemy.ship_class != "5" and enemy.ship_class != "4":
                        continue

                    dist = compute_distance(enemy.position, ship.position)
                    if ((not closest_fighter_class or enemy.ship_class == closest_fighter_class) and dist < closest_fighter_dist) or (
                            closest_fighter_class == "4" and enemy.ship_class == "5" and dist < 20):
                        closest_fighter_dist = dist
                        closest_fighter = enemy_id
                        closest_fighter_class = enemy.ship_class

                if closest_fighter:
                    self.last_enemy_target = closest_fighter

        # we are currently fighting a ship, attack it if it's close
        if self.last_enemy_target and self.last_enemy_target in self.data.ships and \
           compute_distance(self.data.ships[self.last_enemy_target].position, ship.position) < 20:
            self.commands[ship_id] = AttackCommand(target=self.last_enemy_target)
        # if not, let's look at the closest enemy ship
        elif self.closest_enemy_ship:
            closest_enemy_ship = self.data.ships[self.closest_enemy_ship]
            dist_center = compute_distance(closest_enemy_ship.position, self.center)
            dist_ship = compute_distance(closest_enemy_ship.position, ship.position)
            # attack it if it's close to our ship already or if it's close to our defense ring and
            # we either don't have a mothership, this is a normal ship and the nearby enemy is a trader
            # or if this is a mothership and the nearby ship is not a trader
            if dist_ship < 20 or (
                dist_center < self.defense_dist and ((
                    not self.mothership
                ) or (
                    ship_id != self.mothership and (
                        closest_enemy_ship.ship_class == "2" or
                        closest_enemy_ship.ship_class == "3"
                    )
                ) or (
                    ship_id == self.mothership and (
                        closest_enemy_ship.ship_class != "2" and
                        closest_enemy_ship.ship_class != "3"
                    )))):
                self.commands[ship_id] = AttackCommand(target=self.closest_enemy_ship)
                # if this is a mothership, save the enemy ship as our target
                if is_mothership:
                    self.last_enemy_target = self.closest_enemy_ship
            # if this is not a mothership, but we have one and an enemy is within our defense ring
            # follow the mothership
            elif self.mothership and ship_id != self.mothership and dist_center < self.defense_dist:
                self.commands[ship_id] = MoveCommand(destination=Destination(target=self.mothership))
            # otherwise, try to keep in the middle of our traders
            else:
                if self.center[0]:
                    self.commands[ship_id] = MoveCommand(destination=Destination(coordinates=self.center))
                # if this is a mothership, reset our target
                if is_mothership:
                    self.last_enemy_target = None
        # there is no closest enemy ship
        else:
            if self.center[0]:
                self.commands[ship_id] = MoveCommand(destination=Destination(coordinates=self.center))
            # if this is a mothership, reset our target
            if is_mothership:
                self.last_enemy_target = None

    def attack(self):
        # and attack (or defend)
        for ship_id, ship in self.my_fighters_and_mothership.items():
            self.attack_or_defend_with(ship_id, ship)

    def buy_ships(self):
        # nowhere to buy ships from
        if not self.my_shipyards:
            return
        # we are currently fighting someone
        if self.last_enemy_target:
            return

        # if there are still some enemy ships, buy fighters
        if len(self.other_ships):
            fighters_count = sum(1 for ship in self.my_fighters.values() if ship.ship_class == "4")
            bombers_count = sum(1 for ship in self.my_fighters.values() if ship.ship_class == "5")
            traders_count = len(self.my_traders)
            # magic
            want_fighters = traders_count // 4 - 1
            want_bombers = traders_count // 5 + 1

            buy_fighter = None
            # prefer bombers
            if bombers_count < want_bombers:
                buy_fighter = "5"
            elif fighters_count < want_fighters:
                buy_fighter = "4"

            # we want more fighters!
            if buy_fighter:
                if self.my_money >= self.static_data.ship_classes[buy_fighter].price + self.extra_money:
                    shipyard = None
                    # prefer buying from the mothership
                    if self.mothership:
                        shipyard = self.mothership
                    elif self.my_shipyards:
                        shipyard = random.choice(list(self.my_shipyards.keys()))

                    if shipyard:
                        self.commands[shipyard] = ConstructCommand(ship_class=buy_fighter)
                return

        # no fighters needed, buy more traders
        if self.my_total > 8000000:
            # hauler
            buy_trader = "2"
        else:
            # shipper
            buy_trader = "3"

        if self.my_money >= self.static_data.ship_classes[buy_trader].price + self.extra_money:
            shipyard = None
            # prefer buying from the mothership
            if self.mothership:
                shipyard = self.mothership
            elif self.my_shipyards:
                shipyard = random.choice(list(self.my_shipyards.keys()))

            if shipyard:
                self.commands[shipyard] = ConstructCommand(ship_class=buy_trader)

    def repair(self):
        for ship_id, ship in self.my_fighters_and_mothership.items():
            # if we are currently attacking, we have enough money for a repair and enough life lost, then repair
            if ship_id in self.commands and self.commands[ship_id].type == "attack":
                ship_class = self.static_data.ship_classes[ship.ship_class]
                if ship.ship_class == "1":
                    if ship.life <= ship_class.life - (2*ship_class.repair_life) and self.my_money >= ship_class.repair_price:
                        self.commands[ship_id] = RepairCommand()
                # change this, repair between fights?
                elif (ship.ship_class == "5" or ship.ship_class == "4") and \
                        self.last_enemy_target and \
                        self.last_enemy_target in self.data.ships and \
                        self.data.ships[self.last_enemy_target].ship_class != "4" and \
                        self.data.ships[self.last_enemy_target].ship_class != "5":
                    if sum(1 for other, dist in self.ship_distances[ship_id].items() if dist < 50 and self.data.ships[other].player != self.player_id and (self.data.ships[other].ship_class == "4" or self.data.ships[other].ship_class == "5")) > 0:
                        if ship.life <= ship_class.life and self.my_money >= ship_class.repair_price:
                            self.commands[ship_id] = RepairCommand()
                    if ship.life <= ship_class.life - ship_class.repair_life and self.my_money >= ship_class.repair_price:
                        self.commands[ship_id] = RepairCommand()
                elif (ship.ship_class == "5" or ship.ship_class == "4") and len(self.my_fighters) > 5:
                    if ship.life <= ship_class.life - ship_class.repair_life and self.my_money >= ship_class.repair_price:
                        self.commands[ship_id] = RepairCommand()

        # also repair escaping traders if we have enough others to cover the loss
        if not self.my_fighters_and_mothership and len(self.my_traders) >= 5:
            for ship_id, ship in self.my_traders.items():
                if ship_id in self.commands and self.commands[ship_id].type == "move":
                    ship_class = self.static_data.ship_classes[ship.ship_class]
                    if ship.life <= ship_class.life - ship_class.repair_life and self.my_money >= ship_class.repair_price:
                        self.commands[ship_id] = RepairCommand()

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
        closest_enemy_ship_class = None

        for enemy_id, enemy in self.other_ships.items():
            dist = compute_distance(enemy.position, self.center)
            if self.last_enemy_target and enemy_id == self.last_enemy_target:
                dist -= 25
            elif enemy.ship_class == "1":
                dist += 25
            elif enemy.ship_class in ["2", "3"]:
                dist += 100

            if ((not closest_enemy_ship_class or enemy.ship_class == closest_enemy_ship_class) and dist < closest_enemy_ship_dist) or \
               (dist < self.defense_dist and closest_enemy_ship_class in ["2", "3"] and enemy.ship_class in ["1", "4", "5"]) or \
               (dist < self.defense_dist and closest_enemy_ship_class in ["1", "2", "3"] and enemy.ship_class in ["4", "5"]):
                closest_enemy_ship_dist = dist
                closest_enemy_ship = enemy_id
                closest_enemy_ship_class = enemy.ship_class

        return closest_enemy_ship

    def game_logic(self):
        self.recreate_me()

        # precalculate some things
        self.my_ships: Dict[Ship] = {ship_id: ship for ship_id, ship in
                                     self.data.ships.items() if ship.player == self.player_id}
        self.other_ships: Dict[Ship] = {ship_id: ship for ship_id, ship in
                                        self.data.ships.items() if ship.player != self.player_id}

        self.my_fighters = {ship_id: ship for ship_id, ship in
                            self.my_ships.items() if ship.ship_class == "4" or ship.ship_class == "5"}
        self.my_fighters_and_mothership = {ship_id: ship for ship_id, ship in
                                           self.my_ships.items() if (
                                            ship.ship_class == "1" or
                                            ship.ship_class == "4" or
                                            ship.ship_class == "5")}
        self.my_traders = {ship_id: ship for ship_id, ship in
                           self.my_ships.items() if ship.ship_class == "2" or ship.ship_class == "3"}
        self.my_shipyards = {ship_id: ship for ship_id, ship in
                             self.my_ships.items() if self.static_data.ship_classes[ship.ship_class].shipyard}

        self.ship_distances = {ship_id: {other_id: compute_distance(ship.position, other.position)
                                         for other_id, other in self.data.ships.items()}
                               for ship_id, ship in self.data.ships.items()}

        mothership_list = [ship_id for ship_id, ship in self.my_ships.items() if ship.ship_class == "1"]
        self.mothership = mothership_list[0] if mothership_list else None

        self.center = self.calculate_center()

        # find our furthest ship and calculate our defense ring
        my_furthest_ship_dist = 0.
        for ship_id, ship in self.my_traders.items():
            dist = compute_distance(ship.position, self.center)
            if dist > my_furthest_ship_dist:
                my_furthest_ship_dist = dist

        self.defense_dist = max(150, my_furthest_ship_dist * 2.5)

        self.closest_enemy_ship = self.calculate_closest_enemy_ship()

        my_net_worth = self.data.players[self.player_id].net_worth
        self.my_money = my_net_worth.money
        self.my_total = my_net_worth.total

        # keep some money for trading and repairs
        if len(self.other_ships):
            # TODO maybe look at other players' money and try to have more
            self.extra_money = max(1000000, (self.my_total - 10000000) // 5)
        else:
            self.extra_money = len(self.my_traders) * 20000

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
        self.repair()

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
