# app.py
import re
import io
import pandas as pd
import streamlit as st

st.set_page_config(page_title="teket 席ごとの最終状態サマリ", layout="wide")
st.title("teket 販売履歴 → 席ごと最終状態サマリ")

def read_csv_any(f):
    # teketはCP932が多いがUTF-8も混在するため両対応
    for enc in ("cp932", "utf-8-sig", "utf-8"):
        try:
            f.seek(0)
            return pd.read_csv(f, encoding=enc, dtype=str).fillna("")
        except Exception:
            continue
    f.seek(0)
    return pd.read_csv(f, dtype=str).fillna("")

def pick_col(cols, candidates):
    for c in candidates:
        if c in cols:
            return c
    # ゆるい部分一致（例: "受取日時(日本時間)"）
    for c in candidates:
        for col in cols:
            if c in col:
                return col
    return None

def parse_seat(raw):
    s = str(raw)
    # 全角を半角化っぽく：数字だけ確実に拾う
    digits = re.findall(r"\d+", s)
    if len(digits) >= 3:
        f, r, n = digits[0], digits[1], digits[2]
        try:
            return f"{int(f)}-{int(r):02d}-{int(n):02d}", int(f), int(r), int(n)
        except ValueError:
            pass
    # 典型: "1階5列12番" が欠けるケースに一応対応
    m = re.search(r"(\d+)\s*階.*?(\d+)\s*列.*?(\d+)\s*番", s)
    if m:
        f, r, n = map(int, m.groups())
        return f"{f}-{r:02d}-{n:02d}", f, r, n
    return "", None, None, None

def to_dt(series):
    for fmt in [None, "yyyy-MM-dd HH:mm:ss", "yyyy/MM/dd HH:mm", "yyyy/MM/dd H:mm"]:
        try:
            return pd.to_datetime(series, errors="coerce", format=None if fmt is None else fmt)
        except Exception:
            continue
    return pd.to_datetime(series, errors="coerce")

def chain_compact(names):
    out = []
    prev = None
    for x in names:
        x = (x or "").strip()
        if not x:
            continue
        if x != prev:
            out.append(x)
            prev = x
    return " → ".join(out)

def coalesce(*vals):
    for v in vals:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""

f = st.file_uploader("teket販売履歴 CSV をアップロード", type=["csv"])
if not f:
    st.stop()

df = read_csv_any(f)
cols = df.columns.tolist()

# 想定カラム候補
seat_col = pick_col(cols, ["座席", "座席情報", "席", "座席名", "エリア/座席", "券面座席"])
event_time_col = pick_col(cols, ["販売日時", "処理日時", "購入日時", "日時", "更新日時"])
status_col = pick_col(cols, ["処理", "ステータス", "状態"])
buyer_col = pick_col(cols, ["購入者", "購入者名", "注文者", "購入者氏名"])
to_cols = [
    pick_col(cols, ["受取者", "受取者名", "来場者", "来場者名", "譲渡先", "受取先"]),
    buyer_col,
]
received_time_col = pick_col(cols, ["受取日時", "受取日", "来場日時", "チェックイン日時"])

# ガード
if not seat_col:
    st.error("座席列が見つかりません。列名例: 「座席」「席」「座席情報」")
    st.dataframe(df.head(30))
    st.stop()
if not event_time_col:
    st.warning("時系列列が見つからないため、行順で擬似ソートします。列名例: 「販売日時」「処理日時」")
    df["_index_as_time"] = range(len(df))
    event_time_col = "_index_as_time"

# 席キー生成
tmp = df[seat_col].apply(parse_seat).apply(pd.Series)
tmp.columns = ["席", "_階", "_列", "_番"]
df = pd.concat([df, tmp], axis=1)
df = df[df["席"] != ""].copy()

# 時刻整形
if event_time_col != "_index_as_time":
    df["_event_dt"] = to_dt(df[event_time_col])
    # 欠損は最小値で埋める
    min_dt = pd.Timestamp("1970-01-01")
    df["_event_dt"] = df["_event_dt"].fillna(min_dt)
else:
    df["_event_dt"] = df[event_time_col]

# 役者（from/to）
df["_from"] = df[buyer_col] if buyer_col else ""
to_guess = None
for c in to_cols:
    if c:
        to_guess = c
        break
df["_to"] = df[to_guess] if to_guess else df["_from"]

# キャンセル判定
cancel_words = ("キャンセル", "取消", "払戻", "返金", "無効")
def is_canceled(row):
    s = (row.get(status_col, "") if status_col else "") or ""
    s = str(s)
    return any(w in s for w in cancel_words)

df["_is_cancel"] = df.apply(is_canceled, axis=1)

# 受取日時（最終所有者の受取）
if received_time_col:
    df["_received_dt_raw"] = df[received_time_col]
    df["_received_dt"] = to_dt(df["_received_dt_raw"])
else:
    df["_received_dt_raw"] = ""
    df["_received_dt"] = pd.NaT

# 席ごとに時系列で畳み込み
def reduce_group(g):
    g = g.sort_values("_event_dt", kind="mergesort")
    path = []
    # from→toの推移から所有者の変遷を生成
    for _, r in g.iterrows():
        f, t = (r["_from"] or "").strip(), (r["_to"] or "").strip()
        if not f and not t:
            continue
        # 初回
        if not path:
            path.append(f or t)
        # 所有者が変わった場合のみ追加
        cur = path[-1]
        nxt = t or f
        if nxt and nxt != cur:
            path.append(nxt)

    final_owner = path[-1] if path else coalesce(g["_to"].iloc[-1], g["_from"].iloc[-1])
    received_dt = g["_received_dt"].dropna().max() if "_received_dt" in g else pd.NaT
    received_str = received_dt.strftime("%Y-%m-%d %H:%M") if pd.notna(received_dt) else ""

    # 最終状態（最後の行を優先）
    last = g.iloc[-1]
    canceled = bool(last["_is_cancel"])

    return pd.Series({
        "席": last["席"],
        "キャンセル": "はい" if canceled else "いいえ",
        "経由": chain_compact(path),
        "最終所有者": final_owner,
        "受取日時": received_str,
    })

out = df.groupby("席", as_index=False).apply(reduce_group, include_groups=False)

# ソート：席キー 1-02-03 で数値昇順
def seat_sort_key(s):
    m = re.match(r"(\d+)-(\d+)-(\d+)", s)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return (9999, 9999, 9999)

out = out.sort_values(by="席", key=lambda x: x.map(seat_sort_key), kind="mergesort").reset_index(drop=True)

# 表示（スマホ考慮で主要列のみ）
show_cols = ["席", "キャンセル", "経由", "最終所有者", "受取日時"]
st.dataframe(
    out[show_cols],
    use_container_width=True,
    hide_index=True
)

# ダウンロード
csv = out[show_cols].to_csv(index=False).encode("utf-8-sig")
st.download_button("席ごとの最終状態CSVをダウンロード", data=csv, file_name="teket_席ごと最終状態.csv", mime="text/csv")

# 参考情報（任意表示）
with st.expander("入力CSVの列見取り図"):
    st.write(pd.DataFrame({"columns": cols}))
