//+------------------------------------------------------------------+
//|                                            DinaGoldTrader.mq5    |
//|  帝娜黄金交易系统 —— 行为分析(技术面)执行层                      |
//|   /|                                                                  |
//|  进场（势位态三要素齐全）：                                       |
//|    1H 五要件 = 回档(顾比) + 收口/乖离(布林) + 过度(随机)         |
//|                + 适离(轴心点混合菲波纳奇) + 渐短(蜡烛敛散)       |
//|    4H 三形态 = 涨跌吞没 / 启明黄昏 / 刺透盖顶（须在布林轨道上）  |
//|  出场：初始止损 / 大幅运动收盘破外轨 / 小幅运动收盘反穿中轨      |
//|        / 中轨跟进止损 / 反向信号平仓                              |
//|  基本面：读取 MQL5/Files/gold_signal.ini（Python 侧产出）        |
//|          仅用于方向偏置、否决反向信号与仓位缩放                  |
//+------------------------------------------------------------------+
#property copyright "Dina Gold Trading System"
#property version   "1.00"
#property description "帝娜黄金交易系统 - 1H五要件 / 4H三形态 / 布林带出场"
#property strict

#include <DinaGold/DinaIndicators.mqh>
#include <DinaGold/DinaCandles.mqh>
#include <DinaGold/DinaLevels.mqh>
#include <DinaGold/DinaSignal.mqh>
#include <DinaGold/DinaTrade.mqh>
#include <DinaGold/DinaFundamental.mqh>

//+------------------------------------------------------------------+
//| 彩色 GUI 面板（OBJ_LABEL + OBJ_RECTANGLE_LABEL）                 |
//+------------------------------------------------------------------+
#define PANEL_MAX_LBL    40
#define C_PANEL_BG       C'18,22,30'
#define C_PANEL_BORDER   C'70,95,130'
#define C_TITLE          C'255,200,90'
#define C_SECTION        C'130,185,255'
#define C_FACTORSEC      C'180,150,255'
#define C_TEXT           C'210,215,225'
#define C_RED            C'235,85,85'     // 多 / 涨（中国习惯：涨红）
#define C_GREEN          C'70,205,130'   // 空 / 跌（中国习惯：跌绿）
#define C_GRAY           C'150,155,168'
#define C_ORANGE         C'240,165,65'
#define C_CYAN           C'85,200,225'
#define C_WARN           C'245,120,120'
string g_lbl[PANEL_MAX_LBL];
int    g_curLbl = 0;

//+------------------------------------------------------------------+
//| 手数模式（仓位缩放方式）                                          |
//+------------------------------------------------------------------+
enum ENUM_LOT_MODE { LOT_RISK = 0, LOT_FIXED = 1, LOT_ATR_RISK = 2 };

//+------------------------------------------------------------------+
//| 输入参数                                                          |
//+------------------------------------------------------------------+
input group "===== 品种与执行 ====="
input string  InpSymbol        = "XAUUSD";      // 交易品种
input ulong   InpMagic         = 20260907;      // 魔术号
input int     InpDeviation     = 30;            // 允许滑点(point)
input bool    InpAllowTrade    = true;          // 允许实盘下单（false=只提示）

input group "===== 布林带 Bands(13,0,1.618) ====="
input int     InpBBPeriod      = 13;            // 周期
input double  InpBBDeviation   = 1.618;         // 标准差倍数
input int     InpSqueezeLook   = 120;           // 收口回溯根数
input double  InpSqueezePct    = 0.25;          // 收口分位阈值

input group "===== 顾比复合均线 ====="
input double  InpPullbackRatio = 0.60;          // 回档贴近阈值(ATR倍数)

input group "===== 随机震荡指标 ====="
input int     InpStochK        = 5;
input int     InpStochD        = 3;
input int     InpStochSlow     = 3;
input double  InpOverBought    = 80;
input double  InpOverSold      = 20;

input group "===== 轴心点混合菲波纳奇 ====="
input int     InpSwingLeft     = 5;             // 分形左腿
input int     InpSwingRight    = 5;             // 分形右腿
input int     InpSwingWindow   = 200;           // 摆动点搜索窗口
input bool    InpUsePivot      = true;          // 启用轴心点
input double  InpProxATR       = 0.35;          // 适离阈值(ATR倍数)

input group "===== 蜡烛敛散 ====="
input int     InpBodyLookback  = 20;
input double  InpBodyRatio     = 0.60;          // 小实体比例
input double  InpShadowMult    = 1.50;          // 长影线倍数
input double  InpDojiRatio     = 0.10;          // 十字判定

input group "===== 进场 / 出场 ====="
input int     InpMinScore      = 3;             // 五要件至少满足几项（3=回档+另两项）
input bool    InpUseH4         = true;          // 启用4小时图三形态
input double  InpH4BandATR     = 0.50;          // "在布林轨道上"的容差(ATR)
input double  InpEngulfRatio   = 1.00;          // 吞没实体比例
input double  InpStopBufferATR = 0.30;          // 关键位外缓冲
// 最小止损距离。0.80 时约 84% 的单子会在 24 根内被打掉，而持有 24 根的
// 最大有利偏移中位数是 2.65 ATR —— 盈亏比倒挂。3.00 为实测最优。
input double  InpMinStopATR    = 3.00;
input double  InpFallbackATR   = 1.20;          // 无关键位时止损距离
input double  InpBigMoveATR    = 2.00;          // "大幅度运动"阈值
input bool    InpTrailing      = true;          // 跟进止损
input int     InpTrailMethod   = 1;             // 0=布林中轨 1=ATR回撤
input double  InpTrailActivate = 2.50;          // 启动跟踪的浮盈(ATR)
input double  InpTrailATRMult  = 2.00;          // ATR回撤法的回撤倍数
input int     InpMaxHoldBars   = 24;            // 最大持有K线数(0=不限)
input bool    InpAllowShort    = true;          // 做空总安全锁(默认开)；具体多空由 regime 矩阵决定
input bool    InpReverseClose  = true;          // 反向信号平仓
// 小幅运动收盘反穿中轨是否平仓。默认 false，与 Python 回测 close_beyond_middle
// 一致——避免中轨把持仓提前扫掉，导致盈亏比倒挂（实盘贴着中轨被洗的典型根因）。
input bool    InpCloseBeyondMiddle = false;     // 小运动反穿中轨即平仓
input double  InpSkewFactor    = 0.40;           // 非优势方向仓位系数(优势方向=1.0)
input bool    InpNeutralFlatAside = true;          // 中性+日线无趋势时站旁边(B3 采纳)
// 4H 三形态共振（原著"帝娜系统"核心）：
//   true  = 1H 五要件 且 4H 三形态 同方向 才进场（AND，faithful 原著）
//   false = 1H 五要件 或 4H 三形态 任一触发即进场（OR，旧逻辑）
// 【实证 2026-09-19】回测(2023-2026 黄金牛市, long-only)显示 4H 共振削弱正期望
//   (纯1H PF=1.22 → 严格AND PF=0.19 / 近窗W=24 PF=0.87)，故默认关闭保留纯1H最优系统。
input bool    InpH4Resonance    = false;         // 4H 与 1H 共振(AND)；默认关(实证削弱做多边缘)

input group "===== 仓位与风控 ====="
input double  InpRiskPct       = 1.0;           // 单笔风险占净值 %
input bool    InpUseKelly      = true;          // 用 Python 侧凯利 f*
input double  InpMaxLots       = 5.0;
input ENUM_LOT_MODE InpLotMode = LOT_RISK;     // 手数模式：0=风险%模式 1=固定手数 2=ATR等价固定风险%
input double  InpFixedLots     = 0.1;          // 固定手数(仅 InpLotMode=1 生效)
input int     InpMaxSpreadPts  = 60;            // 点差过滤(point)

input group "===== 基本面文件 ====="
input string  InpSignalFile    = "gold_signal.ini";
input int     InpReloadMinutes = 60;            // 信号文件刷新间隔
input int     InpMaxSignalAgeHours = 24;        // 信号文件陈旧阈值(小时)；超时则停用基本面否决

//+------------------------------------------------------------------+
DinaHandles  g_h1, g_h4;
DinaBuf      g_b1, g_b4;
DinaFund     g_fund;
CTrade       g_trade;

int          g_shortArr[DINA_GUPPY_N] = {3, 5, 8, 10, 12, 15};
int          g_longArr[DINA_GUPPY_N]  = {30, 35, 40, 45, 50, 60};
double       g_fibRet[7] = {0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0};
double       g_fibExt[3] = {1.272, 1.618, 2.618};

datetime     g_lastBar1H  = 0;
datetime     g_lastFundLoad = 0;
string       g_sym = "";
DinaSetup    g_snapSt;       // 最近一次技术面快照（供 OnTimer 常驻刷新面板）
int          g_snapH4 = 0;
int          g_snapDir = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   g_sym = (InpSymbol == "") ? _Symbol : InpSymbol;
   if(!SymbolInfoInteger(g_sym, SYMBOL_SELECT))
   {
      Print("[Dina] 品种不可用: ", g_sym);
      return INIT_FAILED;
   }
   SymbolSelect(g_sym, true);

   DinaInitHandles(g_h1, g_sym, PERIOD_H1, InpBBPeriod, InpBBDeviation,
                   InpStochK, InpStochD, InpStochSlow, 14, g_shortArr, g_longArr);
   DinaInitHandles(g_h4, g_sym, PERIOD_H4, InpBBPeriod, InpBBDeviation,
                   InpStochK, InpStochD, InpStochSlow, 14, g_shortArr, g_longArr);
   if(g_h1.bb == INVALID_HANDLE || g_h4.bb == INVALID_HANDLE)
   {
      Print("[Dina] 指标句柄创建失败");
      return INIT_FAILED;
   }
   g_trade.SetExpertMagicNumber(InpMagic);
   DinaLoadFundamental(InpSignalFile, g_fund);
   g_lastFundLoad = TimeCurrent();
   EventSetTimer(2);          // 每 2 秒刷新一次基本面面板（常驻显示，不依赖 tick）
   DinaCreatePanel();         // 创建彩色 GUI 面板对象
   Comment("");               // 清掉旧的纯文本面板
   Print("[Dina] 初始化完成 品种=", g_sym, " 允许下单=", InpAllowTrade);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   DinaDestroyPanel();        // 清理彩色 GUI 面板对象
   EventKillTimer();
   DinaRelease(g_h1);
   DinaRelease(g_h4);
}

//+------------------------------------------------------------------+
//| 定时重载基本面文件（OnTick / OnTimer 共用）                       |
//+------------------------------------------------------------------+
void ReloadFundIfNeeded()
{
   if(TimeCurrent() - g_lastFundLoad > InpReloadMinutes * 60)
   {
      DinaLoadFundamental(InpSignalFile, g_fund, InpMaxSignalAgeHours);
      g_lastFundLoad = TimeCurrent();
   }
}

//+------------------------------------------------------------------+
//| 定时刷新面板（不依赖行情 tick，确保基本面信息常驻显示）          |
//+------------------------------------------------------------------+
void OnTimer()
{
   ReloadFundIfNeeded();
   if(RefreshBuffers()) DrawPanel(g_snapSt, g_snapH4, g_snapDir);
}

//+------------------------------------------------------------------+
bool RefreshBuffers()
{
   if(!DinaRefresh(g_h1, g_b1, DINA_MAXBARS)) return false;
   if(!DinaRefresh(g_h4, g_b4, 300))          return false;
   return true;
}

//+------------------------------------------------------------------+
//| 由 H1 收盘K线与 D1 上一日轴心点构建关键位                        |
//+------------------------------------------------------------------+
void BuildLevelSet(DinaLevelSet &ls)
{
   MqlRates r1[], rd[];
   ArraySetAsSeries(r1, true);
   ArraySetAsSeries(rd, true);
   if(CopyRates(g_sym, PERIOD_H1, 0, InpSwingWindow + 40, r1) <= 0) return;
   double P = 0, R1 = 0, S1 = 0, R2 = 0, S2 = 0;
   if(InpUsePivot && CopyRates(g_sym, PERIOD_D1, 0, 5, rd) > 1)
      DinaPivot(rd[1].high, rd[1].low, rd[1].close, P, R1, S1, R2, S2);
   DinaBuildLevels(ls, r1, InpSwingLeft, InpSwingRight, InpSwingWindow,
                   g_fibRet, g_fibExt, P, R1, S1, R2, S2);
}

//+------------------------------------------------------------------+
//| 4小时图三形态（须出现在布林带轨道上）                             |
//+------------------------------------------------------------------+
int H4Setup()
{
   MqlRates r4[];
   ArraySetAsSeries(r4, true);
   if(CopyRates(g_sym, PERIOD_H4, 0, 200, r4) <= 0) return 0;
   int i = 1;                                    // 上一根已收盘 H4
   int pat = DinaH4Pattern(r4, i, InpEngulfRatio);
   if(pat == 0) return 0;
   double tol = InpH4BandATR * g_b4.atr[i];
   if(pat > 0  && MathAbs(r4[i].close - g_b4.bbLo[i]) <= tol) return 1;
   if(pat < 0  && MathAbs(r4[i].close - g_b4.bbUp[i]) <= tol) return -1;
   return 0;
}

//+------------------------------------------------------------------+
//| 基本面否决                                                        |
//+------------------------------------------------------------------+
bool Vetoed(int dir)
{
   if(!g_fund.loaded || !g_fund.veto) return false;
   if(g_fund.bias > 0 && dir < 0) { Print("[Dina] 基本面否决：驱动偏多，禁止做空"); return true; }
   if(g_fund.bias < 0 && dir > 0) { Print("[Dina] 基本面否决：驱动偏空，禁止做多"); return true; }
   return false;
}

//+------------------------------------------------------------------+
void OnTick()
{
   datetime cur1h = iTime(g_sym, PERIOD_H1, 0);
   if(cur1h == 0) return;

   // 定时重载基本面文件（OnTimer 也调用，避免无 tick 时面板不更新）
   ReloadFundIfNeeded();

   // 持仓管理（每 tick）
   ulong ticket; long ptype;
   bool hasPos = DinaFindPosition(g_sym, InpMagic, ticket, ptype);
   if(hasPos) ManagePosition(ticket, ptype);

   // 新K线才做进出场决策
   if(cur1h == g_lastBar1H) return;
   g_lastBar1H = cur1h;
   if(!RefreshBuffers()) return;

   MqlRates r1[];
   ArraySetAsSeries(r1, true);
   if(CopyRates(g_sym, PERIOD_H1, 0, DINA_MAXBARS, r1) <= 0) return;

   DinaLevelSet ls;
   BuildLevelSet(ls);

   DinaSetup st;
   DinaEvalH1(r1, g_b1, ls, 1, InpPullbackRatio, InpSqueezeLook, InpSqueezePct,
              InpStochK, InpStochD, InpOverBought, InpOverSold, InpProxATR,
              InpBodyLookback, InpBodyRatio, InpShadowMult, InpDojiRatio,
              InpStopBufferATR, InpMinStopATR, InpFallbackATR, InpMinScore, st);

   int h4 = InpUseH4 ? H4Setup() : 0;

   // ---- 持仓：先判出场 ----
   if(hasPos)
   {
      int dir = (ptype == POSITION_TYPE_BUY) ? 1 : -1;
      if(DinaCheckExit(r1, g_b1, 1, (int)ptype,
                       PositionGetDouble(POSITION_PRICE_OPEN),
                       CurrentMFE(dir), InpBigMoveATR, 0.0,
                       InpCloseBeyondMiddle) == 1)
      {
         DinaCloseTicket(g_trade, ticket, InpMagic, InpDeviation, "布林带出场");
         return;
      }
      if(InpReverseClose)
      {
         int opp = (dir > 0) ? -1 : 1;
         if((st.dir == opp && st.score >= InpMinScore) || h4 == opp)
         {
            DinaCloseTicket(g_trade, ticket, InpMagic, InpDeviation, "反向进场信号");
            return;
         }
      }
      return;   // 已有持仓不再开新仓
   }

   // ---- 开仓 ----
   int dir = 0; string why = "";
   if(InpH4Resonance)
   {
      // 原著：1H 五要件 且 4H 三形态 同方向 共振（AND）
      if(st.dir != 0 && h4 != 0 && h4 == st.dir)
         { dir = st.dir; why = StringFormat("1H+4H共振(%d/5)", st.score); }
   }
   else
   {
      // 纯 1H 五要件：与 Python 回测 require_h4_resonance=false 完全对齐（4H 不参与开仓）。
      // 注意：早期 EA 此处是"1H 或 4H 任一触发"的 OR 逻辑，正是实盘过度交易(19笔)的偏差源，已移除。
      if(st.dir != 0) { dir = st.dir; why = StringFormat("1H五要件(%d/5)", st.score); }
   }
   if(dir == 0) { DrawPanel(st, h4, dir); return; }

   // ---- regime 矩阵：基本面偏置 × 日线趋势 -> 方向门控 + 仓位偏斜 ----
   bool allowLong, allowShort; double longSkew, shortSkew;
   DinaRegimeGate(g_fund, InpSkewFactor, InpNeutralFlatAside, allowLong, allowShort, longSkew, shortSkew);
   if(dir > 0 && !allowLong)  { Print("[Dina] regime 否决做多(方向门控)"); DrawPanel(st, h4, dir); return; }
   if(dir < 0 && !allowShort) { Print("[Dina] regime 否决做空(方向门控)"); DrawPanel(st, h4, dir); return; }
   if(dir < 0 && !InpAllowShort) { DrawPanel(st, h4, dir); return; }   // 做空总安全锁

   if(!CheckSpread()) { DrawPanel(st, h4, dir); return; }

   double entry = (dir > 0) ? SymbolInfoDouble(g_sym, SYMBOL_ASK)
                            : SymbolInfoDouble(g_sym, SYMBOL_BID);
   double stop  = (st.dir != 0) ? st.stop
                                : ((dir > 0) ? entry - InpFallbackATR * g_b1.atr[1]
                                             : entry + InpFallbackATR * g_b1.atr[1]);
   // ---- 手数模式：风险% / 固定手数 / ATR 等价固定风险% ----
   double lots;
   if(InpLotMode == LOT_FIXED)
   {
      // 固定手数模式：恒定基础手数，仍按 regime 多空偏斜缩放(多=longSkew, 空=shortSkew)。
      // 基本面仓位系数不生效，手数不随净值浮动，保持字面量。
      lots = DinaNormalizeLot(g_sym, InpFixedLots * (dir > 0 ? longSkew : shortSkew));
   }
   else if(InpLotMode == LOT_ATR_RISK)
   {
      // ATR 等价固定风险%模式：每笔固定风险 InpRiskPct% 净值，手数由止损 ATR 距离反推。
      // 不采用凯利与基本面仓位系数，仅保留 regime 多空偏斜，使杠杆随波动自适应且信念中性。
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      double smult  = (dir > 0) ? longSkew : shortSkew;
      lots = DinaLotsForRisk(g_sym, equity, InpRiskPct, 0.0, smult,
                            MathAbs(entry - stop), InpMaxLots);
   }
   else
   {
      // 风险%模式（默认）：InpRiskPct% 净值 + 半凯利 + 基本面仓位系数，再乘 regime 偏斜。
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      double kelly  = InpUseKelly ? g_fund.kelly : 0.0;
      double base   = g_fund.loaded ? g_fund.sizeMult : 1.0;
      double smult  = (dir > 0) ? base * longSkew : base * shortSkew;
      lots = DinaLotsForRisk(g_sym, equity, InpRiskPct, kelly, smult,
                            MathAbs(entry - stop), InpMaxLots);
   }

   PrintFormat("[Dina] 信号 %s dir=%d 价=%.2f 止损=%.2f 手数=%.2f ATR=%.2f",
               why, dir, entry, stop, lots, g_b1.atr[1]);
   if(InpAllowTrade)
      DinaOpen(g_trade, g_sym, dir, lots, stop, "Dina:" + why, InpMagic, InpDeviation);
   else
      Print("[Dina] 仅提示模式，未下单");
   DrawPanel(st, h4, dir);     // 开仓后也刷新面板
}

//+------------------------------------------------------------------+
double CurrentMFE(int dir)
{
   ulong ticket; long ptype;
   if(!DinaFindPosition(g_sym, InpMagic, ticket, ptype)) return 0.0;
   if(!PositionSelectByTicket(ticket)) return 0.0;
   double entry = PositionGetDouble(POSITION_PRICE_OPEN);
   datetime t   = (datetime)PositionGetInteger(POSITION_TIME);
   MqlRates r1[];
   ArraySetAsSeries(r1, true);
   int shift = iBarShift(g_sym, PERIOD_H1, t);
   int bars = (shift > 0) ? shift + 1 : 1;
   if(bars > DINA_MAXBARS) bars = DINA_MAXBARS;
   if(CopyRates(g_sym, PERIOD_H1, 0, bars, r1) <= 0) return 0.0;
   return DinaMFE(r1, dir, entry, bars);
}

//+------------------------------------------------------------------+
void ManagePosition(ulong ticket, long ptype)
{
   if(!PositionSelectByTicket(ticket)) return;
   int dir   = (ptype == POSITION_TYPE_BUY) ? 1 : -1;
   double sl = PositionGetDouble(POSITION_SL);
   double entry = PositionGetDouble(POSITION_PRICE_OPEN);
   double mfe = CurrentMFE(dir);

   // 时间止损：超过最大持有K线数则平仓，避免资金被无限期占用
   if(InpMaxHoldBars > 0)
   {
      datetime t0 = (datetime)PositionGetInteger(POSITION_TIME);
      int held = iBarShift(g_sym, PERIOD_H1, t0);
      if(held >= InpMaxHoldBars)
      {
         DinaCloseTicket(g_trade, ticket, InpMagic, InpDeviation, "时间止损");
         return;
      }
   }

   if(!RefreshBuffers()) return;
   if(g_b1.atr[1] <= 0) return;
   if(!InpTrailing) return;
   double newSL;
   if(InpTrailMethod == 1)
   {
      // ATR回撤法：用已收盘K线(shift=1)的极值，不能用形成中的 shift=0
      double refH = iHigh(g_sym, PERIOD_H1, 1);
      double refL = iLow(g_sym, PERIOD_H1, 1);
      newSL = DinaTrailStopATR((int)ptype, sl, mfe, g_b1.atr[1], refH, refL,
                               InpTrailActivate, InpTrailATRMult);
   }
   else
      newSL = DinaTrailStop(g_b1, 1, (int)ptype, sl, mfe, InpTrailActivate, 0.0);
   if(dir > 0  && newSL > sl) DinaMoveSL(g_trade, g_sym, ticket, newSL, InpMagic);
   if(dir < 0  && (sl == 0 || newSL < sl) && newSL > 0)
      DinaMoveSL(g_trade, g_sym, ticket, newSL, InpMagic);
}

//+------------------------------------------------------------------+
bool CheckSpread()
{
   long sp = SymbolInfoInteger(g_sym, SYMBOL_SPREAD);
   if(sp > InpMaxSpreadPts)
   {
      Print("[Dina] 点差过大 ", sp, " > ", InpMaxSpreadPts, "，跳过");
      return false;
   }
   return true;
}

//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//| 彩色 GUI 面板：创建背景与标签对象池                              |
//+------------------------------------------------------------------+
void DinaCreatePanel()
{
   string bg = "DinaPanelBg";
   ObjectDelete(0, bg);
   if(ObjectCreate(0, bg, OBJ_RECTANGLE_LABEL, 0, 0, 0))
   {
      ObjectSetInteger(0, bg, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, bg, OBJPROP_XDISTANCE, 10);
      ObjectSetInteger(0, bg, OBJPROP_YDISTANCE, 10);
      ObjectSetInteger(0, bg, OBJPROP_XSIZE, 400);
      ObjectSetInteger(0, bg, OBJPROP_YSIZE, 440);
      ObjectSetInteger(0, bg, OBJPROP_FILL, true);
      ObjectSetInteger(0, bg, OBJPROP_BGCOLOR, C_PANEL_BG);
      ObjectSetInteger(0, bg, OBJPROP_COLOR, C_PANEL_BORDER);
      ObjectSetInteger(0, bg, OBJPROP_STYLE, STYLE_SOLID);
      ObjectSetInteger(0, bg, OBJPROP_BACK, true);
      ObjectSetInteger(0, bg, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, bg, OBJPROP_HIDDEN, true);
   }
   for(int i = 0; i < PANEL_MAX_LBL; i++)
   {
      string nm = "DinaLbl_" + IntegerToString(i);
      ObjectDelete(0, nm);
      if(ObjectCreate(0, nm, OBJ_LABEL, 0, 0, 0))
      {
         ObjectSetInteger(0, nm, OBJPROP_CORNER, CORNER_LEFT_UPPER);
         ObjectSetInteger(0, nm, OBJPROP_ANCHOR, ANCHOR_LEFT_UPPER);
         ObjectSetInteger(0, nm, OBJPROP_XDISTANCE, 20);
         ObjectSetInteger(0, nm, OBJPROP_YDISTANCE, 0);
         ObjectSetString(0, nm, OBJPROP_FONT, "Microsoft YaHei");
         ObjectSetInteger(0, nm, OBJPROP_FONTSIZE, 9);
         ObjectSetInteger(0, nm, OBJPROP_COLOR, C_TEXT);
         ObjectSetInteger(0, nm, OBJPROP_BACK, false);
         ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
         ObjectSetInteger(0, nm, OBJPROP_HIDDEN, true);
         g_lbl[i] = nm;
      }
   }
}

void DinaDestroyPanel()
{
   ObjectDelete(0, "DinaPanelBg");
   for(int i = 0; i < PANEL_MAX_LBL; i++)
      if(StringLen(g_lbl[i]) > 0) ObjectDelete(0, g_lbl[i]);
}

void PanelLine(string text, color c, int y, int x, int size)
{
   if(g_curLbl >= PANEL_MAX_LBL) return;
   string nm = g_lbl[g_curLbl];
   ObjectSetString(0, nm, OBJPROP_TEXT, text);
   ObjectSetInteger(0, nm, OBJPROP_COLOR, c);
   ObjectSetInteger(0, nm, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, nm, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, nm, OBJPROP_FONTSIZE, size);
   ObjectSetInteger(0, nm, OBJPROP_HIDDEN, false);
   g_curLbl++;
}

//+------------------------------------------------------------------+
void DrawPanel(const DinaSetup &st, int h4, int dir)
{
   // 记录最新快照，供 OnTimer 常驻刷新（即使无新 tick 也显示最新基本面）
   g_snapSt = st; g_snapH4 = h4; g_snapDir = dir;

   // ---- regime 门控（与 OnTick 决策完全一致，EA 自算）----
   bool allowLong, allowShort; double longSkew, shortSkew;
   DinaRegimeGate(g_fund, InpSkewFactor, InpNeutralFlatAside, allowLong, allowShort, longSkew, shortSkew);
   string regimeTxt = DinaRegimeText(allowLong, allowShort, longSkew, shortSkew);

   color biasC = (g_fund.bias > 0 ? C_RED : (g_fund.bias < 0 ? C_GREEN : C_GRAY));
   color d1C   = (g_fund.d1_trend > 0 ? C_RED : (g_fund.d1_trend < 0 ? C_GREEN : C_GRAY));
   color regC;
   if(!allowLong && !allowShort)        regC = C_GRAY;
   else if(allowLong && !allowShort)    regC = C_RED;
   else if(allowShort && !allowLong)    regC = C_GREEN;
   else regC = (longSkew > shortSkew ? C_ORANGE : C_CYAN);

   string biasTxt = (g_fund.bias > 0 ? "多" : (g_fund.bias < 0 ? "空" : "中性"));
   string d1Txt   = (g_fund.d1_trend > 0 ? "明显上涨↑" : (g_fund.d1_trend < 0 ? "明显下跌↓" : "不明显→"));
   color freshC   = g_fund.stale ? C_WARN : C_GRAY;
   string freshTxt = g_fund.stale ? (g_fund.ageHours < 0 ? "⚠无法解析更新时间" : "⚠陈旧 " + IntegerToString(g_fund.ageHours) + "h") : "✔新鲜";
   string vetoTxt = g_fund.loaded ? (g_fund.veto ? "启用" : "停用") : "无信号文件";

   g_curLbl = 0;
   int x = 20;
   int y = 22;
   int step = 18;

   PanelLine("‖ 帝娜黄金 · 实时判断面板 ‖", C_TITLE, y, x, 11); y += step + 4;

   PanelLine("【基本面判断】", C_SECTION, y, x, 10); y += step;
   PanelLine("信号更新 " + (g_fund.loaded ? g_fund.updated : "未加载") + "   " + freshTxt, freshC, y, x, 9); y += step;
   PanelLine(StringFormat("驱动总分 %+.2f/10    偏置 %s", g_fund.score, biasTxt), biasC, y, x, 9); y += step;
   PanelLine("日线趋势 " + d1Txt, d1C, y, x, 9); y += step;
   PanelLine("Regime门控 " + regimeTxt + "   多x" + DoubleToString(longSkew, 2) + " / 空x" + DoubleToString(shortSkew, 2), regC, y, x, 9); y += step;
   PanelLine("否决反向 " + vetoTxt + "  |  仓位系数 x" + DoubleToString(g_fund.sizeMult, 2) + "  |  凯利 " + DoubleToString(g_fund.kelly, 4), C_TEXT, y, x, 9); y += step;
   if(g_fund.dataWarn)
   {
      string wn = (g_fund.dataNote != "") ? g_fund.dataNote : "⚠ 基本面数据缺失/陈旧，偏置可能不可信";
      PanelLine(wn, C_RED, y, x, 9); y += step;
   }
   y += 6;
   PanelLine("【技术面 · 五要件】", C_SECTION, y, x, 10); y += step;
   string guppy = (g_b1.gsMin[1] > g_b1.glMax[1] ? "金叉" : (g_b1.gsMax[1] < g_b1.glMin[1] ? "死叉" : "未定"));
   PanelLine("顾比 " + guppy + "   回档 " + (st.dir > 0 ? "多" : (st.dir < 0 ? "空" : "-")), C_TEXT, y, x, 9); y += step;
   PanelLine(StringFormat("五要件: 回档%s 收口%s 过度%s 适离%s 渐短%s  => %d/5",
      (st.c1 ? "√" : "×"), (st.c2 ? "√" : "×"), (st.c3 ? "√" : "×"),
      (st.c4 ? "√" : "×"), (st.c5 ? "√" : "×"), st.score), C_TEXT, y, x, 9); y += step;
   PanelLine("4H形态 " + (h4 > 0 ? "看涨" : (h4 < 0 ? "看跌" : "-")) + "   决策 " + (dir > 0 ? "做多" : (dir < 0 ? "做空" : "观望")), C_TEXT, y, x, 9); y += step;
   PanelLine(StringFormat("ATR %.2f   布林 %.2f / %.2f / %.2f", g_b1.atr[1], g_b1.bbUp[1], g_b1.bbMid[1], g_b1.bbLo[1]), C_TEXT, y, x, 9); y += step;

   // 隐藏未用标签
   for(int i = g_curLbl; i < PANEL_MAX_LBL; i++)
      ObjectSetInteger(0, g_lbl[i], OBJPROP_HIDDEN, true);

   // 背景矩形跟随内容高度
   ObjectSetInteger(0, "DinaPanelBg", OBJPROP_YSIZE, y - 10 + 8);
   ObjectSetInteger(0, "DinaPanelBg", OBJPROP_XSIZE, 400);
   ChartRedraw(0);
}
//+------------------------------------------------------------------+
