# app.py
import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="teket 席ごとの最終状態サマリ", layout="wide")
st.title("teket 販売履歴 → 席ごと最終状態サマリ（購入日時ベース）")

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
        if c in cols: return c
    for c in cands:
        for col in cols:
            if c in col: return col
    return None

def parse_seat(raw):
    s = str(raw)
    m = re.search(r"(\d+)\s*階.*?(\d+)\s*列.*?(\d+)\s*番", s)
    if m:
        f, r, n = map(int, m.groups())
        return f"{f}-{r:02d}-{n:02d}"
    digs = re.findall(r"\d+", s)
    if len(digs) >= 3:
        try:
            f, r, n = map(int, digs[:3])
            return f"{f}-{r:02d}-{n:02d}"
        except:
            return ""
    return ""

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
            out.append(x); prev = x
    return " → ".join(out)

f = st.file_uploader("teket販売履歴 CSV をアップロード", type=["csv"])
if not f: st.stop()

df = read_csv_any(f)
cols = df.columns.tolist()

# 列推定
seat_col = pick_col(cols, ["座席","座席情報","席","座席名","エリア/座席","券面座席"])
# 「購入日時」を最優先
purchase_time_col = pick_col(cols, ["購入日時","注文日時","購入日","購入時間"])
status_col  = pick_col(cols, ["処理","ステータス","状態"])
buyer_col   = pick_col(cols, ["購入者","購入者名","注文者","購入者氏名"])
to_col      = pick_col(cols, ["受取者","受取者名","来場者","来場者名","譲渡先","受取先"])

if not seat_col:
    st.error("座席列が見つかりません。列名例: 「座席」「席」「座席情報」")
    st.dataframe(df.head(30)); st.stop()

# 席キー
df["席"] = df[seat_col].map(parse_seat)
df = df[df["席"] != ""].copy()

# 時系列は「購入日時」を基準
if purchase_time_col:
    df["_event_dt"] = to_dt(df[purchase_time_col]).fillna(pd.Timestamp(0))
else:
    st.warning("「購入日時」系の列が見つからないため、行番号で代用します。")
    df["_event_dt"] = range(len(df))

# 所有者のfrom/to
df["_from"] = df[buyer_col] if buyer_col else ""
df["_to"]   = df[to_col] if to_col else df["_from"]

# キャンセル判定
cancel_words = ("キャンセル","取消","払戻","返金","無効")
def is_canceled(s):
    s = str(s or "")
    return any(w in s for w in cancel_words)
df["_is_cancel"] = df[status_col].apply(is_canceled) if status_col else False

# グループ集約（購入日時で並べ替え）
def reduce_group(g):
    g = g.sort_values("_event_dt", kind="mergesort")
    key = g["席"].iloc[0]

    path = []
    for _, r in g.iterrows():
        f, t = (r.get("_from","") or "").strip(), (r.get("_to","") or "").strip()
        if not path:
            if f or t: path.append(f or t)
        cur = path[-1] if path else ""
        nxt = t or f
        if nxt and nxt != cur:
            path.append(nxt)

    final_owner = path[-1] if path else (g["_to"].dropna().iloc[-1] if not g["_to"].empty else "")
    last = g.iloc[-1]
    canceled = bool(last.get("_is_cancel", False))

    # 最終購入日時（この席に関する最後の購入イベント時刻）
    last_purchase_dt = g["_event_dt"].iloc[-1]
    last_purchase_str = last_purchase_dt.strftime("%Y-%m-%d %H:%M") if hasattr(last_purchase_dt, "strftime") else str(last_purchase_dt)

    return pd.Series({
        "席": key,
        "キャンセル": "はい" if canceled else "いいえ",
        "経由": chain_compact(path),
        "最終所有者": final_owner,
        "最終購入日時": last_purchase_str,
    })

out = df.groupby("席", sort=False).apply(reduce_group).reset_index(drop=True)

# 座席ソート
def seat_sort_key(s):
    m = re.match(r"(\d+)-(\d+)-(\d+)", str(s))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (9999,9999,9999)

out = out.sort_values("席", key=lambda x: x.map(seat_sort_key), kind="mergesort").reset_index(drop=True)

# 表示（スマホ向け主要列のみ）
show_cols = ["席","キャンセル","経由","最終所有者","最終購入日時"]
st.dataframe(out[show_cols], use_container_width=True, hide_index=True)

st.download_button(
    "席ごとの最終状態CSVをダウンロード",
    data=out[show_cols].to_csv(index=False).encode("utf-8-sig"),
    file_name="teket_席ごと最終状態_購入日時ベース.csv",
    mime="text/csv",
)

with st.expander("入力CSVの列見取り図"):
    st.write(pd.DataFrame({"columns": cols}))
