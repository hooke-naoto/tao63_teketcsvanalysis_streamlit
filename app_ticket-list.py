import pandas as pd
import streamlit as st
import re

st.set_page_config(page_title="teket 座席 最終状態サマリ", layout="centered")
st.title("teket 販売履歴｜座席ごとの最終状態サマリ（列・番2桁表示）")

def try_read_csv(file):
    for enc in ["cp932", "utf-8-sig", "utf-8"]:
        try:
            return pd.read_csv(file, encoding=enc)
        except Exception:
            continue
    st.error("CSVの読込に失敗しました。")
    st.stop()

def guess_col(cols, candidates):
    for c in candidates:
        if c in cols:
            return c
    return None

def normalize_datetime(s):
    return pd.to_datetime(s, errors="coerce")

def build_chain(rows, actor_col, partner_col, status_col):
    chain = []
    current = None
    for _, r in rows.iterrows():
        actor = str(r.get(actor_col, "")).strip()
        partner = str(r.get(partner_col, "")).strip() if partner_col else ""
        status = str(r.get(status_col, "")).strip() if status_col else ""
        if current is None and actor:
            current = actor
            chain.append(current)
        if partner:
            if not chain:
                if actor:
                    chain.append(actor)
            if not chain or chain[-1] != partner:
                chain.append(partner)
            current = partner
        if not partner and actor and current and actor != current and status and ("譲渡" in status or "受取" in status):
            chain.append(actor)
            current = actor
    dedup = []
    for name in chain:
        if not dedup or dedup[-1] != name:
            dedup.append(name)
    final_owner = dedup[-1] if dedup else (current or "")
    # 「→」を「 -> 」に統一
    return " -> ".join(dedup) if dedup else "", final_owner

def format_seat(x):
    s = str(x)
    m = re.search(r"(\d+)\D+(\d+)", s)
    if not m:
        return s.strip()
    col = f"{int(m.group(1)):02d}"
    num = f"{int(m.group(2)):02d}"
    return f"{col}-{num}"

f = st.file_uploader("teket CSV (販売履歴) をアップロード", type=["csv"])
if not f:
    st.info("CSVを選択してください。")
    st.stop()

df = try_read_csv(f)

seat_col     = guess_col(df.columns, ["席", "座席", "座席番号", "席情報", "チケット"])
time_col     = guess_col(df.columns, ["購入日時"])  # 固定
status_col   = guess_col(df.columns, ["処理", "ステータス", "状態"])
owner_col    = guess_col(df.columns, ["購入者", "所有者", "名義", "注文者"])
partner_col  = guess_col(df.columns, ["譲渡先", "受取者", "相手", "受領者", "譲渡相手"])

seat_id = df[seat_col].map(format_seat)
work = df.copy()
work["_seat_id_"] = seat_id
work["_ts_"] = normalize_datetime(work[time_col])
work = work.sort_values(by=["_seat_id_", "_ts_"], ascending=[True, True])

records = []
for seat, rows in work.groupby("_seat_id_", dropna=False):
    rows = rows.copy()
    last = rows.iloc[-1]
    status_last = str(last.get(status_col, "")).strip()
    canceled = any(k in status_last for k in ["キャンセル", "取消", "返金", "無効"])
    receive_like = rows[rows[status_col].astype(str).str.contains("受取|有料受取|無料受取|購入完了|発券|入場", regex=True, na=False)]
    final_receive_at = (receive_like.iloc[-1][time_col]
                        if len(receive_like) > 0 else last[time_col])
    chain, final_owner = build_chain(rows, owner_col, partner_col, status_col)
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
        "キャンセル": "キャンセル済み" if canceled else "-",
        "譲渡経路": chain if chain else str(rows.iloc[0].get(owner_col, "")),
        "最終所有者": final_owner if final_owner else str(rows.iloc[-1].get(owner_col, "")),
        "最終受取日時": final_receive_at
    })

out = pd.DataFrame(records)
display_cols = ["席", "キャンセル", "譲渡経路", "最終所有者", "最終受取日時"]
if "種別" in out.columns and out["種別"].notna().any():
    display_cols = ["席", "種別"] + display_cols[1:]
out_sorted = out.sort_values(by=["席"], ascending=True)[display_cols].reset_index(drop=True)

st.dataframe(out_sorted, use_container_width=True, hide_index=True)

csv = out_sorted.to_csv(index=False).encode("utf-8-sig")
st.download_button("座席サマリをCSVでダウンロード", data=csv, file_name="teket_seat_summary.csv", mime="text/csv")
