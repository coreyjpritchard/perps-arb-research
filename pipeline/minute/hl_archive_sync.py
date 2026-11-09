"""Sync Hyperliquid asset_ctxs archive (requester-pays S3, read-only creds from env) and extract per-minute
mark/oracle/mid/premium/funding/OI for the study coins into data/hl_archive/minute/<COIN>.parquet."""
import os
import boto3, lz4.frame, io, pathlib, pandas as pd
D = pathlib.Path(os.environ.get("PERPS_DATA", pathlib.Path(__file__).resolve().parents[2] / "data")) / "hl_archive"; RAW = D/"asset_ctxs"; OUT = D/"minute"
RAW.mkdir(parents=True, exist_ok=True); OUT.mkdir(exist_ok=True)
COINS = ["BTC","ETH","SOL","XRP","DOGE","SUI","LINK","AVAX","HYPE"]
s3 = boto3.client("s3", region_name="ap-northeast-1"); kw = dict(Bucket="hyperliquid-archive", RequestPayer="requester")
keys=[]
for page in s3.get_paginator("list_objects_v2").paginate(Prefix="asset_ctxs/", **kw):
    keys += [(o["Key"], o["Size"]) for o in page.get("Contents", [])]
got = 0
for k, sz in sorted(keys):
    f = RAW/k.split("/")[-1]
    if f.exists() and f.stat().st_size == sz: continue
    f.write_bytes(s3.get_object(Key=k, **kw)["Body"].read()); got += sz
print(f"downloaded {got/1e9:.3f} GB this run; files {len(keys)}")
parts = {c: [] for c in COINS}
for f in sorted(RAW.glob("*.csv.lz4")):
    df = pd.read_csv(io.BytesIO(lz4.frame.decompress(f.read_bytes())))
    df = df[df.coin.isin(COINS)]
    for c, g in df.groupby("coin"): parts[c].append(g)
for c, L in parts.items():
    if not L: print(c, "none"); continue
    g = pd.concat(L); g["time"] = pd.to_datetime(g["time"], utc=True)
    g = g.drop_duplicates("time").sort_values("time"); g.to_parquet(OUT/f"{c}.parquet", index=False)
    print(c, len(g), g.time.min(), g.time.max())
