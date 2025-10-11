import pandas as pd
import streamlit as st

st.title("TAO63 団員の配布数ランキング from teket CSV")

f = st.file_uploader("teket CSV (販売履歴) をアップロード", type=["csv"])
if f:
    # 元データを保持
    df_raw = pd.read_csv(f, encoding="cp932")

    # ===== 既存の集計（そのまま維持） =====
    df = df_raw.copy()
    try:
        df = df[(df["クーポン"]=="TAO1013gregor") & ~df["処理"].isin(["無料受取","有料受取"])]
        df["S席"] = df["チケット"].str.startswith("S席")
        df["A席"] = df["チケット"].str.startswith("A席")
        out = df.groupby("購入者")[["S席","A席"]].sum().astype(int)
        out["合計枚数"] = out["S席"] + out["A席"]
        st.subheader("団員の配布数ランキング")
        st.dataframe(out.sort_values("合計枚数", ascending=False), use_container_width=True)
        st.download_button("団員の配布数ランキング CSVダウンロード",
                           out.to_csv(index=True).encode("utf-8-sig"),
                           file_name="集計結果.csv")
    except Exception as e:
        st.warning(f"既存集計の実行をスキップ: {e}")

    # ===== 席ごとの最終状態ハイライト（追加機能） =====
    st.subheader("席ごとの最終状態ハイライト")

    # 席列の推定
    seat_candidates = ["席", "座席", "座席番号", "席情報", "Seat", "座席情報"]
    seat_col = next((c for c in seat_candidates if c in df_raw.columns), None)
    if seat_col is None:
        st.warning("席情報の列が見つからないため、この表示をスキップ。候補: " + ", ".join(seat_candidates))
    else:
        df_seat = df_raw.copy()

        # 時刻列の推定（あれば最新判定に使用）
        time_candidates = [c for c in df_seat.columns if any(k in c for k in ["日時","時間","時刻","date","Date","time","Time"])]
        time_col = time_candidates[0] if time_candidates else None
        if time_col:
            # 解析可能なものだけでソート
            t = pd.to_datetime(df_seat[time_col], errors="coerce")
            df_seat = df_seat.assign(__time__=t).sort_values(["__time__"], ascending=True)
        else:
            # CSV行順で最新を判断
            df_seat = df_seat.reset_index(drop=False).rename(columns={"index":"__row__"})

        # 最終行フラグ作成（各席の最後の出現）
        last_mask = ~df_seat.duplicated(subset=[seat_col], keep="last")
        last_idx = df_seat.index[last_mask]

        # 表示用整形：席列を先頭、席で昇順
        cols = [seat_col] + [c for c in df_seat.columns if c not in [seat_col, "__time__", "__row__"]]
        df_view = df_seat[cols].sort_values(by=seat_col, ascending=True)

        # 太字適用のためにインデックス基準で判定
        last_idx_set = set(last_idx)
        def _bold_last(s):
            return ["font-weight: bold" if i in last_idx_set else "" for i in s.index]

        # pandas Styler → HTML で確実に太字表示
        styled_html = df_view.style.apply(_bold_last, axis=0).to_html()
        st.markdown(styled_html, unsafe_allow_html=True)

        # ダウンロード（見た目は太字にならないが内容は同じ）
        st.download_button(
            "席ごとの履歴 CSVダウンロード",
            df_view.to_csv(index=False).encode("utf-8-sig"),
            file_name="席ごとの履歴.csv",
        )
