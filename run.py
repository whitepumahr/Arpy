import random
import sys
from os import path
from pathlib import Path
import platform
from typing import List

from loguru import logger
from sc2 import maps
from sc2.data import AIBuild, Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer

sys.path.append("ares-sc2/src/ares")
sys.path.append("ares-sc2/src")
sys.path.append("ares-sc2")

import yaml
from bot.main import Arpy

from ladder import run_ladder_game

plt = platform.system()

# Change if non-default setup / linux
# If having issues with this, modify `map_list` below manually
if plt == "Windows":
    MAPS_PATH: str = "D:\\Diablo 3\\Overwatch\\StarCraft II\\Maps"
elif plt == "Darwin":
    MAPS_PATH: str = "/Applications/StarCraft II/Maps"
elif plt == "Linux":
    # Path would look something like this on linux after installing
    # SC2 via lutris
    MAPS_PATH: str = (
        "~/Games/battlenet/drive_c/Program Files (x86)/StarCraft II/Maps"
    )
else:
    logger.error(f"{plt} not supported")
    sys.exit()

CONFIG_FILE: str = "config.yml"
MAP_FILE_EXT: str = "SC2Map"
MY_BOT_NAME: str = "BotName"
MY_BOT_RACE: str = "BotRace"


def main():
    bot_name: str = "Arpy"
    race: Race = Race.Protoss

    __user_config_location__: str = path.abspath(".")
    user_config_path: str = path.join(__user_config_location__, CONFIG_FILE)

    # Attempt to get race and bot name from config file if they exist
    if path.isfile(user_config_path):
        with open(user_config_path) as config_file:
            config: dict = yaml.safe_load(config_file)
            if MY_BOT_NAME in config:
                bot_name = config[MY_BOT_NAME]
            if MY_BOT_RACE in config:
                race = Race[config[MY_BOT_RACE].title()]

    bot1 = Bot(race, Arpy(), bot_name)

    if "--LadderServer" in sys.argv:
        # Ladder game started by LadderManager
        print("Starting ladder game...")
        result, opponentid = run_ladder_game(bot1)
        print(result, " against opponent ", opponentid)
    else:
        # Local game
        map_list: List[str] = [
            p.name.replace(f".{MAP_FILE_EXT}", "")
            for p in Path(MAPS_PATH).glob(f"*.{MAP_FILE_EXT}")
            if p.is_file()
        ]

        if len(map_list) == 0:
            logger.error(f"Can't find maps, please check `MAPS_PATH` in `run.py'")
            logger.info("Trying back up option")
            logger.info(
                f"\nLooking for maps in {MAPS_PATH} but didn't find anything. \n"
                f"If this path is correct please ensure maps are present. \n"
                f"If this path is incorrect please edit the `MAPS_PATH` in `run.py` \n"
                f"Tip: If you're using linux, MAPS_PATH will definitely need updating\n"
            )

            # Fallback to common ladder maps
            map_list: List[str] = [
                "PylonAIE_v4",
                "PersephoneAIE_v4",
                "TorchesAIE_v4",
                "IncorporealAIE_v4",
                "MagannathaAIE_v2",
            ]

        random_map: str = random.choice(map_list)
        logger.info(f"Map: {random_map}")

        # Modify opponent difficulty/race here
        enemy_race = Race.Terran
        enemy_difficulty = Difficulty.Easy

        result = run_game(
            maps.get(random_map),
            [bot1, Computer(enemy_race, enemy_difficulty)],
            realtime=False,
        )
        print(result)


if __name__ == "__main__":
    main()
