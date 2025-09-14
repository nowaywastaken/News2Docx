# News2Docx

涓€閿姄鍙栬嫳鏂囨柊闂伙紝鑷姩鎺у瓧涓庡弻璇炕璇戯紝瀵煎嚭涓烘帓鐗堣鑼冪殑 DOCX 鏂囨。銆侲nglish summary: Fetch English news, condense to target length, translate to Chinese, and export nicely formatted DOCX via a simple CLI.

- 鎶撳彇鏉ユ簮锛氬彲閰嶇疆鑱氬悎 API 杩斿洖 URL锛涘唴缃父瑙佺珯鐐规鏂囬€夋嫨鍣紝鏀寔鑷畾涔夎鐩栥€?- 鏂囨湰澶勭悊锛氬苟鍙戣皟鐢?LLM锛圤penAI-Compatible锛夊畬鎴愨€滃瓧鏁拌皟鏁?+ 鍙岃缈昏瘧鈥濓紝淇濇寔娈佃惤瀵归綈銆?- 鏂囨。瀵煎嚭锛氭寜鏁欒緟/浣滄枃鏉愭枡甯哥敤瑙勮寖鐢熸垚 DOCX锛堟爣棰樺眳涓€侀琛岀缉杩涖€佸彲閰嶇疆涓嫳瀛椾綋锛夛紝鏀寔鍚堝苟瀵煎嚭鎴栨寜绡囨媶鍒嗐€?
## 鐜瑕佹眰

- Python 3.11+
- Windows / macOS / Linux
- 鍙闂缃戯紙鎶撳彇 API 涓?LLM 鎺ュ彛锛?
## 瀹夎

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

鍙€夛細鏈湴鍐掔儫锛堜笉鑱旂綉锛屼粎楠岃瘉瀵煎嚭閾捐矾锛夛細
```bash
python scripts/smoke.py
```

## 蹇€熷紑濮?
1) 澶嶅埗骞剁紪杈戦厤缃枃浠讹細灏嗘牴鐩綍鐨?`config.yml` 鎵撳紑骞跺～鍐欙細
   - `crawler_api_url`锛氭姄鍙?API 鍦板潃
   - `crawler_api_token`锛氭姄鍙?API Token锛堝繀濉級
   - `openai_api_base`锛歄penAI Compatible Base URL锛堥粯璁?`https://api.siliconflow.cn/v1`锛?   - `openai_api_key`锛歄penAI Compatible API Key锛堝繀濉紝鐢ㄤ簬 AI 澶勭悊锛?
2) 涓€鏉″懡浠ょ鍒扮锛堟姄鍙?+ 澶勭悊 + 鍙€夊鍑猴級
```bash
python -m news2docx.cli.main run --config config.yml
```

3) 鍒嗛樁娈佃繍琛岋紙鍙姄鍙?/ 鍙鐞?/ 鍙鍑猴級
```bash
# 浠呮姄鍙栧苟淇濆瓨 scraped_news_*.json
python -m news2docx.cli.main scrape --config config.yml --max-urls 3

# 浠呭鐞嗭紙杈撳叆涓轰笂涓€姝ヤ繚瀛樼殑 JSON锛夛紝杈撳嚭 processed_news_*.json
python -m news2docx.cli.main process scraped_news_20240101_120000.json --config config.yml

# 浠呭鍑猴紙榛樿閫夊彇鏈€鏂?runs/*/processed.json锛?python -m news2docx.cli.main export --config config.yml --split/--no-split
```

## 鍛戒护琛岀敤娉?
```bash
python -m news2docx.cli.main --help
```

- `scrape`锛氳皟鐢ㄦ姄鍙?API 鑾峰彇 URL锛屽苟鍙戞姄鍙栫綉椤垫鏂囷紝淇濆瓨涓?JSON銆?- `process`锛氬鎶撳彇缁撴灉鎵ц鈥滀袱姝ュ鐞嗏€濓紙瀛楁暟璋冩暣 + 缈昏瘧锛夛紝杈撳嚭澶勭悊鍚庣殑 JSON銆?- `run`锛氱鍒扮鎵ц锛堟姄鍙?+ 澶勭悊锛夛紝骞跺彲閫夊鍑?DOCX銆?- `export`锛氬皢澶勭悊缁撴灉瀵煎嚭涓?DOCX锛堟敮鎸佹寜绡囨媶鍒嗭級銆?- `doctor`锛氫綋妫€鍛戒护锛屾鏌ュ叧閿幆澧冨彉閲忎笌缃戠粶杩為€氭€э紙涓嶈Е鍙戠湡瀹炶璐硅皟鐢級銆?- `stats`/`clean`/`resume`/`combine`锛氳緟鍔╁懡浠ゃ€?
## 閰嶇疆璇存槑锛坈onfig.yml锛?
- 鎶撳彇鐩稿叧
  - `crawler_api_url`锛氭姄鍙?API 鍦板潃
  - `crawler_api_token`锛氭姄鍙?API Token锛堝繀濉級
  - 鍏朵粬锛歚max_urls`銆乣concurrency`銆乣retry_hours`銆乣timeout`銆乣strict_success`銆乣max_api_rounds`銆乣per_url_retries`銆乣pick_mode`銆乣random_seed`銆乣db_path`銆乣noise_patterns`

- 澶勭悊鐩稿叧锛圓I锛?  - `openai_api_base`锛歄penAI Compatible Base URL锛堥粯璁?SiliconFlow锛?  - `openai_api_key`锛氬繀濉紝LLM API Key
  - 鍏朵粬锛歚target_language`銆乣merge_short_paragraph_chars`

- 瀵煎嚭鐩稿叧锛圖OCX锛?  - `run_export`銆乣export_split`銆乣export_order`銆乣export_mono`銆乣export_out_dir`
  - 瀛椾綋涓庣増寮忥細`export_first_line_indent_cm`銆乣export_font_zh_*`銆乣export_font_en_*`銆乣export_title_bold`銆乣export_title_size_multiplier`

## 鐜鍙橀噺閫熸煡锛堝彲涓庨厤缃枃浠舵贩鐢級

- 鎶撳彇锛歚CRAWLER_API_URL`銆乣CRAWLER_API_TOKEN`銆乣CRAWLER_MAX_URLS`銆乣CRAWLER_TIMEOUT`銆乣CRAWLER_RETRY_HOURS`銆乣CRAWLER_STRICT_SUCCESS`銆乣CRAWLER_MAX_API_ROUNDS`銆乣CRAWLER_PER_URL_RETRIES`銆乣CRAWLER_PICK_MODE`銆乣CRAWLER_RANDOM_SEED`
- 澶勭悊锛歚OPENAI_API_KEY`銆乣OPENAI_API_BASE`銆乣OPENAI_MODEL`銆乣CONCURRENCY`銆乣N2D_CACHE_DIR`銆乣OPENAI_MIN_INTERVAL_MS`銆乣MAX_TOKENS_HARD_CAP`
- 瀵煎嚭锛歚TARGET_LANGUAGE`銆乣EXPORT_ORDER`銆乣EXPORT_MONO`
- 杩愯鐩綍锛歚RUNS_DIR`
- 閫夋嫨鍣ㄨ鐩栵細`SCRAPER_SELECTORS_FILE`

Windows PowerShell 璁剧疆鐜鍙橀噺锛?```powershell
$env:CRAWLER_API_TOKEN = "your_token"
$env:OPENAI_API_KEY = "your_api_key"
$env:OPENAI_API_BASE = "https://api.siliconflow.cn/v1"  # 榛樿鍙笉璁?```

Bash 璁剧疆鐜鍙橀噺锛?```bash
export CRAWLER_API_TOKEN="your_token"
export OPENAI_API_KEY="your_api_key"
export OPENAI_API_BASE="https://api.siliconflow.cn/v1"  # 榛樿鍙笉璁?```

## FAQ

- 缂哄皯 Token/API Key锛?  - 鎶撳彇闃舵闇€瑕?`CRAWLER_API_TOKEN`锛屽鐞嗛樁娈甸渶瑕?`OPENAI_API_KEY`銆?- 杩愯 `process`/`run` 鎶ラ敊锛氱己灏?`OPENAI_API_KEY`锛?  - 璇峰湪 `config.yml` 鎴栫幆澧冨彉閲忎腑鎻愪緵 API Key銆俙doctor` 瀛愬懡浠ゅ彲甯姪妫€鏌ラ厤缃笌杩為€氭€с€?
## 寮€鍙戜笌娴嬭瘯

```bash
pytest -q
python scripts/smoke.py
```

## 璁稿彲

鏈」鐩殏鏈０鏄庡紑婧愯鍙瘉銆傝嫢闇€鍦ㄧ敓浜ф垨鍟嗙敤鍦烘櫙涓娇鐢紝璇峰厛涓庝綔鑰呯‘璁ゆ巿鏉冩潯娆俱€?
---

## 鎶撳彇妯″紡锛坮emote/local锛?
鏈湴绋嬪簭鐜版敮鎸佷袱绉嶆姄鍙栨ā寮忥細

- remote锛堥粯璁わ紝鎺ㄨ崘鍥藉唴锛夛細浣跨敤浣犻儴缃插湪鏈嶅姟鍣?浜戝嚱鏁颁笂鐨勨€滅埇铏腑杞€濈鐐癸紝杩斿洖鏂伴椈 URL 鍒楄〃锛屽啀鐢辨湰鍦版姄姝ｆ枃銆?- local锛堥渶鐩磋繛 GDELT锛夛細鏈湴鐩存帴璋冪敤 GDELT Doc 2.0 鎺ュ彛锛屾牴鎹珯鐐瑰垪琛ㄦ媺鍙栬繎 7 澶╃殑鑻辨枃鏂伴椈 URL銆?
鍦?`config.yml` 涓€夋嫨锛?
```yaml
# 杩滅▼妯″紡锛堥粯璁わ級
crawler_mode: remote
crawler_api_url: https://<your-crawler-endpoint>
crawler_api_token: <your-token>

# 鏈湴妯″紡锛堢洿杩?GDELT锛?# crawler_mode: local
# crawler_sites_file: server/news_website.txt   # 姣忚涓€涓煙鍚嶏紝鏀寔 # 娉ㄩ噴
# gdelt_timespan: 7d          # 鍙€夛細24h/7d/30d
# gdelt_max_per_call: 50      # 鍙€夛細姣忔壒鏈€澶ц繑鍥炴暟
# gdelt_sort: datedesc        # 鍙€夛細datedesc|dateasc
```

瀵瑰簲鐜鍙橀噺锛堝彲瑕嗙洊閰嶇疆鏂囦欢锛夛細

- `CRAWLER_MODE`銆乣CRAWLER_API_URL`銆乣CRAWLER_API_TOKEN`
- `CRAWLER_SITES_FILE`銆乣GDELT_TIMESPAN`銆乣GDELT_MAX_PER_CALL`銆乣GDELT_SORT`

鎻愮ず锛歚doctor` 瀛愬懡浠ゅ湪 remote 妯″紡浼氭帰娴嬩腑杞鐐硅繛閫氭€э紱local 妯″紡浼氭彁绀鸿繍琛屾湡鐩磋繛 GDELT銆?
## 鏈嶅姟鍣ㄧ鐖櫕锛堝彲閫夛級

- 鐩綍 `server/` 鎻愪緵浜?GDELT 鎶撳彇绔偣绀轰緥锛堝閮ㄧ讲鍒伴樋閲屼簯鍑芥暟璁＄畻锛夈€?- 绔欑偣娓呭崟锛歚server/news_website.txt`锛堟瘡琛屼竴涓煙鍚嶏紝`#` 涓烘敞閲婏級銆備害鍙€氳繃鐜鍙橀噺 `SITES_FILE` 鎸囧畾璺緞銆?- 杩愯鏃跺弬鏁帮紙浜戠锛夛細`SITES`锛堥€楀彿鍒嗛殧锛岃鐩栨竻鍗曪級銆乣TIMESPAN`銆乣MAX_PER_CALL`銆乣SORT`銆?- 绔偣杩斿洖褰㈠锛歚{"count": N, "urls": ["https://..."]}`銆?
