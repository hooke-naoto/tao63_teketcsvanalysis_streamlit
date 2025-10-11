import io
import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="teket席履歴 正規化ビュー", layout="wide")
st.title("teket 販売履歴 → 席ごとの最終状態ビュー")

# ========= ユーティリティ =========
def find_col(df, candidates):
    for col in df.columns:
        name = str(col)
        for cand in candidates:
            if all(k in name for k in cand if k):
                return col
    return None

def parse_seat_text(text):
    if pd.isna(text):
        return None
    s = str(text)

    m = re.search(r'(\d+)\s*階.*?(\d+)\s*列.*?(\d+)\s*番', s)
    if m:
        return tuple(map(int, m.groups()))

    m = re.search(r'(\d+)\s*[Ff\-ー‐− ]\s*(\d+)\s*[\-ー‐− ]\s*(\d+)', s)
    if m:
        return tuple(map(int, m.groups()))

    m_f = re.search(r'階[:：]?\s*(\d+)', s)
    m_r = re.search(r'列[:：]?\s*(\d+)', s)
    m_n = re.search(r'番[:：]?\s*(\d+)', s)
    if m_f and m_r and m_n:
        return int(m_f.group(1)), int(m_r.group(1)), int(m_n.group(1))
    return None

def seat_to_key(val):
    t = parse_seat_text(val)
    return t if t else None

def format_seat_key(tup):
    f, r, n = tup
    return f"{f:d}-{r:02d}-{n:02d}"

def normalize_datetime_series(s):
    return pd.to_datetime(s, errors="coerce", utc=False)

def is_cancel(text):
    if pd.isna(text):
        return False
    s = str(text)
    return any(k in s for k in ["キャンセル", "取消", "払戻", "返金", "無効"])

# ========== 入力 ==========
f = st.file_uploader("teket CSV（販売履歴）をアップロード", type=["csv"])
enc = st.selectbox("文字コード", ["cp932", "utf-8", "utf-8-sig"], index=0)

if not f:
    st.info("CSVを選択してください。")
    st.stop()

try:
    df = pd.read_csv(f, encoding=enc)
except Exception as e:
    st.error(f"読込失敗: {e}")
    st.stop()

if df.empty:
    st.warning("データが空です。")
    st.stop()

# ========== 列名推定 ==========
seat_col = find_col(df, [["座席"], ["座席番号"], ["席番"], ["席"], ["号"]]) or \
           find_col(df, [["チケット"]])

buyer_col = find_col(df, [["購入者"]]) or find_col(df, [["氏名"]]) or find_col(df, [["名前"]])
status_col = find_col(df, [["処理"]]) or find_col(df, [["ステータス"], ["状態"]])
sale_dt_col = (find_col(df, [["販売", "日時"]]) or
               find_col(df, [["購入", "日時"]]) or
               find_col(df, [["注文", "日時"]]) or
               find_col(df, [["日時"]]))
recv_dt_col = find_col(df, [["受取", "日時"]]) or find_col(df, [["引換", "日時"]]) or None

need = [("座席/チケット", seat_col), ("購入者", buyer_col), ("販売/購入日時", sale_dt_col)]
missing = [name for name, ok in need if ok is None]
if missing:
    st.error("必要列が見つかりません: " + ", ".join(missing))
    with st.expander("入力CSV 先頭プレビュー"):
        st.dataframe(df.head(30), use_container_width=True)
    st.stop()

# ========== 座席キー抽出 ==========
src_for_seat = df[seat_col].astype(str)
seat_key = src_for_seat.apply(seat_to_key)

bad = seat_key.isna().sum()
if bad > 0:
    st.warning(f"座席を特定できない行を {bad} 行スキップしました。")

df = df[~seat_key.isna()].copy()
if df.empty:
    out = pd.DataFrame(columns=["席", "状態", "経由", "最終受取日時"])
    st.warning("座席を特定できた行がありません。正規表現に合う座席表記か確認してください。")
    st.dataframe(out, use_container_width=True)
    st.stop()

df["__seat_key__"] = seat_key[~seat_key.isna()].values
df["__seat_str__"] = df["__seat_key__"].apply(format_seat_key)
df["__sale_dt__"] = normalize_datetime_series(df[sale_dt_col])
df["__recv_dt__"] = normalize_datetime_series(df[recv_dt_col]) if recv_dt_col else pd.NaT
df["__buyer__"] = df[buyer_col].astype(str) if buyer_col else "(不明)"
df["__status__"] = df[status_col].astype(str) if status_col else ""

# ========== 席ごとの履歴集約 ==========
rows = []
for seat, g in df.sort_values(["__seat_key__", "__sale_dt__"]).groupby("__seat_key__"):
    g = g.sort_values("__sale_dt__", kind="mergesort")
    buyers_seq = [b for b in g["__buyer__"].tolist() if pd.notna(b) and b != ""]
    chain = []
    for b in buyers_seq:
        if not chain or chain[-1] != b:
            chain.append(b)

    final_status = str(g["__status__"].iloc[-1])
    state = "キャンセル" if is_cancel(final_status) else "有効"
    recv_series = g["__recv_dt__"].dropna()
    final_recv_dt = recv_series.iloc[-1] if not recv_series.empty else pd.NaT

    rows.append({
        "席": format_seat_key(seat),
        "状態": state,
        "経由": " → ".join(chain),
        "最終受取日時": final_recv_dt
    })

out = pd.DataFrame(rows, columns=["席", "状態", "経由", "最終受取日時"])

# ======= ここが修正点: 空/列欠落を防御して整列 =======
if out.empty:
    st.warning("出力行がありません。フィルタ条件や座席抽出ロジックを確認してください。")
else:
    if "席" in out.columns:
        out = out.sort_values("席", kind="mergesort").reset_index(drop=True)

# 表示
st.dataframe(out, use_container_width=True)

# ダウンロード
buf = io.StringIO()
out.to_csv(buf, index=False, encoding="utf-8-sig")
st.download_button(
    "席ごとの最終状態 CSV をダウンロード",
    data=buf.getvalue().encode("utf-8-sig"),
    file_name="teket_seat_final_state.csv",
    mime="text/csv",
)

with st.expander("入力CSV 先頭プレビュー（内部列除く）"):
    st.dataframe(
        df.drop(columns=[c for c in df.columns if c.startswith("__")], errors="ignore").head(20),
        use_container_width=True
    )
