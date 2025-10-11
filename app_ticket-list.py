# app.py
# teket販売履歴CSV → 席ごとの最終状態を1行集約
# 仕様:
# - 席キーは「階-列-番」。2階 L/R 列は「2-L-xx」「2-R-xx」として数字化しない
# - 時系列は「購入日時」を基準
# - 列名は「席 (階-列-番)」「キャンセル(キャンセル済み / -)」「経由」「最終所有者」「最終購入日時」
# - L < R < 数字 で昇順ソート
# - スマホ向けに主要列のみ表示、CSVダウンロード可

import re
import unicodedata
import pandas as pd
import streamlit as st

st.set_page_config(page_title="teket 席ごとの最終状態サマリ", layout="wide")
st.title("teket 販売履歴 → 席ごと最終状態サマリ")

def read_csv_any(f):
    for enc in ("cp932", "utf-8-sig", "utf-8"):
        try:
            f.seek(0)
            return pd.read_csv(f, encoding=enc, dtype=str).fillna("")
        except Exception:
            pass
    f.seek(0)
    return pd.read_csv(f, dtype=str).fillna("")

def pick_col(cols, cands):
    for c in cands:
        if c in cols:
            return c
    for c in cands:
        for col in cols:
            if c in col:
                return col
    return None

def parse_seat(raw):
    """
    例:
      1階5列12番 → 1-05-12
      2階L列8番 / 2階L8 / 2-L-08 / ２階 Ｌ 列 ８ 番 → 2-L-08
      2階R列15番 → 2-R-15
    """
    s = unicodedata.normalize("NFKC", str(raw)).strip().upper()

    # 既にハイフン形式なら正規化して返す
    m = re.fullmatch(r"(\d+)-([0-9LR]+)-(\d+)", s)
    if m:
        f, r, n = m.groups()
        if r in ("L", "R"):
            return f"{int(f)}-{r}-{int(n):02d}"
        return f"{int(f)}-{int(r):02d}-{int(n):02d}"

    # L/R列（列の字や区切りは任意）
    m = re.search(r"(\d+)\s*(?:階|F)?\s*[-\s]*([LR])\s*(?:列)?\s*[-\s]*(\d+)\s*(?:番)?", s, re.I)
    if m:
        f, lr, n = m.groups()
        return f"{int(f)}-{lr.upper()}-{int(n):02d}"

    # 数字列（列の字や区切りは任意）
    m = re.search(r"(\d+)\s*(?:階|F)?\s*[-\s]*(\d+)\s*(?:列)?\s*[-\s]*(\d+)\s*(?:番)?", s)
    if m:
        f, r, n = map(int, m.groups())
        return f"{f}-{r:02d}-{n:02d}"

    return ""  # 解釈不能

def to_dt(sr):
    try:
        return pd.to_datetime(sr, errors="coerce")
    except Exception:
        return pd.to_datetime(sr.astype(str), errors="coerce")

def chain_compact(names):
    out, prev = [], None
    for x in names:
        x = (x or "").strip()
        if x and x != prev:
            out.append(x)
            prev = x
    return " → ".join(out)

# --------------- UI ---------------
f = st.file_uploader("teket販売履歴 CSV をアップロード", type=["csv"])
if not f:
    st.stop()

df = read_csv_any(f)
cols = df.columns.tolist()

# 列推定
seat_col = pick_col(cols, ["座席", "座席情報", "席", "座席名", "エリア/座席", "券面座席"])
purchase_time_col = pick_col(cols, ["購入日時", "注文日時", "購入日", "購入時間"])
status_col = pick_col(cols, ["処理", "ステータス", "状態"])
buyer_col = pick_col(cols, ["購入者", "購入者名", "注文者", "購入者氏名"])
to_col = pick_col(cols, ["受取者", "受取者名", "来場者", "来場者名", "譲渡先", "受取先"])

if not seat_col:
    st.error("座席列が見つかりません。列名例: 「座席」「席」「座席情報」")
    st.dataframe(df.head(30))
    st.stop()

# 席キー生成
df["席"] = df[seat_col].map(parse_seat)
missing = (df["席"] == "").sum()
if missing:
    st.warning(f"座席パースに失敗した行: {missing} 行。未解釈行は除外します。")
df = df[df["席"] != ""].copy()

# 時系列は購入日時ベース
if purchase_time_col:
    df["_event_dt"] = to_dt(df[purchase_time_col]).fillna(pd.Timestamp(0))
else:
    st.warning("「購入日時」系の列が見つからないため、行番号で代用します。")
    df["_event_dt"] = range(len(df))

# 所有者の推移情報
df["_from"] = df[buyer_col] if buyer_col else ""
df["_to"] = df[to_col] if to_col else df["_from"]

# キャンセル判定
cancel_words = ("キャンセル", "取消", "払戻", "返金", "無効")
if status_col:
    df["_is_cancel"] = df[status_col].apply(lambda s: any(w in str(s or "") for w in cancel_words))
else:
    df["_is_cancel"] = False

# 席ごとに時系列で集約
def reduce_group(g):
    g = g.sort_values("_event_dt", kind="mergesort")
    key = g["席"].iloc[0]

    # 所有者経路
    path = []
    for _, r in g.iterrows():
        f_, t_ = (r.get("_from", "") or "").strip(), (r.get("_to", "") or "").strip()
        if not path and (f_ or t_):
            path.append(f_ or t_)
        cur = path[-1] if path else ""
        nxt = t_ or f_
        if nxt and nxt != cur:
            path.append(nxt)

    final_owner = path[-1] if path else (g["_to"].dropna().iloc[-1] if not g["_to"].empty else "")
    last_dt = g["_event_dt"].iloc[-1]
    last_dt_str = last_dt.strftime("%Y-%m-%d %H:%M") if hasattr(last_dt, "strftime") else str(last_dt)
    canceled_flag = bool(g.iloc[-1].get("_is_cancel", False))

    return pd.Series({
        "席 (階-列-番)": key,
        "キャンセル": "キャンセル済み" if canceled_flag else "-",
        "経由": chain_compact(path),
        "最終所有者": final_owner,
        "最終購入日時": last_dt_str,
    })

out = df.groupby("席", sort=False).apply(reduce_group).reset_index(drop=True)

# 座席ソート: L < R < 数字
def seat_sort_key(s):
    m = re.match(r"(\d+)-([0-9LR]+)-(\d+)", str(s))
    if not m:
        return (9999, 9999, 9999)
    f, r, n = m.groups()
    if r == "L":
        rkey = -2
    elif r == "R":
        rkey = -1
    else:
        rkey = int(r)
    return (int(f), rkey, int(n))

out = out.sort_values("席 (階-列-番)", key=lambda x: x.map(seat_sort_key), kind="mergesort").reset_index(drop=True)

# 表示（主要列のみ）
show_cols = ["席 (階-列-番)", "キャンセル", "経由", "最終所有者", "最終購入日時"]
st.dataframe(out[show_cols], use_container_width=True, hide_index=True)

# ダウンロード
st.download_button(
    "席ごとの最終状態CSVをダウンロード",
    data=out[show_cols].to_csv(index=False).encode("utf-8-sig"),
    file_name="teket_席ごと最終状態.csv",
    mime="text/csv",
)

# 参考: 入力CSVの列
with st.expander("入力CSVの列（確認用）"):
    st.write(pd.DataFrame({"columns": cols}))
