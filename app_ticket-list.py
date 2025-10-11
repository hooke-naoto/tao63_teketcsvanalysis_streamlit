import io
import re
import sys
import pandas as pd
import streamlit as st

st.set_page_config(page_title="teket席履歴 正規化ビュー", layout="wide")
st.title("teket 販売履歴 → 席ごとの最終状態ビュー")

# ========= ユーティリティ =========
def find_col(df, candidates):
    """候補語をすべて含む列名を優先順で探索（部分一致, 日本語想定）"""
    for col in df.columns:
        name = str(col)
        for cand in candidates:
            if all(k in name for k in cand if k):  # 複合キーワード
                return col
    return None

def parse_seat_text(text):
    """
    '1階3列12番' / '1階 3列 12番' / '1F-3-12' などから (floor,row,number) を抽出
    数字が取れない場合は None
    """
    if pd.isna(text):
        return None
    s = str(text)

    # パターン1: 「(\d+)階.*?(\d+)列.*?(\d+)番」
    m = re.search(r'(\d+)\s*階.*?(\d+)\s*列.*?(\d+)\s*番', s)
    if m:
        f, r, n = map(int, m.groups())
        return f, r, n

    # パターン2: 「1F-3-12」「1f 3 12」
    m = re.search(r'(\d+)\s*[Ff\-ー‐− ]\s*(\d+)\s*[\-ー‐− ]\s*(\d+)', s)
    if m:
        f, r, n = map(int, m.groups())
        return f, r, n

    # パターン3: 「階:1 列:3 番:12」風
    m_f = re.search(r'階[:：]?\s*(\d+)', s)
    m_r = re.search(r'列[:：]?\s*(\d+)', s)
    m_n = re.search(r'番[:：]?\s*(\d+)', s)
    if m_f and m_r and m_n:
        return int(m_f.group(1)), int(m_r.group(1)), int(m_n.group(1))

    return None

def seat_to_key(val):
    """
    座席文字列 → (floor,row,number) 正規化
    """
    t = parse_seat_text(val)
    if not t:
        return None
    f, r, n = t
    return f, r, n

def format_seat_key(tup):
    """(floor,row,number) → 'x-xx-xx' 形式"""
    f, r, n = tup
    return f"{f:d}-{r:02d}-{n:02d}"

def normalize_datetime_series(s):
    """和暦なし前提。失敗はNaT。秒まで許容。"""
    return pd.to_datetime(s, errors="coerce", format=None, utc=False)

def is_cancel(text):
    """処理欄からキャンセル類推"""
    if pd.isna(text):
        return False
    s = str(text)
    return any(k in s for k in ["キャンセル", "取消", "払戻", "返金", "無効"])

# ========== 入力 ==========
f = st.file_uploader("teket CSV（販売履歴）をアップロード", type=["csv"])
enc = st.selectbox("文字コード", ["cp932", "utf-8", "utf-8-sig"], index=0)

if not f:
    st.info("CSVを選択してください。想定列の例：購入者 / 処理 / 販売日時 or 購入日時 / 受取日時 / 座席 or チケット")
    st.stop()

# 読み込み
try:
    df = pd.read_csv(f, encoding=enc)
except Exception as e:
    st.error(f"読込失敗: {e}")
    st.stop()

if df.empty:
    st.warning("データが空です。")
    st.stop()

# ========== 列名推定 ==========
# 座席情報は「座席 / 座席番号 / 席 / 号」など、またはチケット列中のテキストに含まれる想定
seat_col = find_col(df, [["座席"], ["座席番号"], ["席番"], ["席"], ["号"]]) or \
           find_col(df, [["チケット"]])

buyer_col = find_col(df, [["購入者"]]) or find_col(df, [["氏名"]]) or find_col(df, [["名前"]])
status_col = find_col(df, [["処理"]]) or find_col(df, [["ステータス"], ["状態"]])
sale_dt_col = (find_col(df, [["販売", "日時"]]) or
               find_col(df, [["購入", "日時"]]) or
               find_col(df, [["注文", "日時"]]) or
               find_col(df, [["日時"]]))
recv_dt_col = find_col(df, [["受取", "日時"]]) or find_col(df, [["引換", "日時"]]) or None

missing = [("座席/チケット", seat_col), ("購入者", buyer_col), ("販売/購入日時", sale_dt_col)]
missing = [name for name, ok in missing if ok is None]
if missing:
    st.error("必要列が見つかりません: " + ", ".join(missing))
    st.dataframe(df.head(30), use_container_width=True)
    st.stop()

# ========== 座席キー抽出 ==========
src_for_seat = df[seat_col].astype(str)

# チケット列に「S席 1階3列12番」のように混在する場合にも対応
seat_key = src_for_seat.apply(seat_to_key)

# 取り出せない行は捨てる（スマホ表示の明快さ優先）
bad = seat_key.isna().sum()
if bad > 0:
    st.warning(f"座席を特定できない行を {bad} 行スキップしました。")

df = df[~seat_key.isna()].copy()
df["__seat_key__"] = seat_key[~seat_key.isna()].values
df["__seat_str__"] = df["__seat_key__"].apply(format_seat_key)

# 時刻正規化
df["__sale_dt__"] = normalize_datetime_series(df[sale_dt_col])
if recv_dt_col:
    df["__recv_dt__"] = normalize_datetime_series(df[recv_dt_col])
else:
    df["__recv_dt__"] = pd.NaT

# 安全のため、購入者・処理は文字列化
if buyer_col:
    df["__buyer__"] = df[buyer_col].astype(str)
else:
    df["__buyer__"] = "(不明)"

if status_col:
    df["__status__"] = df[status_col].astype(str)
else:
    df["__status__"] = ""

# ========== 席ごとの履歴集約 ==========
out_rows = []
for seat, g in df.sort_values(["__seat_key__", "__sale_dt__"]).groupby("__seat_key__"):
    g = g.sort_values("__sale_dt__", kind="mergesort")
    buyers_seq = [b for b in g["__buyer__"].tolist() if pd.notna(b) and b != ""]
    # 同一連続名の重複は圧縮
    buyers_chain = []
    for b in buyers_seq:
        if not buyers_chain or buyers_chain[-1] != b:
            buyers_chain.append(b)

    final_status_text = str(g["__status__"].iloc[-1])
    canceled = is_cancel(final_status_text)
    state = "キャンセル" if canceled else "有効"

    # 最終受取日時: 受取日時列の最終有効値。なければ NaT のまま
    final_recv = g["__recv_dt__"].dropna()
    final_recv_dt = final_recv.iloc[-1] if not final_recv.empty else pd.NaT

    out_rows.append({
        "席": format_seat_key(seat),
        "状態": state,
        "経由": " → ".join(buyers_chain) if buyers_chain else "",
        "最終受取日時": final_recv_dt
    })

out = pd.DataFrame(out_rows)
out = out.sort_values(["席"], kind="mergesort").reset_index(drop=True)

# 表示（スマホ最適化）
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

# 参考: 元CSVの先頭行確認（デバッグ用に折りたたみ）
with st.expander("入力CSV 先頭プレビュー"):
    st.dataframe(df.head(20).drop(columns=[c for c in df.columns if c.startswith("__")], errors="ignore"),
                 use_container_width=True)
