

import yfinance as yf
import pandas as pd
import numpy as np
from tabulate import tabulate

# ==========================================
# ⚙️ 使用者設定 (請在此輸入您的庫存)
# ==========================================
# 格式: '代號': {'cost': 買入成本, 'stop_loss_pct': 初始停損% (書中建議 5-7%)}
MY_PORTFOLIO = {
    '4939.TW': {'cost': 51.2, 'stop_loss_pct': 0.07},  #
    '3346.TW': {'cost': 50.8, 'stop_loss_pct': 0.07}, #
    '2317.TWO': {'cost': 227.2, 'stop_loss_pct': 0.07} # (上櫃用 .TWO)
}

# ==========================================
# 核心邏輯
# ==========================================
def health_check(portfolio):
    print("🏥 正在為您的庫存進行「考特賣出法則」健檢...\n")
    results = []

    for ticker, data in portfolio.items():
        try:
            # 1. 抓取資料 (抓取足夠計算均線的天數)
            df = yf.download(ticker, period='6mo', progress=False, auto_adjust=True)
            if df.empty:
                print(f"❌ 找不到 {ticker} 資料")
                continue

            # 處理多層索引
            close = df['Close']
            if isinstance(close, pd.DataFrame): close = close.iloc[:, 0]

            # 2. 計算關鍵指標
            current_price = float(close.iloc[-1])
            cost = data['cost']
            init_risk_pct = data['stop_loss_pct']
            init_risk_amt = cost * init_risk_pct # 初始風險金額 (1R)

            # 均線
            ma10 = float(close.rolling(10).mean().iloc[-1])
            ma20 = float(close.rolling(20).mean().iloc[-1])
            ma50 = float(close.rolling(50).mean().iloc[-1])

            # 獲利狀況
            pnl_pct = (current_price - cost) / cost
            pnl_amt = current_price - cost
            r_multiple = pnl_amt / init_risk_amt # 目前賺了幾個 R

            # 3. 執行賣出法則判定
            action = "✅ 續抱"
            sell_price = 0.0
            reason = []

            # (A) 初始停損 (Hard Stop)
            hard_stop_price = cost * (1 - init_risk_pct)
            if current_price < hard_stop_price:
                action = "🛑 清倉賣出 (停損)"
                reason.append(f"觸發初始停損 (跌破 {round(hard_stop_price, 2)})")
                sell_price = current_price

            # (B) 第一法則：保本法則 (Breakeven) - 賺 2R 以上
            # 如果賺超過 2R，停損點上移至成本價
            elif r_multiple >= 2:
                # 檢查是否跌回成本
                if current_price < cost:
                    action = "🛑 清倉賣出 (保本)"
                    reason.append("獲利回吐觸及成本價 (Rule 1)")
                    sell_price = cost
                else:
                    reason.append(f"已達 2R ({round(r_multiple,1)}R)，停損上移至成本價 {cost}")

            # (C) 第二法則：獲利 3R 減碼 (Scale Out)
            if r_multiple >= 3:
                reason.append(f"獲利達 3R ({round(r_multiple,1)}R)，建議獲利了結一半 (Rule 2)")
                if action == "✅ 續抱": action = "💰 部分獲利"

            # (D) 第三/四法則：均線防守 (MA Rule)
            # 判斷是否為超級強勢股 (連續7週守住10日線 -> 這裡簡化為最近35天都在10MA上)
            is_super_strong = (close.iloc[-35:] > close.rolling(10).mean().iloc[-35:]).all()

            check_ma = ma10 if is_super_strong else ma20
            ma_name = "10MA" if is_super_strong else "20MA"

            if current_price < check_ma:
                if action != "🛑 清倉賣出 (停損)": # 如果還沒被停損
                    action = "⚠️ 警戒 / 賣出"
                    reason.append(f"跌破 {ma_name} ({round(check_ma, 2)})，趨勢轉弱 (Rule 3/4)")
                    sell_price = current_price
            else:
                reason.append(f"股價守穩 {ma_name} ({round(check_ma, 2)})")

            # (E) 整合建議賣出價 (若需賣出)
            # 如果目前是續抱，建議賣出價就是這三者的最高者：初始停損、成本(若達2R)、均線
            suggested_stop = hard_stop_price
            if r_multiple >= 2: suggested_stop = max(suggested_stop, cost)
            suggested_stop = max(suggested_stop, check_ma) # 動態防守

            results.append({
                "代號": ticker.replace('.TW', '').replace('.TWO', ''),
                "現價": round(current_price, 2),
                "成本": cost,
                "獲利(R)": f"{round(r_multiple, 1)}R",
                "建議動作": action,
                "建議防守價": round(suggested_stop, 2),
                "診斷原因": " | ".join(reason)
            })

        except Exception as e:
            print(f"分析 {ticker} 時發生錯誤: {e}")

    return pd.DataFrame(results)

# ==========================================
# 執行程式
# ==========================================
if __name__ == "__main__":
    df_result = health_check(MY_PORTFOLIO)

    if not df_result.empty:
        print("\n📊 庫存健檢報告 (依據書中法則)")
        print(tabulate(df_result, headers='keys', tablefmt='fancy_grid', showindex=False))
        print("\n💡 說明：")
        print("1. [獲利(R)]: 獲利金額 / 初始風險金額。書中建議 >3R 可減碼。")
        print("2. [建議防守價]: 若明日收盤價低於此價格，應執行賣出。")
    else:
        print("無資料")
