from uuid import uuid4

import pandas as pd
import sqlalchemy
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

table_name = "hike-sources"
column_name = "source"

engine = connect_database()

sql = f"""select {column_name} from "{table_name}" """

with engine.connect() as conn:
    db = pd.read_sql(sqlalchemy.text(sql), conn)

db_sources = db[column_name].values.tolist()

sources = list(set(sources) - set(db_sources))

if sources:
    ids = [uuid4() for _ in range(len(sources))]

    df = pd.DataFrame(data=sources, columns=[column_name], index=ids)

    with engine.connect() as conn:
        df.to_sql(table_name, conn, if_exists="append", index_label="id")
