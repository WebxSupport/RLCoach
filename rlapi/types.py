"""Rocket League API type definitions."""
from dataclasses import dataclass, field
from typing import List, Optional

# Simple type aliases
ShopID = str
ClubID = str
ChallengeID = str
PlaylistID = int
TournamentID = str
PartyID = str


@dataclass
class MatchPlayer:
    PlayerID: str = ""
    PlayerName: str = ""
    Score: int = 0
    Goals: int = 0
    Assists: int = 0
    Saves: int = 0
    Shots: int = 0
    Demolishes: int = 0
    OwnGoals: int = 0
    bMVP: bool = False


@dataclass
class Match:
    MatchGUID: str = ""
    RecordStartTimestamp: int = 0
    MapName: str = ""
    Playlist: int = 0
    SecondsPlayed: float = 0.0
    OvertimeSecondsPlayed: float = 0.0
    WinningTeam: int = 0
    Team0Score: int = 0
    Team1Score: int = 0
    bOverTime: bool = False
    bNoContest: bool = False
    bForfeit: bool = False
    bClubVsClub: bool = False
    Mutators: List[str] = field(default_factory=list)
    Players: List[MatchPlayer] = field(default_factory=list)
    CustomMatchCreatorPlayerID: Optional[str] = None


@dataclass
class MatchEntry:
    ReplayUrl: str = ""
    Match: Match = field(default_factory=Match)


# Stubs for other exported types
@dataclass
class PlayerData:
    PlayerName: str = ""
    PlayerID: str = ""


@dataclass
class PlayerXPInfo:
    XPLevel: int = 0
    TotalXP: int = 0


@dataclass
class Product:
    pass


@dataclass
class Shop:
    pass


@dataclass
class ShopCatalogue:
    pass


@dataclass
class Skill:
    pass


@dataclass
class ClubDetails:
    pass
