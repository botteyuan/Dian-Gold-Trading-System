//+------------------------------------------------------------------+
//|                                            DinaGoldTrader.mq5    |
//|  Dina Gold Trading System - behavioral analysis (technical) execution layer                |
//|                                                                  |
//|                                                                  |
//|  Entry (all three factors: trend, level, pattern present):                          |
//|    1H 5 conditions = pullback (Guppy) + squeeze/divergence (Bollinger) + exhaustion (Stochastic) |
//|                + proximity (pivot + Fibonacci) + convergence (candle contraction)     |
//|    4H 3 patterns = bullish/bearish engulfing / morning-evening star / piercing-dark cloud (must be at band) |
//|  Exit: initial stop / large move close beyond outer band / small move close back through middle |
//|        / middle-band trailing stop / close on opposite signal                              |
//|  Fundamentals: read MQL5/Files/gold_signal.ini (produced by Python side)                     |
//|          used only for directional bias, vetoing opposite signals, and position sizing       |
//+------------------------------------------------------------------+
#property copyright "Dina Gold Trading System"
#property version   "1.00"
#property description "Dina Gold Trading System - 1H 5-Conditions / 4H 3-Patterns / Bollinger Exit"
#property strict

#include <DinaGold/DinaIndicators.mqh>
#include <DinaGold/DinaCandles.mqh>
#include <DinaGold/DinaLevels.mqh>
#include <DinaGold/DinaSignal.mqh>
#include <DinaGold/DinaTrade.mqh>
#include <DinaGold/DinaFundamental.mqh>

//+------------------------------------------------------------------+
//| Color GUI panel (OBJ_LABEL + OBJ_RECTANGLE_LABEL)                                            |
//+------------------------------------------------------------------+
#define PANEL_MAX_LBL    40
#define C_PANEL_BG       C'18,22,30'
#define C_PANEL_BORDER   C'70,95,130'
#define C_TITLE          C'255,200,90'
#define C_SECTION        C'130,185,255'
#define C_FACTORSEC      C'180,150,255'
#define C_TEXT           C'210,215,225'
#define C_RED            C'235,85,85'     // long / rising (Chinese convention: red for up)
#define C_GREEN          C'70,205,130'   // short / falling (Chinese convention: green for down)
#define C_GRAY           C'150,155,168'
#define C_ORANGE         C'240,165,65'
#define C_CYAN           C'85,200,225'
#define C_WARN           C'245,120,120'
string g_lbl[PANEL_MAX_LBL];
int    g_curLbl = 0;

//+------------------------------------------------------------------+
//| Position sizing mode                                                                   |
//+------------------------------------------------------------------+
enum ENUM_LOT_MODE { LOT_RISK = 0, LOT_FIXED = 1, LOT_ATR_RISK = 2 };

//+------------------------------------------------------------------+
//| Input parameters                                                                       |
//+------------------------------------------------------------------+
input group "===== Symbol & Execution ====="
input string  InpSymbol        = "XAUUSD";      // trading symbol
input ulong   InpMagic         = 20260907;      // magic number
input int     InpDeviation     = 30;            // allowed slippage (points)
input bool    InpAllowTrade    = true;          // allow live orders (false = hint only)

input group "===== Bollinger Bands(13,0,1.618) ====="
input int     InpBBPeriod      = 13;            // period
input double  InpBBDeviation   = 1.618;         // standard deviation multiplier
input int     InpSqueezeLook   = 120;           // squeeze lookback bars
input double  InpSqueezePct    = 0.25;          // squeeze quantile threshold

input group "===== Guppy Multiple MA ====="
input double  InpPullbackRatio = 0.60;          // pullback proximity threshold (ATR multiple)

input group "===== Stochastic Oscillator ====="
input int     InpStochK        = 5;
input int     InpStochD        = 3;
input int     InpStochSlow     = 3;
input double  InpOverBought    = 80;
input double  InpOverSold      = 20;

input group "===== Pivot + Fibonacci Hybrid ====="
input int     InpSwingLeft     = 5;             // fractal left leg
input int     InpSwingRight    = 5;             // fractal right leg
input int     InpSwingWindow   = 200;           // swing point search window
input bool    InpUsePivot      = true;          // enable pivot points
input double  InpProxATR       = 0.35;          // proximity threshold (ATR multiple)

input group "===== Candle Convergence/Divergence ====="
input int     InpBodyLookback  = 20;
input double  InpBodyRatio     = 0.60;          // small-body ratio
input double  InpShadowMult    = 1.50;          // long-shadow multiplier
input double  InpDojiRatio     = 0.10;          // doji threshold

input group "===== Entry / Exit ====="
input int     InpMinScore      = 3;             // minimum conditions to satisfy (3 = pullback + two others)
input bool    InpUseH4         = true;          // enable 4H chart 3 patterns
input double  InpH4BandATR     = 0.50;          // tolerance for "at Bollinger band" (ATR)
input double  InpEngulfRatio   = 1.00;          // engulfing body ratio
input double  InpStopBufferATR = 0.30;          // buffer beyond key level
// Minimum stop distance. At 0.80, ~84% of trades get stopped out within 24 bars, while the
// median max favorable excursion for holding 24 bars is 2.65 ATR — inverting the R:R. 3.00 is empirically optimal.
input double  InpMinStopATR    = 3.00;
input double  InpFallbackATR   = 1.20;          // stop distance when no key level is present
input double  InpBigMoveATR    = 2.00;          // "large move" threshold
input bool    InpTrailing      = true;          // trailing stop
input int     InpTrailMethod   = 1;             // 0=middle band 1=ATR retracement
input double  InpTrailActivate = 2.50;          // profit (in ATR) needed to activate trailing
input double  InpTrailATRMult  = 2.00;          // retracement multiplier for the ATR-trailing method
input int     InpMaxHoldBars   = 24;            // max bars to hold a position (0=unlimited)
input bool    InpAllowShort    = true;          // master safety switch for shorting (on by default); long/short decided by the regime matrix
input bool    InpReverseClose  = true;          // close on opposite signal
// Whether to close when a small move closes back through the middle band. Default false, aligned with the Python backtest close_beyond_middle
// to avoid the middle band sweeping the position out early and inverting the R:R (the classic cause of being whipsawed near the middle band in live trading).
input bool    InpCloseBeyondMiddle = false;     // close as soon as a small move crosses back through the middle band
input double  InpSkewFactor    = 0.40;           // position multiplier for the unfavored direction (favored direction = 1.0)
input bool    InpNeutralFlatAside = true;          // stand aside when neutral + daily no trend (adopted in B3)
// 4H three-pattern resonance (core of the original "Dina system"):
//   true  = enter only when 1H five conditions AND 4H three patterns agree in direction (AND, faithful to original)
//   false = enter when either 1H five conditions OR 4H three patterns trigger (OR, old logic)
// [Evidence 2026-09-19] backtest (2023-2026 gold bull market, long-only) shows 4H resonance weakens positive expectation
//   (pure 1H PF=1.22 -> strict AND PF=0.19 / recent window W=24 PF=0.87), so default off to keep the pure-1H optimal system.
input bool    InpH4Resonance    = false;         // 4H+1H resonance (AND); off by default (evidence shows it weakens the long edge)

input group "===== Position & Risk ====="
input double  InpRiskPct       = 1.0;           // risk per trade as % of equity
input bool    InpUseKelly      = true;          // use Python-side Kelly f*
input double  InpMaxLots       = 5.0;
input ENUM_LOT_MODE InpLotMode = LOT_RISK;     // position sizing mode (0=risk-based %, 1=fixed lots, 2=ATR-equalized fixed risk%)
input double  InpFixedLots     = 0.1;          // fixed lots per trade (used when InpLotMode = LOT_FIXED)
input int     InpMaxSpreadPts  = 60;            // spread filter (points)

input group "===== Fundamental File ====="
input string  InpSignalFile    = "gold_signal.ini";
input int     InpReloadMinutes = 60;            // signal file refresh interval
input int     InpMaxSignalAgeHours = 24;        // signal-file staleness threshold (hours); beyond it, disable fundamental veto

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
DinaSetup    g_snapSt;       // latest technical snapshot (for OnTimer's persistent panel refresh)
int          g_snapH4 = 0;
int          g_snapDir = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   g_sym = (InpSymbol == "") ? _Symbol : InpSymbol;
   if(!SymbolInfoInteger(g_sym, SYMBOL_SELECT))
   {
      Print("[Dina] symbol not available: ", g_sym);
      return INIT_FAILED;
   }
   SymbolSelect(g_sym, true);

   DinaInitHandles(g_h1, g_sym, PERIOD_H1, InpBBPeriod, InpBBDeviation,
                   InpStochK, InpStochD, InpStochSlow, 14, g_shortArr, g_longArr);
   DinaInitHandles(g_h4, g_sym, PERIOD_H4, InpBBPeriod, InpBBDeviation,
                   InpStochK, InpStochD, InpStochSlow, 14, g_shortArr, g_longArr);
   if(g_h1.bb == INVALID_HANDLE || g_h4.bb == INVALID_HANDLE)
   {
      Print("[Dina] indicator handle creation failed");
      return INIT_FAILED;
   }
   g_trade.SetExpertMagicNumber(InpMagic);
   DinaLoadFundamental(InpSignalFile, g_fund);
   g_lastFundLoad = TimeCurrent();
   EventSetTimer(2);          // refresh the fundamental panel every 2 seconds (persistent display, independent of ticks)
   DinaCreatePanel();         // create the colored GUI panel objects
   Comment("");               // clear the old plain-text panel
   Print("[Dina] init done, symbol=", g_sym, " allowTrade=", InpAllowTrade);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   DinaDestroyPanel();        // clean up the colored GUI panel objects
   EventKillTimer();
   DinaRelease(g_h1);
   DinaRelease(g_h4);
}

//+------------------------------------------------------------------+
//| Periodically reload the fundamental file (shared by OnTick / OnTimer)                       |
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
//| Periodically refresh the panel (independent of price ticks, keep fundamental info persistently visible)          |
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
//| Build key levels from H1 closed bars and the previous D1 pivot                        |
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
//| 4H three patterns (must appear on a Bollinger band)                             |
//+------------------------------------------------------------------+
int H4Setup()
{
   MqlRates r4[];
   ArraySetAsSeries(r4, true);
   if(CopyRates(g_sym, PERIOD_H4, 0, 200, r4) <= 0) return 0;
   int i = 1;                                    // previous closed H4 bar
   int pat = DinaH4Pattern(r4, i, InpEngulfRatio);
   if(pat == 0) return 0;
   double tol = InpH4BandATR * g_b4.atr[i];
   if(pat > 0  && MathAbs(r4[i].close - g_b4.bbLo[i]) <= tol) return 1;
   if(pat < 0  && MathAbs(r4[i].close - g_b4.bbUp[i]) <= tol) return -1;
   return 0;
}

//+------------------------------------------------------------------+
//| Fundamental veto                                                        |
//+------------------------------------------------------------------+
bool Vetoed(int dir)
{
   if(!g_fund.loaded || !g_fund.veto) return false;
   if(g_fund.bias > 0 && dir < 0) { Print("[Dina] fundamental veto: bias long, short blocked"); return true; }
   if(g_fund.bias < 0 && dir > 0) { Print("[Dina] fundamental veto: bias short, long blocked"); return true; }
   return false;
}

//+------------------------------------------------------------------+
void OnTick()
{
   datetime cur1h = iTime(g_sym, PERIOD_H1, 0);
   if(cur1h == 0) return;

   // periodically reload the fundamental file (also called by OnTimer, so the panel updates even without ticks)
   ReloadFundIfNeeded();

   // position management (every tick)
   ulong ticket; long ptype;
   bool hasPos = DinaFindPosition(g_sym, InpMagic, ticket, ptype);
   if(hasPos) ManagePosition(ticket, ptype);

   // only make entry/exit decisions on a new bar
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

   // ---- Position: check exit first ----
   if(hasPos)
   {
      int dir = (ptype == POSITION_TYPE_BUY) ? 1 : -1;
      if(DinaCheckExit(r1, g_b1, 1, (int)ptype,
                       PositionGetDouble(POSITION_PRICE_OPEN),
                       CurrentMFE(dir), InpBigMoveATR, 0.0,
                       InpCloseBeyondMiddle) == 1)
      {
         DinaCloseTicket(g_trade, ticket, InpMagic, InpDeviation, "Bollinger exit");
         return;
      }
      if(InpReverseClose)
      {
         int opp = (dir > 0) ? -1 : 1;
         if((st.dir == opp && st.score >= InpMinScore) || h4 == opp)
         {
            DinaCloseTicket(g_trade, ticket, InpMagic, InpDeviation, "Reverse entry signal");
            return;
         }
      }
      return;   // already in a position, do not open a new one
   }

   // ---- Open position ----
   int dir = 0; string why = "";
   if(InpH4Resonance)
   {
      // original: 1H five conditions AND 4H three patterns agree in direction (AND)
      if(st.dir != 0 && h4 != 0 && h4 == st.dir)
         { dir = st.dir; why = StringFormat("1H+4H resonance (%d/5)", st.score); }
   }
   else
   {
      // Pure 1H five conditions: fully aligned with the Python backtest require_h4_resonance=false (4H does not participate in entry).
      // Note: earlier EA versions used an OR logic of "1H or 4H either triggers" here, which was the source of overtrading (19 trades) in live trading — now removed.
      if(st.dir != 0) { dir = st.dir; why = StringFormat("1H 5-conditions (%d/5)", st.score); }
   }
   if(dir == 0) { DrawPanel(st, h4, dir); return; }

   // ---- regime matrix: fundamental bias × daily trend -> direction gate + position skew ----
   bool allowLong, allowShort; double longSkew, shortSkew;
   DinaRegimeGate(g_fund, InpSkewFactor, InpNeutralFlatAside, allowLong, allowShort, longSkew, shortSkew);
   if(dir > 0 && !allowLong)  { Print("[Dina] regime gate blocks long"); DrawPanel(st, h4, dir); return; }
   if(dir < 0 && !allowShort) { Print("[Dina] regime gate blocks short"); DrawPanel(st, h4, dir); return; }
   if(dir < 0 && !InpAllowShort) { DrawPanel(st, h4, dir); return; }   // master shorting safety switch

   if(!CheckSpread()) { DrawPanel(st, h4, dir); return; }

   double entry = (dir > 0) ? SymbolInfoDouble(g_sym, SYMBOL_ASK)
                            : SymbolInfoDouble(g_sym, SYMBOL_BID);
   double stop  = (st.dir != 0) ? st.stop
                                : ((dir > 0) ? entry - InpFallbackATR * g_b1.atr[1]
                                             : entry + InpFallbackATR * g_b1.atr[1]);
   double lots;
   if(InpLotMode == LOT_FIXED)
   {
      // Fixed-lot mode: a constant base lot, still scaled by the regime's
      // long/short skew (long=longSkew, short=shortSkew). The fundamental size
      // multiplier is NOT applied, so the lot stays literal regardless of equity.
      lots = DinaNormalizeLot(g_sym, InpFixedLots * (dir > 0 ? longSkew : shortSkew));
   }
   else if(InpLotMode == LOT_ATR_RISK)
   {
      // ATR-equalized fixed-risk mode: each trade risks exactly InpRiskPct% of
      // equity, with the lot derived from the stop's ATR distance. Kelly and the
      // fundamental size multiplier are NOT applied; only the regime long/short
      // skew (longSkew/shortSkew) is kept so the leverage stays volatility-adaptive
      // but conviction-neutral.
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      double smult  = (dir > 0) ? longSkew : shortSkew;
      lots = DinaLotsForRisk(g_sym, equity, InpRiskPct, 0.0, smult,
                            MathAbs(entry - stop), InpMaxLots);
   }
   else
   {
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      double kelly  = InpUseKelly ? g_fund.kelly : 0.0;
      double base   = g_fund.loaded ? g_fund.sizeMult : 1.0;
      double smult  = (dir > 0) ? base * longSkew : base * shortSkew;
      lots = DinaLotsForRisk(g_sym, equity, InpRiskPct, kelly, smult,
                            MathAbs(entry - stop), InpMaxLots);
   }

   PrintFormat("[Dina] signal %s dir=%d price=%.2f stop=%.2f lots=%.2f ATR=%.2f",
               why, dir, entry, stop, lots, g_b1.atr[1]);
   if(InpAllowTrade)
      DinaOpen(g_trade, g_sym, dir, lots, stop, "Dina:" + why, InpMagic, InpDeviation);
   else
      Print("[Dina] hint-only mode, no order placed");
   DrawPanel(st, h4, dir);     // also refresh the panel after opening
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

   // time stop: close if held beyond the max bar count, to avoid capital being locked up indefinitely
   if(InpMaxHoldBars > 0)
   {
      datetime t0 = (datetime)PositionGetInteger(POSITION_TIME);
      int held = iBarShift(g_sym, PERIOD_H1, t0);
      if(held >= InpMaxHoldBars)
      {
         DinaCloseTicket(g_trade, ticket, InpMagic, InpDeviation, "Time stop");
         return;
      }
   }

   if(!RefreshBuffers()) return;
   if(g_b1.atr[1] <= 0) return;
   if(!InpTrailing) return;
   double newSL;
   if(InpTrailMethod == 1)
   {
      // ATR-retracement method: use extremes of closed bars (shift=1), not the forming bar (shift=0)
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
      Print("[Dina] spread too high: ", sp, " > ", InpMaxSpreadPts, ", skip");
      return false;
   }
   return true;
}

//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//| Colored GUI panel: create the background and label object pool                              |
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
   // record the latest snapshot for OnTimer's persistent refresh (shows latest fundamentals even without new ticks)
   g_snapSt = st; g_snapH4 = h4; g_snapDir = dir;

   // ---- regime gate (identical to OnTick decision, computed by the EA) ----
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

   string biasTxt = (g_fund.bias > 0 ? "Long" : (g_fund.bias < 0 ? "Short" : "Neutral"));
   string d1Txt   = (g_fund.d1_trend > 0 ? "Rising↑" : (g_fund.d1_trend < 0 ? "Falling↓" : "Unclear→"));
   color freshC   = g_fund.stale ? C_WARN : C_GRAY;
   string freshTxt = g_fund.stale ? (g_fund.ageHours < 0 ? "⚠ cannot parse update time" : "⚠ stale " + IntegerToString(g_fund.ageHours) + "h") : "✔ fresh";
   string vetoTxt = g_fund.loaded ? (g_fund.veto ? "on" : "off") : "no signal file";

   g_curLbl = 0;
   int x = 20;
   int y = 22;
   int step = 18;

   PanelLine("Dina Gold · Live Panel", C_TITLE, y, x, 11); y += step + 4;

   PanelLine("Fundamental", C_SECTION, y, x, 10); y += step;
   PanelLine("Signal Updated " + (g_fund.loaded ? g_fund.updated : "not loaded") + "   " + freshTxt, freshC, y, x, 9); y += step;
   PanelLine(StringFormat("Driver Score %+.2f/10    Bias %s", g_fund.score, biasTxt), biasC, y, x, 9); y += step;
   PanelLine("D1 Trend " + d1Txt, d1C, y, x, 9); y += step;
   PanelLine("Regime Gate " + regimeTxt + "   Long x" + DoubleToString(longSkew, 2) + " / Short x" + DoubleToString(shortSkew, 2), regC, y, x, 9); y += step;
   PanelLine("Veto Reverse " + vetoTxt + "  |  Size x" + DoubleToString(g_fund.sizeMult, 2) + "  |  Kelly " + DoubleToString(g_fund.kelly, 4), C_TEXT, y, x, 9); y += step;
   if(g_fund.dataWarn)
   {
      string wn = (g_fund.dataNote != "") ? g_fund.dataNote : "⚠ fundamental data missing/stale, bias may be unreliable";
      PanelLine(wn, C_RED, y, x, 9); y += step;
   }
   y += 6;
   PanelLine("Technical · 5 Conditions", C_SECTION, y, x, 10); y += step;
   string guppy = (g_b1.gsMin[1] > g_b1.glMax[1] ? "Bullish Cross" : (g_b1.gsMax[1] < g_b1.glMin[1] ? "Bearish Cross" : "Undefined"));
   PanelLine("Guppy " + guppy + "   Pullback " + (st.dir > 0 ? "Long" : (st.dir < 0 ? "Short" : "-")), C_TEXT, y, x, 9); y += step;
   PanelLine(StringFormat("5 Conditions: Pullback %s Squeeze/Div %s Exhaust %s Proximity %s Shrink %s  => %d/5",
      (st.c1 ? "√" : "×"), (st.c2 ? "√" : "×"), (st.c3 ? "√" : "×"),
      (st.c4 ? "√" : "×"), (st.c5 ? "√" : "×"), st.score), C_TEXT, y, x, 9); y += step;
   PanelLine("4H Pattern " + (h4 > 0 ? "Bullish" : (h4 < 0 ? "Bearish" : "-")) + "   Decision " + (dir > 0 ? "Long" : (dir < 0 ? "Short" : "Standby")), C_TEXT, y, x, 9); y += step;
   PanelLine(StringFormat("ATR %.2f   Bollinger %.2f / %.2f / %.2f", g_b1.atr[1], g_b1.bbUp[1], g_b1.bbMid[1], g_b1.bbLo[1]), C_TEXT, y, x, 9); y += step;

   // hide unused labels
   for(int i = g_curLbl; i < PANEL_MAX_LBL; i++)
      ObjectSetInteger(0, g_lbl[i], OBJPROP_HIDDEN, true);

   // background rectangle follows the content height
   ObjectSetInteger(0, "DinaPanelBg", OBJPROP_YSIZE, y - 10 + 8);
   ObjectSetInteger(0, "DinaPanelBg", OBJPROP_XSIZE, 400);
   ChartRedraw(0);
}
//+------------------------------------------------------------------+
