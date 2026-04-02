import os
import json
import boto3
import requests
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
from datetime import datetime, timezone
from decimal import Decimal
from boto3.dynamodb.conditions import Key
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


# Configurations
TABLE_NAME = os.environ["DYNAMODB_TABLE"]
S3_BUCKET = os.environ["S3_BUCKET"]
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

COINS = ["bitcoin", "ethereum", "solana"]
COIN_LABEL = {
    "bitcoin": "Bitcoin (BTC)",
    "ethereum": "Ethereum (ETH)",
    "solana": "Solana (SOL)",
}
COIN_COLORS = {
    "bitcoin": "#f2a900",
    "ethereum": "#627eea",
    "solana": "#00ffa3",
}

# AWS Clients
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
s3 = boto3.client("s3", region_name=AWS_REGION)
table = dynamodb.Table(TABLE_NAME)

def fetch_prices() -> dict:
    """
    Call CoinGecko to fetch current prices - No API key required
    """
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": ",".join(COINS),
        "vs_currencies": "usd",
        "include_market_cap": "true",
        "include_24hr_vol": "true",
        "include_24hr_change": "true",
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()

def get_last_price(coin_id: str) -> dict | None:
    """
    Get the last recorded price for a coin from DynamoDB
    """
    resp = table.query(
        KeyConditionExpression=Key("coin_id").eq(coin_id),
        ScanIndexForward=False,
        Limit=1,
    )
    items = resp.get("Items", [])
    return items[0] if items else None

def write_record(coin_id: str, ts: str, data: dict, prev_price: float | None):
    price = float(data["usd"])
    mkt_cap = float(data.get("usd_market_cap", 0))
    vol_24h = float(data.get("usd_24h_vol", 0))
    change_24h = float(data.get("usd_24h_change", 0))

    delta = round(price - prev_price, 6) if prev_price is not None else 0.0

    if prev_price is None:
        log.info(f"First record for {coin_id}: ${price:.2f}")
        trend = "Initial"
    elif abs(delta) / max(prev_price, 1) < 0.0005: 
        log.info(f"No significant change for {coin_id}: ${price:.2f} (Δ${delta:.6f})")
        trend = "Stable"
    elif delta > 0:
        log.info(f"Price up for {coin_id}: ${price:.2f} (Δ${delta:.6f})")
        trend = "Rising"
    else:
        log.info(f"Price down for {coin_id}: ${price:.2f} (Δ${delta:.6f})")
        trend = "Falling"

    item = {
        "coin_id": coin_id,
        "timestamp": ts,
        "price_usd": Decimal(str(round(price, 6))),
        "delta_usd": Decimal(str(round(delta, 6))),
        "trend": trend,
        "market_cap": Decimal(str(round(mkt_cap, 2))),
        "vol_24h": Decimal(str(round(vol_24h, 2))),
        "change_24h": Decimal(str(round(change_24h, 4))),
    }
    table.put_item(Item=item)

    label = COIN_LABEL[coin_id]
    sign = "+" if delta > 0 else ""
    log.info(f"{label}: ${price:.2f} ({sign}${delta:.6f}, {trend})")
    print(f"{label}: ${price:.2f} ({sign}${delta:.6f}, {trend})")
    return item

def fetch_history(coin_id: str) -> list[dict]:
    """
    Fetch historical price data for a coin from DynamoDB
    """
    items = []
    last_evaluated_key = None
    while True:
        kwargs = {
            "KeyConditionExpression": Key("coin_id").eq(coin_id),
            "ScanIndexForward": True,
            "Limit": 1000,
        }
        if last_evaluated_key:
            kwargs["ExclusiveStartKey"] = last_evaluated_key
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        last_evaluated_key = resp.get("LastEvaluatedKey")
        if not last_evaluated_key:
            break
    return items

def build_dataframe() -> pd.DataFrame:
    """
    Convert historical data into a Pandas DataFrame
    """
    rows =[]
    for coin in COINS:
        for item in fetch_history(coin):
            rows.append({
                "coin_id": item["coin_id"],
                "timestamp": datetime.fromisoformat(item["timestamp"]),
                "price_usd": float(item["price_usd"]),
                "delta_usd": float(item["delta_usd"]),
                "trend": item["trend"],
                "change_24h": float(item.get("change_24h", 0)),
            })
    df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    return df

def generate_plot(df: pd.DataFrame, path: str="/tmp/plot.png"):
    """
    Generate a line plot of price trends using Matplotlib and Seaborn
    """
    sns.set_theme(style="darkgrid", palette="deep")
    fig, axes= plt.subplots(3, 1, figsize=(14, 12), sharex=True)
    fig.suptitle("Crypto Price Tracker", fontsize = 16, fontweight="bold", y=0.98)

    for ax, coin in zip(axes, COINS):
        sub = df[df["coin_id"] == coin].copy()
        label = COIN_LABEL[coin]
        color = COIN_COLORS[coin]

        ax.plot(sub["timestamp"], sub["price_usd"], label=label, color=color, linewidth=2)
        ax.fill_between(sub["timestamp"], sub["price_usd"], color=color, alpha=0.1)
        
        rising = sub[sub["trend"] == "Rising"]
        falling = sub[sub["trend"] == "Falling"]
        ax.scatter(rising["timestamp"], rising["price_usd"], color="green", s=20, zorder = 5, label="Rising")
        ax.scatter(falling["timestamp"], falling["price_usd"], color="red", s=20, zorder=5, label="Falling")

        ax.set_ylabel(f"{label} (USD)", fontsize=10)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))
        ax.legend(loc="upper left", fontsize=8)

        if not sub.empty:
            last_price = sub["price_usd"].iloc[-1]
            last_change = sub["change_24h"].iloc[-1]
            change_sign = "+" if last_change > 0 else ""
            ax.set_title(f"Last: ${last_price:.2f} ({change_sign}{last_change:.2f}%)", fontsize=9)

    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
    axes[-1].xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate(rotation=30)
 
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fig.text(0.99, 0.01, f"Last updated: {now_str}", ha="right", fontsize=8, color="gray")
 
    plt.tight_layout(rect=[0, 0.02, 1, 0.97])
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Plot saved → {path}")

def upload_to_s3(local_path: str, s3_key: str, content_type: str):
    """
    Upload a file to S3
    """
    if not os.path.exists(local_path):
        log.error(f"File not found: {local_path}")
        return
    s3.upload_file(local_path, S3_BUCKET, s3_key, ExtraArgs={"ContentType": content_type})
    log.info(f"Uploaded to S3 → s3://{S3_BUCKET}/{s3_key}")

def main():
    try:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"Fetching prices at {ts}...")

        # Fetch current prices and write to DynamoDB
        prices = fetch_prices()
        for coin in COINS:
            data = prices.get(coin, {})
            if not data:
                log.warning(f"No price data for {coin}")
                continue
            last_record = get_last_price(coin)
            prev_price = float(last_record["price_usd"]) if last_record else None
            write_record(coin, ts, data, prev_price)

        # Build DataFrame and generate plot
        df = build_dataframe()
        plot_path = "/tmp/plot.png"
        generate_plot(df, plot_path)

        # Save CSV
        csv_path = "/tmp/data.csv"
        df.to_csv(csv_path, index=False)
        log.info(f"CSV saved → {csv_path}")
        upload_to_s3(csv_path, "data.csv", "text/csv")

        # Upload plot to S3
        upload_to_s3(plot_path, "plot.png", "image/png")

    except Exception as e:
        log.error(f"Error in main: {e}", exc_info=True)

if __name__ == "__main__":
    main()



