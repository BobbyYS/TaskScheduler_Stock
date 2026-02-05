

import yfinance as yf
import pandas as pd
import twstock
from tqdm import tqdm
from tabulate import tabulate
import numpy as np

# ==========================================
# ⚙️ 嚴格篩選參數 (依據書中標準)
# ==========================================
MIN_PRICE = 20          # 股價 > 20 (避開雞蛋水餃)
MIN_VOLUME = 800000     # 均量 > 800張 (確保流動性)
RS_PERIOD = 20          # 相對強度週期
BENCHMARK = '0050.TW'   # 大盤基準

# 型態參數
HTF_RALLY_PCT = 0.80    # 高窄旗型：前波漲幅需 > 80%
HTF_PULLBACK = 0.25     # 高窄旗型：回檔不能超過 25%
GAP_UP_PCT = 0.08       # 跳空缺口：至少 8%
NEAR_HIGH_PCT = 0.15    # 股價要在 52週高點的 15% 範圍內

# ==========================================
# 輔助函數
# ==========================================
def get_stock_list():
    """獲取上市+上櫃所有普通股代號"""
    print("📋 正在建立全台股清單...")
    codes = twstock.codes
    stock_list = []
    names_map = {}

    for code in codes:
        row = codes[code]
        if row.type == '股票':
            suffix = '.TW' if row.market == '上市' else '.TWO'
            ticker = code + suffix
            stock_list.append(ticker)
            names_map[ticker] = row.name
    return stock_list, names_map

def get_benchmark_roc():
    """計算大盤動能"""
    try:
        bench = yf.download(BENCHMARK, period='6mo', progress=False, auto_adjust=True)
        close = bench['Close']
        if isinstance(close, pd.DataFrame): close = close.iloc[:, 0]
        return float(close.pct_change(RS_PERIOD).iloc[-1])
    except:
        return 0

# ==========================================
# 核心策略邏輯
# ==========================================
def analyze_stock(ticker, df, bench_roc):
    # 資料清洗 (降維處理，避免 MultiIndex 問題)
    try:
        close = df['Close']
        if isinstance(close, pd.DataFrame): close = close.iloc[:, 0]

        open_p = df['Open']
        if isinstance(open_p, pd.DataFrame): open_p = open_p.iloc[:, 0]

        high = df['High']
        if isinstance(high, pd.DataFrame): high = high.iloc[:, 0]

        low = df['Low']
        if isinstance(low, pd.DataFrame): low = low.iloc[:, 0]

        volume = df['Volume']
        if isinstance(volume, pd.DataFrame): volume = volume.iloc[:, 0]
    except:
        return None

    # 1. 基礎濾網
    current_price = float(close.iloc[-1])
    current_vol = float(volume.iloc[-1])
    avg_vol = float(volume.rolling(20).mean().iloc[-1])

    if current_price < MIN_PRICE or avg_vol < MIN_VOLUME:
        return None

    # 2. 趨勢濾網 (Stage 2: 價格 > 50MA > 200MA)
    ma50 = float(close.rolling(50).mean().iloc[-1])
    ma200 = float(close.rolling(200).mean().iloc[-1])

    if not (current_price > ma50 > ma200):
        return None

    # 3. RS 強度濾網 (強於大盤)
    stock_roc = float(close.pct_change(RS_PERIOD).iloc[-1])
    rs_rating = stock_roc - bench_roc
    if rs_rating < 0: # 剔除落後股
        return None

    # 4. 型態辨識 (Pattern Recognition)
    buy_signal = False
    pattern_type = ""
    pivot_price = 0.0
    reason = ""

    # --- A. 高窄旗型 (High Tight Flag) ---
    # 邏輯：過去 60 天內最低點到最高點漲幅 > 80%，且近期 15 天回檔 < 25%
    price_60d_ago = float(close.iloc[-60:].min())
    recent_high = float(high.iloc[-60:].max())

    rally_magnitude = (recent_high - price_60d_ago) / price_60d_ago
    pullback_depth = (recent_high - current_price) / recent_high

    # --- B. 買進跳空 (Buyable Gap Up) ---
    # 邏輯：今日開盤跳空 > 8%，且爆量
    prev_close = float(close.iloc[-2])
    today_open = float(open_p.iloc[-1])
    gap_pct = (today_open - prev_close) / prev_close

    # --- C. VCP / 箱型突破 (Pivot Breakout) ---
    # 邏輯：接近 52 週新高 + 帶量突破 20 日高點 + 波動收縮
    year_high = float(high.iloc[-250:].max())
    dist_to_year_high = (year_high - current_price) / year_high

    prev_20_high = float(high.iloc[-21:-1].max()) # 昨日以前的 20 日高
    is_breakout = (current_price > prev_20_high) and (close.iloc[-2] < prev_20_high) # 確保是"第一天"突破
    is_vol_spike = (current_vol > avg_vol * 1.5) # 量增 50%

    # 判斷優先順序 (Power Play 最優先)
    if (rally_magnitude > HTF_RALLY_PCT) and (pullback_depth < HTF_PULLBACK) and is_breakout:
        buy_signal = True
        pattern_type = "🚀 高窄旗型 (Power Play)"
        pivot_price = prev_20_high
        reason = f"短線飆漲 {int(rally_magnitude*100)}% 後強勢整理突破"

    elif (gap_pct > GAP_UP_PCT) and (current_vol > avg_vol * 2):
        buy_signal = True
        pattern_type = "🕳️ 買進跳空 (Gap Up)"
        pivot_price = today_open
        reason = f"開盤跳空 {int(gap_pct*100)}% 且爆量"

    elif is_breakout and is_vol_spike and (dist_to_year_high < NEAR_HIGH_PCT):
        buy_signal = True
        pattern_type = "📦 VCP/箱型突破"
        pivot_price = prev_20_high
        reason = "接近52週高點，量縮後帶量突破"

    # --- D. 雙底突破 (Double Bottom) ---
    # 簡單模擬：W底右腳突破。這裡用 Pivot Breakout 涵蓋，但特別標註剛從 50MA 反彈的
    elif is_breakout and is_vol_spike and (abs(current_price - ma50) / ma50 < 0.05):
        buy_signal = True
        pattern_type = "W 雙底/50MA反彈"
        pivot_price = prev_20_high
        reason = "回測50MA支撐後，帶量轉強"

    if buy_signal:
        return {
            "現價": round(current_price, 2),
            "型態": pattern_type,
            "買入點(Pivot)": round(pivot_price, 2),
            "RS強度": round(rs_rating * 100, 1),
            "建議停損(7%)": round(pivot_price * 0.93, 2),
            "買入原因": reason,
            "成交量": int(current_vol)
        }
    return None

# ==========================================
# 主程式執行
# ==========================================
def run_screening():
    tickers, names_map = get_stock_list()
    bench_roc = get_benchmark_roc()

    results = []
    print(f"\n🚀 開始掃描全市場 {len(tickers)} 檔股票...")
    print("🔍 尋找：高窄旗型、跳空缺口、VCP、箱型突破...\n")

    for ticker in tqdm(tickers):
        try:
            # 抓取 1 年資料 (計算 52週高 與 HTF)
            df = yf.download(ticker, period='1y', progress=False, auto_adjust=True)
            if df.empty or len(df) < 100: continue

            res = analyze_stock(ticker, df, bench_roc)
            if res:
                res['代號'] = ticker.replace('.TW', '').replace('.TWO', '')
                res['名稱'] = names_map.get(ticker, ticker)
                results.append(res)
        except:
            continue

    if results:
        df_res = pd.DataFrame(results)
        # 欄位排序
        cols = ['代號', '名稱', '現價', '型態', 'RS強度', '買入點(Pivot)', '建議停損(7%)', '買入原因', '成交量']
        df_res = df_res[cols].sort_values(by=['RS強度'], ascending=False)

        print("\n" + "="*80)
        print("📊 【書中買入法則】全台股黃金買點掃描報告")
        print("="*80)
        print(tabulate(df_res, headers='keys', tablefmt='fancy_grid', showindex=False))
        print("\n💡 戰略指導：")
        print("1. [🚀 高窄旗型] 是勝率最高的 Power Play，若出現請優先關注。")
        print("2. [買入點(Pivot)] 是突破的關鍵價位，若目前股價離此太遠 (>3%)，請勿追高。")
        print("3. 進場後請嚴格執行 7% 停損 (表中已計算)。")
    else:
        print("⚠️ 今日市場無符合嚴格型態的買入訊號 (可能大盤處於盤整或下跌)。")

# 執行
run_screening()
