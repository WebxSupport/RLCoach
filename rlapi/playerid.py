"""PlayerID module for Rocket League API."""
from enum import Enum
from typing import Tuple


class Platform(str, Enum):
    EPIC = "Epic"
    STEAM = "Steam"
    PS4 = "PS4"
    XBOX = "XboxOne"
    SWITCH = "Switch"


class PlayerID(str):
    def __new__(cls, value: str):
        return super().__new__(cls, value)

    @classmethod
    def create(cls, platform: Platform, player_id: str) -> "PlayerID":
        return cls(f"{platform.value}|{player_id}|0")

    def parse(self) -> Tuple[Platform, str]:
        parts = str(self).split("|")
        if len(parts) != 3:
            raise ValueError(f"Invalid PlayerID format: {self}")
        return Platform(parts[0]), parts[1]


def new_player_id(platform: Platform, player_id: str) -> PlayerID:
    return PlayerID.create(platform, player_id)


def parse_player_id(player_id: str) -> Tuple[Platform, str]:
    return PlayerID(player_id).parse()
