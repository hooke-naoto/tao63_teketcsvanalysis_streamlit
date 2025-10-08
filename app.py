import pandas as pd
import streamlit as st

st.title("TAO クーポン利用集計")

f = st.file_uploader("販売履歴CSVを選択", type=["csv"])
if f:
    df = pd.read_csv(f, encoding="cp932")
    df = df[(df["クーポン"]=="TAO1013gregor") & ~df["処理"].isin(["無料受取","有料受取"])]
    df["S席"] = df["チケット"].str.startswith("S席")
    df["A席"] = df["チケット"].str.startswith("A席")
    out = df.groupby("購入者")[["S席","A席"]].sum().astype(int)
    out["合計枚数"] = out["S席"] + out["A席"]
    st.dataframe(out.sort_values("合計枚数", ascending=False))
    st.download_button("CSVダウンロード", out.to_csv().encode("utf-8-sig"), file_name="集計結果.csv")
