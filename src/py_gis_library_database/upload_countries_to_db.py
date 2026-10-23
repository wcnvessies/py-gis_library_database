from uuid import uuid4

import pandas as pd
import sqlalchemy
from general_fun import connect_database

countries = ["Not applicable", "Norway", "Scotland", "Belgium", "Germany", "Sweden", "South-Africa", "Zimbabwe"]

table_name = "countries"
column_name = "country"

engine = connect_database()

sql = f"""select {column_name} from "{table_name}" """

with engine.connect() as conn:
    db = pd.read_sql(sqlalchemy.text(sql), conn)

db_countries = db[column_name].values.tolist()

countries = list(set(countries) - set(db_countries))

if countries:
    ids = [uuid4() for _ in range(len(countries))]

    df = pd.DataFrame(data=countries, columns=[column_name], index=ids)

    with engine.connect() as conn:
        df.to_sql(table_name, conn, if_exists="append", index_label="id")
