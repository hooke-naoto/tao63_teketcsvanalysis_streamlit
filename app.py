import pandas as pd
import streamlit as st

st.title("TAO63 団員の配布数ランキング from teket CSV")

f = st.file_uploader("teket CSV (販売履歴) をアップロード", type=["csv"])
if f:
    df = pd.read_csv(f, encoding="cp932")

    # 共通前処理
    df["クーポン"] = df["クーポン"].fillna("").astype(str)
    df = df[~df["処理"].isin(["無料受取","有料受取"])]  # 受取系を除外
    df["S席"] = df["チケット"].astype(str).str.startswith("S席")
    df["A席"] = df["チケット"].astype(str).str.startswith("A席")

    # 1) 指定クーポン利用者のランキング（既存機能）
    df_coupon = df[df["クーポン"] == "TAO1013gregor"].copy()
    out_coupon = (
        df_coupon.groupby("購入者")[["S席","A席"]]
        .sum()
        .astype(int)
        .rename(columns={"S席":"S席枚数","A席枚数":"A席枚数"} , errors="ignore")
    )
    # 列名を明示
    out_coupon.columns = ["S席枚数","A席枚数"] if list(out_coupon.columns)==["S席","A席"] else out_coupon.columns
    out_coupon["合計枚数"] = out_coupon.get("S席枚数",0) + out_coupon.get("A席枚数",0)
    out_coupon = out_coupon.sort_values("合計枚数", ascending=False)

    st.subheader("指定クーポン利用: 団員の配布数ランキング")
    st.dataframe(out_coupon)
    st.download_button(
        "団員の配布数ランキング CSVダウンロード",
        out_coupon.to_csv(encoding="utf-8-sig"),
        file_name="集計結果_クーポン利用.csv"
    )

    # 2) クーポン未使用の購入を抽出し、購入数（=枚数）降順の表 + 合計行
    df_no_coupon = df[df["クーポン"] == ""].copy()
    out_no_coupon = (
        df_no_coupon.groupby("購入者")[["S席","A席"]]
        .sum()
        .astype(int)
    )
    # 列名整形
    out_no_coupon.columns = ["S席枚数","A席枚数"] if list(out_no_coupon.columns)==["S席","A席"] else out_no_coupon.columns
    if "S席枚数" not in out_no_coupon.columns:
        out_no_coupon["S席枚数"] = 0
    if "A席枚数" not in out_no_coupon.columns:
        out_no_coupon["A席枚数"] = 0

    out_no_coupon["合計枚数"] = out_no_coupon["S席枚数"] + out_no_coupon["A席枚数"]
    out_no_coupon = out_no_coupon.sort_values("合計枚数", ascending=False)

    # 合計行を追加
    total_row = pd.DataFrame(
        {
            "S席枚数": [out_no_coupon["S席枚数"].sum()],
            "A席枚数": [out_no_coupon["A席枚数"].sum()],
            "合計枚数": [out_no_coupon["合計枚数"].sum()],
        },
        index=["合計"]
    )
    out_no_coupon_with_total = pd.concat([out_no_coupon, total_row])

    st.subheader("クーポン未使用: 購入数ランキング（合計行あり）")
    st.dataframe(out_no_coupon_with_total)

    st.download_button(
        "クーポン未使用ランキング CSVダウンロード",
        out_no_coupon_with_total.to_csv(encoding="utf-8-sig"),
        file_name="集計結果_クーポン未使用.csv"
    )
