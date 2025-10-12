# app.py
import io
import pandas as pd
import streamlit as st

st.title("購入者別 集計（クーポン TAO1013gregor / 受取除外）")

f = st.file_uploader("teket 販売履歴 CSV をアップロード", type=["csv"])
if not f:
    st.stop()

# 文字コードの自動救済
read_ok = False
for enc in ["cp932", "utf-8-sig", "utf-8"]:
    try:
        df = pd.read_csv(f, encoding=enc)
        read_ok = True
        break
    except Exception:
        f.seek(0)
if not read_ok:
    st.error("CSVの読み込みに失敗しました。文字コードを確認してください。")
    st.stop()

required = {"購入者", "処理", "クーポン", "チケット"}
missing = required - set(df.columns)
if missing:
    st.error(f"必要列が不足: {', '.join(sorted(missing))}")
    st.stop()

# 条件: 処理 列が「無料受取」「有料受取」以外、かつ クーポン=TAO1013gregor
mask = (~df["処理"].isin(["無料受取", "有料受取"])) & (df["クーポン"].fillna("") == "TAO1013gregor")
df = df.loc[mask].copy()

if df.empty:
    st.warning("条件に合致するデータがありません。")
    st.stop()

# 座席フラグ
df["S席フラグ"] = df["チケット"].astype(str).str.startswith("S席")
df["A席フラグ"] = df["チケット"].astype(str).str.startswith("A席")

# 集計
g = df.groupby("購入者", dropna=False, sort=False)
out = pd.DataFrame({
    "購入者": g.size().index,
    "各購入者の購入総数": (g["S席フラグ"].sum() + g["A席フラグ"].sum()).values,
    "各購入者のS席購入数": g["S席フラグ"].sum().values,
    "各購入者のA席購入数": g["A席フラグ"].sum().values,
})

# 並べ替え
out = out.sort_values(["各購入者の購入総数", "購入者"], ascending=[False, True], kind="mergesort").reset_index(drop=True)

st.dataframe(out, use_container_width=True)

# ダウンロード
csv_bytes = out.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "集計CSVをダウンロード",
    data=csv_bytes,
    file_name="teket_購入者別集計.csv",
    mime="text/csv",
)
