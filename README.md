# 台股每日變化與世界重大事件追蹤器

這是一套長期研究用的自動追蹤系統。每天自動蒐集國際新聞、國際經濟變項與台股收盤資料，請 AI 整理成「事件 → 經濟變項 → 產業 → 台股加權指數」的傳導路徑。AI 在開盤前寫下對當天大盤方向的判斷，收盤後再和實際結果比較，全部資料都保留下來，不覆蓋歷史紀錄。

> 這是研究與資料分析工具，不是投資建議。AI 的判斷是推論，相關不等於因果。

## 系統架構

```
GitHub Actions（排程，雲端執行）
  ├─ 07:13 早班：國際新聞 → 國際變項 → AI 事件分析 → 開盤前判斷 → 評估前一日判斷
  ├─ 18:17 晚班：台股收盤 → 類股 → 法人 → 上櫃 → 重大訊息 → 評估 → 日報
  ├─ 週日：週報、資料備份（CSV 存進 backups/）
  └─ 每月 1 日：月報
          │ 寫入（只有排程可以寫）
          ▼
Supabase（PostgreSQL 資料庫，東京機房）
          │ 唯讀（網站只能讀，不能改）
          ▼
Streamlit 網站（六個頁面）
```

時間都是台北時間。研究紀錄（事件、事前判斷、報告）有資料庫觸發器保護，寫入後不能修改或刪除。

## 資料來源

| 資料 | 來源 | 是否官方 | 需要金鑰 |
|---|---|---|---|
| 加權指數、成交量值 | 臺灣證券交易所 FMTQIK | 官方 | 不需要 |
| 類股指數、漲跌家數、個股行情 | 證交所 MI_INDEX | 官方 | 不需要 |
| 三大法人買賣超 | 證交所 BFI82U | 官方 | 不需要 |
| 上市公司重大訊息 | 證交所 OpenAPI t187ap04_L | 官方 | 不需要 |
| 休市日 | 證交所 holidaySchedule | 官方 | 不需要 |
| 櫃買指數 | 櫃買中心 OpenAPI | 官方 | 不需要 |
| 美國利率、殖利率、CPI、就業、匯率、油價、美股指數 | 美國聯準會 FRED | 官方 | 需要（免費） |
| 費半、台積電 ADR、日經、VIX、美元指數、黃金 | Yahoo Finance（yfinance） | **非官方**，網站會標示 | 不需要 |
| 國際新聞 | GDELT DOC 2.0 | 新聞索引（只有標題與網址） | 不需要 |
| 聯準會新聞稿 | Fed RSS | 官方 | 不需要 |
| AI 分析 | Google Gemini（免費額度） | — | 需要（免費） |

每一筆資料都記錄來源、來源網址與取得時間。

## 檔案結構

```
app/                 Streamlit 網站
  streamlit_app.py   入口與導覽
  pages/             六個頁面：dashboard、events、market、variables、relations、history
  data.py            資料讀取（唯讀）
  ui.py              格式、顏色、圖表元件
tracker/             資料蒐集與分析
  collectors/        證交所、櫃買、FRED／Yahoo、GDELT／Fed
  analysis/          AI 事件分析、事前判斷、評估、漲跌幅分級
  reports.py         日報、週報、月報
  db.py              資料庫寫入與執行紀錄
jobs/                排程執行的程式（setup_db、backfill、morning、evening、periodic、check_sources）
db/schema.sql        資料表、權限與保護規則
tests/               自動測試（使用程式產生的「測試資料」，只寫進暫時測試資料庫）
.github/workflows/   排程設定
backups/             每週自動備份的 CSV
```

## 需要的金鑰（放在 GitHub Secrets，不寫進程式碼）

在 GitHub repo 的 **Settings → Secrets and variables → Actions → New repository secret** 新增：

| 名稱 | 內容 |
|---|---|
| `DATABASE_URL` | Supabase 的 Session pooler 連線網址（含資料庫密碼） |
| `SUPABASE_URL` | Supabase 的 Project URL |
| `SUPABASE_ANON_KEY` | Supabase 的 publishable（或 anon）金鑰，**不是** secret／service_role |
| `FRED_API_KEY` | FRED 金鑰 |
| `GEMINI_API_KEY` | Google AI Studio 金鑰 |

網站部署在 Streamlit Community Cloud 時，只需要在網站的 Secrets 填 `SUPABASE_URL` 與 `SUPABASE_ANON_KEY`。這把金鑰只能讀取，資料庫的列層級安全規則（RLS）禁止它寫入。

## 第一次啟動的順序

1. **Actions → 檢查資料來源 → Run workflow**：逐一測試每個資料來源、金鑰與資料庫連線，結果在執行頁面的摘要。
2. **Actions → 初始化資料庫 → Run workflow**：建立資料表，回補近 3 年加權指數與國際變項。
3. **Actions → 早班／晚班 → Run workflow**：手動跑一次確認流程，之後每天自動執行。
4. 到 Streamlit Community Cloud 部署網站，主程式選 `app/streamlit_app.py`。

## 在自己電腦上執行（選用）

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-jobs.txt
cp .env.example .env        # 填入自己的值
streamlit run app/streamlit_app.py
```

自動測試（會清空指定的資料庫，只能用測試資料庫）：

```bash
TEST_DATABASE_URL=postgresql://... pytest -q
```

## 研究方法的重點

- **事前判斷**：AI 必須在開盤（09:00）前寫入判斷，晚於開盤的判斷會標示「非事前」，不計入命中率。
- **對照規則**：「費城半導體指數前一晚漲就猜漲、跌就猜跌」。AI 的表現要和這條簡單規則比較才有意義。
- **漲跌幅分級 v1**：絕對幅度（0.5／1／2／3%）與相對近 20 日波動（z 分數）兩種，定義與依據見專案文件「決策紀錄」。
- **事實與推論分開**：AI 寫的每一條「事實」都要對應到新聞編號，對不到的會自動降級成「未確認」。
- **版本**：提示詞版本 `p1`、評估方法版本 `v1`，之後修改會換版本號，舊紀錄保留。

## 目前狀態

| 功能 | 狀態 |
|---|---|
| 資料表、權限、保護規則 | ✅ 完成，本機測試通過 |
| 自動蒐集、AI 分析、事前判斷、評估、報告 | ✅ 程式完成，用模擬資料測試通過；**尚未用真實資料來源實際執行** |
| 網站六個頁面 | ✅ 完成，用測試資料逐頁測試通過；**尚未部署** |
| 證交所 MI_INDEX／BFI82U、櫃買 OpenAPI、重大訊息、休市日的實際欄位格式 | ⏳ 尚未驗證，第一次執行「檢查資料來源」時確認 |
| 個股層級的 AI 影響分析、個股相關事件 | ⏳ 尚未完成（第一版研究範圍是大盤） |
| 改用 Claude 作為 AI | ⏳ 程式已寫，尚未測試，需付費 |
| 類股、上櫃、法人的歷史資料 | ⏳ 只從系統上線那天開始累積（官方提供的歷史回補方式另行評估） |
