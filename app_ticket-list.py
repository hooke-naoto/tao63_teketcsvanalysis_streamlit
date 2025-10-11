import pandas as pd
import streamlit as st
import re

st.set_page_config(page_title="teket 座席 最終状態サマリ", layout="centered")
st.title("teket 販売履歴｜座席ごとの最終状態サマリ")

def try_read_csv(file):
    # 文字コード自動リトライ
    for enc in ["cp932", "utf-8-sig", "utf-8"]:
        try:
            return pd.read_csv(file, encoding=enc)
        except Exception:
            continue
    st.error("CSVの読込に失敗しました。文字コードをご確認ください。")
    st.stop()

def guess_col(cols, candidates):
    for c in candidates:
        if c in cols:
            return c
    return None

def normalize_datetime(s):
    # teket出力の和暦は想定外。一般的な日時文字列を想定
    return pd.to_datetime(s, errors="coerce")

def build_chain(rows, actor_col, partner_col, status_col):
    """座席単位の時系列から譲渡経路の文字列と最終所有者を作る"""
    chain = []
    current = None
    for _, r in rows.iterrows():
        actor = str(r.get(actor_col, "")).strip()
        partner = str(r.get(partner_col, "")).strip() if partner_col else ""
        status = str(r.get(status_col, "")).strip() if status_col else ""
        # 初回購入者
        if current is None and actor:
            current = actor
            chain.append(current)
        # 譲渡や受取があれば相手をつなぐ
        if partner:
            if not chain:
                if actor:
                    chain.append(actor)
            if not chain or chain[-1] != partner:
                chain.append(partner)
            current = partner
        # 受取主体が別列に出る形式にも一部対応（partnerが空でも所有者が変わったらつなぐ）
        if not partner and actor and current and actor != current and status and ("譲渡" in status or "受取" in status):
            chain.append(actor)
            current = actor
    # 連続重複を削除
    dedup = []
    for name in chain:
        if not dedup or dedup[-1] != name:
            dedup.append(name)
    final_owner = dedup[-1] if dedup else (current or "")
    return " → ".join(dedup) if dedup else "", final_owner

f = st.file_uploader("teket CSV (販売履歴) をアップロード", type=["csv"])
if not f:
    st.info("CSVを選択してください。例：0054414_販売履歴_YYYYMMDDHHMMSS.csv")
    st.stop()

df = try_read_csv(f)

# 代表的な列名の推測
seat_col     = guess_col(df.columns, ["席", "座席", "座席番号", "席情報", "チケット"])
time_col     = guess_col(df.columns, ["処理日時", "日時", "購入日時", "更新日時"])
status_col   = guess_col(df.columns, ["処理", "ステータス", "状態"])
owner_col    = guess_col(df.columns, ["購入者", "所有者", "名義", "注文者"])
partner_col  = guess_col(df.columns, ["譲渡先", "受取者", "相手", "受領者", "譲渡相手"])

with st.expander("列の自動判定が不正確な場合はここで修正"):
    cols = list(df.columns)
    seat_col   = st.selectbox("座席を識別する列", options=cols, index=cols.index(seat_col) if seat_col in cols else 0)
    time_col   = st.selectbox("時系列を表す日時列", options=cols, index=cols.index(time_col) if time_col in cols else 0)
    status_col = st.selectbox("状態/処理の列", options=cols, index=cols.index(status_col) if status_col in cols else 0)
    owner_col  = st.selectbox("購入者/所有者の列", options=cols, index=cols.index(owner_col) if owner_col in cols else 0)
    partner_col = st.selectbox("譲渡先/受取者の列（無ければ空を選択）", options=["<なし>"] + cols, index=0 if partner_col is None else (1 + cols.index(partner_col)))
    partner_col = None if partner_col == "<なし>" else partner_col

# 「チケット」列に座席文字列が含まれている場合の簡易抽出（例：'S席 1列12番' → '1-12'）
def extract_seat_token(x):
    s = str(x)
    # 数字-数字のパターンを優先（例：12-34）
    m = re.search(r"(\d+)\D+(\d+)", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    # そのまま返す
    return s

seat_id = df[seat_col].copy()
if seat_col == "チケット":
    seat_id = df[seat_col].map(extract_seat_token)

work = df.copy()
work["_seat_id_"] = seat_id
work["_ts_"] = normalize_datetime(work[time_col])

# 並び替え
work = work.sort_values(by=["_seat_id_", "_ts_"], ascending=[True, True])

# 集約ロジック
records = []
for seat, rows in work.groupby("_seat_id_", dropna=False):
    rows = rows.copy()
    # 最終行
    last = rows.iloc[-1]

    # キャンセル判定
    status_last = str(last.get(status_col, "")).strip()
    canceled = any(k in status_last for k in ["キャンセル", "取消", "返金", "無効"])

    # 受取完了とみなす状態の候補
    receive_like = rows[rows[status_col].astype(str).str.contains("受取|有料受取|無料受取|購入完了|発券|入場", regex=True, na=False)]
    final_receive_at = (receive_like.iloc[-1][time_col]
                        if len(receive_like) > 0 else last[time_col])

    # 譲渡経路と最終所有者
    chain, final_owner = build_chain(rows, owner_col, partner_col, status_col)

    # S/A席などの種別が分かる場合は付加（任意）
    seat_class = ""
    ticket_str = str(rows.iloc[-1].get("チケット", ""))
    for tag in ["S席", "A席", "B席", "自由席"]:
        if tag in str(rows.iloc[-1].get(seat_col, "")) or tag in ticket_str:
            seat_class = tag
            break

    records.append({
        "席": seat,
        "種別": seat_class,
        "最終状態": status_last,
        "キャンセル": "✅ キャンセル済" if canceled else "✔︎ 有効",
        "譲渡経路": chain if chain else str(rows.iloc[0].get(owner_col, "")),
        "最終所有者": final_owner if final_owner else str(rows.iloc[-1].get(owner_col, "")),
        "最終受取日時": final_receive_at
    })

out = pd.DataFrame(records)

# 表示をスマホ向けに最小列で
display_cols = ["席", "キャンセル", "譲渡経路", "最終所有者", "最終受取日時"]
# 種別があれば先頭付近に追加
if "種別" in out.columns and out["種別"].notna().any():
    display_cols = ["席", "種別"] + display_cols[1:]

out_sorted = out.sort_values(by=["席"], ascending=True)[display_cols].reset_index(drop=True)

st.dataframe(
    out_sorted,
    use_container_width=True,
    hide_index=True
)

# ダウンロード
csv = out_sorted.to_csv(index=False).encode("utf-8-sig")
st.download_button("座席サマリをCSVでダウンロード", data=csv, file_name="teket_seat_summary.csv", mime="text/csv")
