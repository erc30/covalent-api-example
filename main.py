import asyncio
from pathlib import Path

import httpx
import pandas as pd
import plotly.express as px
from environs import Env
from pandas import DataFrame, json_normalize

# read env file
env = Env()
env_file = Path(__file__).resolve().parent / ".env"
env.read_env(env_file)

# Covalent API endpoints
API_KEY = env("API_KEY")
COVALENT_API = "https://api.covalenthq.com/v1/{ENDPOINT}/"
ENDPOINT = "pricing/historical/USD/{TICKER}"
HISTORICAL_PRICE_ENDPOINT = COVALENT_API.format(ENDPOINT=ENDPOINT)


async def get_token_price_history(ticker: str, from_date: str, to_date: str) -> dict:
    """
    Asynchronously get prices from start date to end date for token.

    :param ticker: token ticker.
    :param from_date: start date.
    :param to_date: end date.
    :return: historical prices by day.
    """
    url = HISTORICAL_PRICE_ENDPOINT.format(TICKER=ticker)
    params = {"key": API_KEY, "from": from_date, "to": to_date}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params)
        if resp.status_code is not httpx.codes.OK.value:
            raise Exception(f"ticker: {ticker}, status_code: {resp.status_code}")
        return resp.json()


async def get_all_token_prices(ticker_list: list[str],
                               from_date: str,
                               to_date: str) -> list[dict]:
    """
    Asynchronously get prices for multiple tokens.

    :param ticker_list: list of token tickers.
    :param from_date: start date.
    :param to_date: end date.
    :return: historical prices by day.
    """
    # planning tasks and getting results
    tasks = [
        get_token_price_history(ticker, from_date=from_date, to_date=to_date)
        for ticker in ticker_list
    ]
    token_prices = await asyncio.gather(*tasks)
    return token_prices


def historical_prices_to_df(token_prices: list[dict]) -> DataFrame:
    """
    Convert list of dicts with prices to dataframe.

    :param token_prices: historical prices for tokens.
    :return: dataframe with ticker, date and price columns.
    """
    df: DataFrame = json_normalize(token_prices, record_path=[["data", "prices"]])
    # save only the columns we need
    df = df.loc[:, ["date", "price", "contract_metadata.contract_ticker_symbol"]]
    # rename the columns
    df.columns = ["date", "price", "ticker"]
    df["price"] = df["price"].apply(pd.to_numeric, downcast="float")
    df["date"] = pd.to_datetime(df["date"])
    return df


def make_table_df(df: DataFrame) -> DataFrame:
    """
    Add additional columns to dataframe with historical prices.

    Additional columns:
        price.min - minimum price for the date period.
        price.max - maximum price for the date period.
        price.first - first price for the date period.
        price.last - first price for the date period.

        date.min - date of the minimum price value.
        date.max - date of the maximum price value.
        date.first - start date.
        date.last - end date.

    :param df: dataframe with historical prices.
    :return: dataframe with additional columns.
    """
    df_max = df.loc[df.groupby("ticker")["price"].idxmax()].set_index("ticker")
    df_min = df.loc[df.groupby("ticker")["price"].idxmin()].set_index("ticker")
    # create multiindex dataframe with columns min and max
    df_min_max = pd.concat([df_min, df_max], axis=1, keys=["min", "max"])
    # change first level columns to date and price
    df_min_max = df_min_max.swaplevel(0, 1, axis=1).sort_index(1)
    df_first_last = df.sort_values("date").groupby(by="ticker").agg(["first", "last"])
    res = df_min_max.join(df_first_last).sort_index(1)
    return res


def calculate_price_ratio(df: DataFrame) -> DataFrame:
    """
    Calculate the ratio of the initial price to the last and maximum.

    :param df: dataframe with historical prices.
    :return: dataframe with new columns: r_last and r_max.
    """
    df_price = df["price"]
    df["r_last"] = df_price["last"] / df_price["first"]
    df["r_max"] = df_price["max"] / df_price["first"]
    return df


def calculate_profit(df: DataFrame, deposit: int) -> DataFrame:
    """
    Calculate how the deposit would change.

    :param df: dataframe with price ratio (last/first and max/first)
    :param deposit: deposit.
    :return: dataframe with new columns: p_last and p_max.
    """
    df["p_last"] = df["r_last"] * deposit - deposit
    df["p_max"] = df["r_max"] * deposit - deposit
    return df


def show_chart(df: DataFrame, title: str = "") -> None:
    """
    Display a bar chart of how the deposit has changed for each token.

    :param df: dataframe with changed deposit.
    :param title: chart title.
    """
    fig = px.bar(df, y=["p_last", "p_max"], title=title, barmode="overlay")
    fig.update_layout(hovermode="x", yaxis_title="profit, $")
    fig.update_yaxes(tickformat=",.0f")
    fig.show()


async def main():
    TICKER_LIST = ["UNI", "SUSHI", "BAL", "LRC", "BNT", "IDEX"]
    START_DATE = "2021-01-01"
    END_DATE = "2021-04-19"
    # USD deposit
    DEPOSIT = 1000

    token_prices = await get_all_token_prices(TICKER_LIST, START_DATE, END_DATE)
    df = historical_prices_to_df(token_prices)
    df = make_table_df(df)
    df = calculate_price_ratio(df)
    df = calculate_profit(df, DEPOSIT)
    title = f"Profit from {START_DATE} to {END_DATE}"

    print(df.to_string())
    show_chart(df, title=title)


if __name__ == "__main__":
    asyncio.run(main())
