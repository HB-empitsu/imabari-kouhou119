import pathlib
from urllib.parse import urljoin, urlparse

import pandas as pd
import pdfplumber
import requests

import streamlit as st


def download_file(url, save_path):
    response = requests.get(url)
    response.raise_for_status()
    save_path.write_bytes(response.content)


def process_table(table):
    df = pd.DataFrame(table[1:], columns=table[0])
    df = df.stack().reset_index().set_axis(["number", "week", "text"], axis=1)
    df["week"] = df["week"].fillna("日")
    df["text"] = (
        df["text"]
        .str.replace("~", "～")
        .str.replace(" ", "")
        .str.strip()
        .str.replace("\n\(", "(", regex=True)
        .mask(df["text"] == "")
    )
    return df.dropna(subset="text")


def split_text(df):
    df = df.join(df["text"].str.split(expand=True)).rename(columns={0: "day"})
    df["day"] = pd.to_numeric(df["day"], errors="coerce")
    return df.dropna(subset="day").astype({"day": int}).drop(["number", "text"], axis=1)


def melt_and_split(df):
    df = (
        pd.melt(df, id_vars=["day", "week"])
        .dropna(subset="value")
        .sort_values(by=["day", "variable"])
        .reset_index(drop=True)
    )
    df[["name", "time"]] = df["value"].str.split("(?<!\))\(", expand=True)
    df["time"] = df["time"].str.strip("()").str.replace(")(", " / ")
    return df.drop("value", axis=1)


def filter_data(df):
    return df[
        ~((df["week"] == "日") & (df["name"].str.contains("歯科")))
        & ~((df["name"] == "献血") | (df["name"] == "市民会館前"))
    ]


def categorize_data(df):
    island = [
        "しのざき整形外科",
        "はかた外科胃腸科",
        "喜多嶋診療所",
        "斎藤クリニック",
        "大三島中央病院",
        "片山医院",
        "有津むらかみクリニック",
    ]
    pediatrics = [
        "あおい小児科",
        "丹こどもクリニック",
        "まつうらバンビクリニック",
        "みぶ小児科",
        "医師会市民病院",
        "県立今治病院",
        "済生会今治病院",
    ]

    df["type"] = 8
    df["type"] = df["type"].mask(df["name"].isin(island), 9)
    df["type"] = df["type"].mask(
        (df["variable"] > 1) & df["name"].isin(pediatrics) & ~(df["time"].fillna("").str.contains("翌")), 7
    )

    df["time"] = df["time"].mask(df["time"].isna() & (df["type"] == 7), "09:00～12:00 / 14:00～17:00")
    df["time"] = df["time"].mask(df["time"].isna() & (df["type"] == 9), "09:00～17:00")

    df["type"] = df["type"].mask(df["time"].isna() & (df["variable"] == 1), 0)
    df["time"] = df["time"].mask(df["type"] == 0, "8:30～翌8:30")
    df["time"] = df["time"].str.replace("8:30", "08:30")

    df["type"] = df["type"].mask((df["variable"] == 1) & (df["type"] == 8) & (df["time"] == "08:30～17:30"), 1)
    df["type"] = df["type"].mask((df["variable"] == 2) & (df["type"] == 8) & (df["time"] == "17:30～翌08:30"), 2)
    df["type"] = df["type"].mask(
        (df["variable"] == 1)
        & (df["type"] == 8)
        & (df["time"] == "08:30～17:15 / 22:30～翌08:30")
        & (df["name"] == "県立今治病院"),
        3,
    )
    df["type"] = df["type"].mask(
        (df["variable"] == 2)
        & (df["type"] == 8)
        & (df["time"] == "17:15～22:30")
        & (df["name"] == "今治セントラルクリニック"),
        4,
    )

    return df


def add_missing_rows(df):
    filtered_days = df[
        (df["week"] == "日") & (df["variable"] == 1) & (df["name"] == "医師会市民病院") & (df["type"] == 0)
    ]["day"]
    island_days = df[(df["day"].isin(filtered_days)) & (df["variable"] == 2) & (df["type"] == 9)]["day"]

    new_rows = []
    for day in island_days:
        new_rows.extend(
            [
                {"day": day, "week": "日", "variable": 1, "name": "医師会市民病院", "time": "09:00～17:30", "type": 6},
                {
                    "day": day,
                    "week": "日",
                    "variable": 1,
                    "name": "医師会市民病院",
                    "time": "09:00～12:00 / 14:00～17:00",
                    "type": 7,
                },
            ]
        )

    return pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True).sort_values(by=["day", "variable", "type"])


@st.cache_data(ttl="1d")
def load_data():
    base_url = "https://www.city.imabari.ehime.jp/kouhou/koho/"
    response = requests.get(base_url)
    response.raise_for_status()

    pdf_url = urljoin(response.url, "kyukyu.pdf")
    yyyymm = urlparse(response.url).path.strip("/").split("/")[-1]

    save_path = pathlib.Path("kyukyu.pdf")
    save_path.parent.mkdir(parents=True, exist_ok=True)
    download_file(pdf_url, save_path)

    with pdfplumber.open(save_path, unicode_norm="NFKC") as pdf:
        table = pdf.pages[0].extract_table()

    df = process_table(table)
    df = split_text(df)
    df = melt_and_split(df)
    df = filter_data(df)
    df = categorize_data(df)
    df = add_missing_rows(df)

    df["date"] = pd.to_datetime(f"{yyyymm}01") + pd.to_timedelta(df["day"] - 1, unit="D")
    df["date"] = df["date"].dt.date
    df = df.reindex(columns=["date", "name", "type", "time"])

    return df


df = load_data()

st.title("広報いまばり 救急病院")

st.dataframe(df, hide_index=True)
