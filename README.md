# Crypto Price Tracker

A containerized data pipeline that tracks Bitcoin, Ethereum, and Solana prices hourly using the CoinGecko API, stores data in AWS DynamoDB, and publishes a price chart to a public S3 website.

## Overview

This pipeline runs as a Kubernetes CronJob on an AWS EC2 instance. Every hour it fetches live crypto prices, records them to DynamoDB, generates a price trend chart, and uploads it to S3.

## Data Source

This project uses the CoinGecko public REST API (https://api.coingecko.com). CoinGecko provides real-time cryptocurrency market data with no API key required. Every hour the pipeline calls the /simple/price endpoint to fetch the current USD price, market capitalization, 24-hour trading volume, and 24-hour percent change for Bitcoin (BTC), Ethereum (ETH), and Solana (SOL). 

## Pipeline Architecture

CoinGecko API -> Python Script -> DynamoDB (storage) -> S3 (plot.png + data.csv)

## Feature

- Fetches price, market cap, 24h volume, and 24h change for 3 coins
- Detects price trend per run: Rising, Falling, Stable, or Initial
- Generates a 3-panel time series chart with trend markers
- Publishes plot.png and data.csv to a public S3 website bucket
- Runs automatically every hour via Kubernetes CronJob

## Tech Stack

- Python 3.12
- boto3, requests, pandas, matplotlib, seaborn
- Docker / GHCR
- Kubernetes (K3S on AWS EC2)
- AWS DynamoDB
- AWS S3 static website hosting

## Scheduled Process

1. CronJob fires every hour on the EC2 instance
2. Pod pulls the image from GHCR
3. tracker.py fetches prices from CoinGecko
4. Prices and trend labels are written to DynamoDB
5. Full price history is queried and plotted
6. plot.png and data.csv are uploaded to S3

## Price Chart Sample

![New](price_chart_sample.png)

During the 72 hours from April 3 to April 5, 2026, all three coins showed stability with no significant spikes. Bitcoin ended the window at $68,319 (+1.38% over 24 hours), trading around $66,000 to $68,000 for most of the period before an uptick at the end of April 5. Ethereum held stable between $2,040 and $2,084 (+0.73% over 24 hours). Solana also traded in a tight range between $78 and $81, finishing slightly down at -0.67% over 24 hours.
