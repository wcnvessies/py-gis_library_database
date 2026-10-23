
import math
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import quote_plus

import sqlalchemy


class colors:  # You may need to change color settings
    PURPLE = "\033[95m"
    CYAN = "\033[96m"
    DARKCYAN = "\033[36m"
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"
    END = "\033[0m"

def roundup(x:float, nearest_value:int)->int:

    return math.ceil(x / nearest_value) * nearest_value


def rounddown(x:float, nearest_value:int)->int:
    return math.floor(x / nearest_value) * nearest_value

def ceil_date(date, **kwargs):
    secs = timedelta(**kwargs).total_seconds()
    return datetime.fromtimestamp(
        date.timestamp() + secs - date.timestamp() % secs, tz=UTC
    )


def floor_date(date, **kwargs):
    secs = timedelta(**kwargs).total_seconds()
    return datetime.fromtimestamp(date.timestamp() - date.timestamp() % secs, tz=UTC)


def date_diff_in_seconds(dt2:datetime, dt1:datetime)->int:
    TimeDelta = dt2 - dt1
    return TimeDelta.days * 24 * 3600 + TimeDelta.seconds


def dhms_from_seconds(seconds):
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    return (days, hours, minutes, seconds)


def print_execution_time(T0:datetime) -> None:
    d, h, m, s = dhms_from_seconds(date_diff_in_seconds(datetime.now(), T0))
    print(
        f"{colors.BOLD}{colors.BLUE}"
        + f"{d} days, {h} hours, {m} minutes, {s} seconds ("
        + datetime.now().strftime("@%Y%m%d %H:%M:%S")
        + f"){colors.END}"
    )




def connect_database():
    user = os.getenv("GIS_DB_USER")
    password = os.getenv("GIS_DB_PASS")
    host = os.getenv("GIS_DB_HOST")
    port = os.getenv("GIS_DB_PORT")
    dbname = os.getenv("GIS_DB_NAME")

    connection_str = f"postgresql://{user}:{quote_plus(password or "")}@{host}:{port}/{dbname}"

    return sqlalchemy.create_engine(connection_str, echo=False)

