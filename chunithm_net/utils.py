from datetime import datetime
from typing import cast
from zoneinfo import ZoneInfo

from bs4.element import ResultSet, Tag

from .entities.enums import ClearType, Difficulty, Rank


def chuni_int(s: str) -> int:
    return int(s.replace(",", ""))


def parse_player_rating(soup: ResultSet[Tag]) -> float:
    rating = ""
    for x in soup:
        digit = extract_last_part(cast(str, x["src"]))
        if digit == "comma":
            rating += "."
        else:
            rating += digit[1]
    return float(rating)


def parse_time(time: str, format: str = "%Y/%m/%d %H:%M") -> datetime:
    return datetime.strptime(time, format).replace(tzinfo=ZoneInfo("Asia/Tokyo"))


def extract_last_part(url: str) -> str:
    return url.split("_")[-1].split(".")[0]


def difficulty_from_imgurl(url: str) -> Difficulty:
    match extract_last_part(url):
        case "basic":
            return Difficulty.BASIC
        case "advanced":
            return Difficulty.ADVANCED
        case "expert":
            return Difficulty.EXPERT
        case "master":
            return Difficulty.MASTER
        case "worldsend":
            return Difficulty.WORLDS_END
        case "ultima":
            return Difficulty.ULTIMA
        case "ultimate":
            return Difficulty.ULTIMA

        case _:
            msg = f"Unknown difficulty: {url}"
            raise ValueError(msg)


def get_rank_and_cleartype(soup: Tag) -> tuple[Rank, ClearType]:
    if (rank_img_elem := soup.select_one("img[src*=_rank_]")) is not None:
        rank_img_url = cast(str, rank_img_elem["src"])
        rank = Rank(int(extract_last_part(rank_img_url)))
    else:
        rank = Rank.D

    clear_type = ClearType.FAILED
    if soup.select_one("img[src*=clear]") is not None:
        clear_type = ClearType.CLEAR
    elif soup.select_one("img[src*=hard]") is not None:
        clear_type = ClearType.HARD_CLEAR
    elif soup.select_one("img[src*=absolutep]") is not None:
        clear_type = ClearType.ABSOLUTE_PLUS_CLEAR
    elif soup.select_one("img[src*=absolute]") is not None:
        clear_type = ClearType.ABSOLUTE_CLEAR
    elif soup.select_one("img[src*=catastrophy]") is not None:
        clear_type = ClearType.CATASTROPHY_CLEAR

    # FC and AJ should override all other lamps.
    if clear_type != ClearType.FAILED:
        if soup.select_one("img[src*=fullcombo]") is not None:
            clear_type = ClearType.FULL_COMBO
        elif soup.select_one("img[src*=alljustice]") is not None:
            clear_type = ClearType.ALL_JUSTICE

    return rank, clear_type
