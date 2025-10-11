# 変更点のみ（前回コードに差し替え）
def reduce_group(g):
    g = g.sort_values("_event_dt", kind="mergesort")
    key = g["席"].iloc[0]

    path = []
    for _, r in g.iterrows():
        f, t = (r.get("_from","") or "").strip(), (r.get("_to","") or "").strip()
        if not path and (f or t): path.append(f or t)
        cur = path[-1] if path else ""
        nxt = t or f
        if nxt and nxt != cur: path.append(nxt)

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

# 集約・並べ替え後の列表示
out = df.groupby("席", sort=False).apply(reduce_group).reset_index(drop=True)

def seat_sort_key(s):
    m = re.match(r"(\d+)-([0-9LR]+)-(\d+)", str(s))
    if not m: return (9999, 9999, 9999)
    f, r, n = m.groups()
    if r == "L": rkey = -2
    elif r == "R": rkey = -1
    else: rkey = int(r)
    return (int(f), rkey, int(n))

out = out.sort_values("席 (階-列-番)", key=lambda x: x.map(seat_sort_key), kind="mergesort").reset_index(drop=True)

show_cols = ["席 (階-列-番)", "キャンセル", "経由", "最終所有者", "最終購入日時"]
st.dataframe(out[show_cols], use_container_width=True, hide_index=True)

st.download_button(
    "席ごとの最終状態CSVをダウンロード",
    data=out[show_cols].to_csv(index=False).encode("utf-8-sig"),
    file_name="teket_席ごと最終状態_LR強化.csv",
    mime="text/csv",
)
