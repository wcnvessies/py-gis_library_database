from uuid import uuid4

import pandas as pd
import sqlalchemy
from general_fun import connect_database

colors = [
    "Not applicable",
    "Green",
    "Blue",
    "Red",
    "Black",
]

table_name = "hike-colors"
column_name = "color"

engine = connect_database()

sql = f"""select {column_name} from "{table_name}" """

with engine.connect() as conn:
    db = pd.read_sql(sqlalchemy.text(sql), conn)

db_colors = db[column_name].values.tolist()

colors = list(set(colors) - set(db_colors))

if colors:
    ids = [uuid4() for _ in range(len(colors))]

    df = pd.DataFrame(data=colors, columns=[column_name], index=ids)

    with engine.connect() as conn:
        df.to_sql(table_name, conn, if_exists="append", index_label="id")
