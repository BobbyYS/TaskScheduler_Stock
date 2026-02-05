# 1. 安裝必要套件
# !pip install yfinance twstock pandas tqdm tabulate

import yfinance as yf
import pandas as pd
import twstock
from tqdm import tqdm
from tabulate import tabulate
import numpy as np

# ==========================================
# ⚙️ DRIVE 終極選股參數
# ==========================================
MIN_PRICE = 20          # 股價 > 20
MIN_VOLUME = 1000000    # 均量 > 1000張 (確保流動性)
RS_PERIOD = 60          # RS 週期 (約一季)
BENCHMARK = '0050.TW'   # 大盤基準

# MVP (Ants) 參數 - 大戶吸籌特徵
MVP_WINDOW = 15         # 觀察過去 15 天
MVP_UP_DAYS = 9         # 至少 9 天收紅 (書中說10天，稍微放寬一點以防漏網)
MVP_VOL_INC = 1.2       # 期間均量比過去放大 20%

# ==========================================
# 輔助函數
# ==========================================
def get_stock_list_with_industry():
    """獲取全台股代號與產業別"""
    print("📋 正在抓取全台股清單與產業分類...")
    codes = twstock.codes
    stock_info = []

    for code in codes:
        row = codes[code]
        if row.type == '股票':
            suffix = '.TW' if row.market == '上市' else '.TWO'
            stock_info.append({
                "ticker": code + suffix,
                "name": row.name,
                "industry": row.group
            })
    return stock_info

def get_benchmark_roc():
    """獲取大盤數據"""
    try:
        bench = yf.download(BENCHMARK, period='6mo', progress=False, auto_adjust=True)
        close = bench['Close']
        if isinstance(close, pd.DataFrame): close = close.iloc[:, 0]
        return float(close.pct_change(RS_PERIOD).iloc[-1])
    except:
        return 0

# ==========================================
# 核心 DRIVE 分析邏輯
# ==========================================
def analyze_drive_full(info, df, bench_roc):
    ticker = info['ticker']
    industry = info['industry']

    try:
        # 資料清洗
        close = df['Close']
        if isinstance(close, pd.DataFrame): close = close.iloc[:, 0]
        volume = df['Volume']
        if isinstance(volume, pd.DataFrame): volume = volume.iloc[:, 0]
        high = df['High']
        if isinstance(high, pd.DataFrame): high = high.iloc[:, 0]

        # 1. 基礎濾網
        current_price = float(close.iloc[-1])
        avg_vol = float(volume.rolling(20).mean().iloc[-1])

        if current_price < MIN_PRICE or avg_vol < MIN_VOLUME: return None

        # 2. D = Direction (趨勢 Stage 2)
        ma50 = float(close.rolling(50).mean().iloc[-1])
        ma200 = float(close.rolling(200).mean().iloc[-1])
        year_high = float(high.iloc[-250:].max())
        year_low = float(high.iloc[-250:].min())

        # 條件：多頭排列 + 接近新高 + 脫離底部
        cond_stage2 = (current_price > ma50 > ma200)
        cond_near_high = (year_high - current_price) / year_high < 0.25
        cond_off_low = (current_price - year_low) / year_low > 0.30

        if not (cond_stage2 and cond_near_high and cond_off_low): return None

        # 3. R = Relative Strength (RS 強度)
        stock_roc = float(close.pct_change(RS_PERIOD).iloc[-1])
        rs_rating = (stock_roc - bench_roc) * 100

        if rs_rating < 5: return None # 至少要比大盤強

        # 4. V = Volume & MVP (大戶吸籌)
        # 檢查過去 15 天的 K 線與成交量
        recent_close = close.iloc[-(MVP_WINDOW+1):-1] # 不含今天，看前15天
        recent_vol = volume.iloc[-(MVP_WINDOW+1):-1]
        prev_vol = volume.iloc[-(MVP_WINDOW*2+1):-(MVP_WINDOW+1)] # 再前15天

        # 計算上漲天數
        up_days = (recent_close.diff() > 0).sum()
        # 計算量能放大
        vol_ratio = recent_vol.mean() / prev_vol.mean() if prev_vol.mean() > 0 else 1

        is_mvp = (up_days >= MVP_UP_DAYS) and (vol_ratio >= MVP_VOL_INC)

        # 判斷今日爆量
        current_vol = float(volume.iloc[-1])
        is_vol_spike = current_vol > (avg_vol * 1.3)

        # 5. 買點觸發 (Pivot Breakout)
        prev_20_high = float(close.iloc[-21:-1].max())
        is_breakout = (current_price > prev_20_high) and (close.iloc[-2] < prev_20_high)

        # 6. E = Earnings (以技術面反應做代理)
        # 如果是 Gap Up (跳空 > 8%)
        prev_close = float(close.iloc[-2])
        open_price = float(df['Open'].iloc[-1])
        is_gap_up = (open_price - prev_close) / prev_close > 0.08

        # 評分與標記
        score = 0
        reasons = []

        if is_breakout and is_vol_spike:
            score += 50
            reasons.append("帶量突破樞紐")

        if is_mvp:
            score += 30
            reasons.append("🔥MVP大戶吸籌")

        if is_gap_up:
            score += 40
            reasons.append("🕳️跳空缺口(GapUp)")

        if rs_rating > 30:
            score += 10
            reasons.append(f"RS超強({int(rs_rating)})")

        # 至少要符合突破 或 MVP特徵 或是 跳空
        if score >= 30:
            return {
                "代號": ticker.replace('.TW', '').replace('.TWO', ''),
                "名稱": info['name'],
                "產業": industry,
                "現價": round(current_price, 2),
                "RS強度": round(rs_rating, 1),
                "型態": "DRIVE 訊號",
                "評分": score,
                "原因": " + ".join(reasons),
                "成交量": int(volume.iloc[-1])
            }

    except:
        return None
    return None

# ==========================================
# 主程式執行
# ==========================================
def run_drive_full_scan():
    stock_infos = get_stock_list_with_industry()
    bench_roc = get_benchmark_roc()

    results = []
    print(f"\n🚀 開始執行 DRIVE 終極掃描 ({len(stock_infos)} 檔)...")
    print("🔍 邏輯：Stage 2 + MVP動能 + 板塊共振 + 買點偵測...\n")

    for info in tqdm(stock_infos):
        try:
            # 下載 1 年資料
            df = yf.download(info['ticker'], period='1y', progress=False, auto_adjust=True)
            if df.empty or len(df) < 200: continue

            res = analyze_drive_full(info, df, bench_roc)
            if res:
                results.append(res)
        except:
            continue

    if results:
        df_res = pd.DataFrame(results)

        # --- I 部分：計算最強板塊 (Top Down) ---
        # 統計各產業入選的股票數量
        industry_counts = df_res['產業'].value_counts()
        top_industries = industry_counts.head(3).index.tolist()

        print(f"\n🔥 資金流向最強的三大板塊：{', '.join(top_industries)}")
        print("-" * 60)

        # 標記領頭羊 (屬於強勢板塊的股票加分)
        df_res['領頭羊'] = df_res.apply(lambda x: '👑' if x['產業'] in top_industries else '', axis=1)

        # 排序：評分 > RS > 產業
        df_res = df_res.sort_values(by=['評分', 'RS強度'], ascending=False)

        cols = ['領頭羊', '代號', '名稱', '產業', '現價', 'RS強度', '評分', '原因']

        print("\n📊 【DRIVE 終極模型】全台股選股報告")
        print(tabulate(df_res[cols], headers='keys', tablefmt='fancy_grid', showindex=False))

        print("\n💡 訊號解讀：")
        print("1. [🔥MVP大戶吸籌]: 過去15天出現密集買盤(Ants)，是強烈的波段訊號。")
        print("2. [👑 領頭羊]: 該股票屬於目前最強勢的板塊，勝率通常最高。")
        print("3. [帶量突破樞紐]: 標準買點，請確認風險報酬比後進場。")
        print("4. [🕳️跳空缺口]: 可能是財報利多，若不回補缺口可視為強勢訊號。")

    else:
        print("⚠️ 今日市場無符合 DRIVE 條件的股票 (可能大盤偏弱)。")

# 執行
run_drive_full_scan()
