from uuid import uuid4

import pandas as pd
from general_fun import connect_database

sources = [
    "Unknown",
    "Twonav Aventura",
    "Twonav Aventura 2 Plus",
    "Garmin Fēnix S5",
    "https://en.nordlandturselskap.no/grade-terrain-grading-hiking-adventure-trips/",
    "Rother - Schotland",
    "Rother wandelgids Lofoten en de Vesterålen",
    "Rother wandelgids Centraal-Noorwegen",
    "Rother wandelgids Zuid-Noorwegen",
    "Rother wandelgids Noorwegen – Jotunheimen - Rondane",
]

ids = [uuid4() for _ in range(len(sources))]

df = pd.DataFrame(data=sources, columns=["source"], index=ids)

engine = connect_database()

with engine.connect() as conn:
    df.to_sql("hike-sources", conn, if_exists="replace", index_label="id")
