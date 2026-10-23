from uuid import uuid4

import pandas as pd
import sqlalchemy
from general_fun import connect_database

grades = [
    "Unknown",
    "Easy",
    "Medium",
    "Challenging",
    "Expert",
]

table_name = "hike-grades"
column_name = "grade"

engine = connect_database()

sql = f"""select {column_name} from "{table_name}" """

with engine.connect() as conn:
    db = pd.read_sql(sqlalchemy.text(sql), conn)

db_grades = db[column_name].values.tolist()

grades = list(set(grades) - set(db_grades))

if grades:
    ids = [uuid4() for _ in range(len(grades))]

    df = pd.DataFrame(data=grades, columns=[column_name], index=ids)

    with engine.connect() as conn:
        df.to_sql(table_name, conn, if_exists="append", index_label="id")
