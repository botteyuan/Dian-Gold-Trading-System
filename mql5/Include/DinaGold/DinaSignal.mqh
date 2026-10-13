//+------------------------------------------------------------------+
//| DinaSignal.mqh — 1H five conditions & 4H three patterns                  |
//|   Entry five conditions: pullback (trend) / squeeze-divergence / exhaustion / proximity (level) / contraction (pattern)  |
//|   Exit: initial stop + large-move close beyond outer band + small-move close back through middle band      |
//|         + trailing stop (Dina's third law: always use a stop, never take profit)             |
//+------------------------------------------------------------------+
#ifndef __DINASIGNAL_MQH__
#define __DINASIGNAL_MQH__
#include "DinaIndicators.mqh"
#include "DinaCandles.mqh"
#include "DinaLevels.mqh"

struct DinaSetup
{
   int    dir;        // +1 long / -1 short / 0 no signal
   int    score;      // number of conditions met (0..5)
   bool   c1, c2, c3, c4, c5;
   double price;      // reference price (close of the signal-confirming bar)
   double stop;       // initial stop loss
   double atr;
};

//+------------------------------------------------------------------+
//| 1H five-condition evaluation (i should be a closed-bar index, usually = 1)               |
//+------------------------------------------------------------------+
void DinaEvalH1(const MqlRates   &r[],
                const DinaBuf    &b,
                const DinaLevelSet &ls,
                int               i,
                double            pullbackRatio,
                int               squeezeLookback, double squeezePct,
                int               stochK, int stochD, double obLevel, double osLevel,
                double            proxATR,
                int               bodyLookback, double bodyRatio,
                double            shadowMult, double dojiRatio,
                double            stopBufferATR, double minStopATR, double fallbackATR,
                int               minScore,
                DinaSetup        &out)
{
   out.dir = 0; out.score = 0;
   out.c1 = out.c2 = out.c3 = out.c4 = out.c5 = false;
   out.atr = b.atr[i];
   out.price = r[i].close;

   // ① Pullback (trend) — first condition
   int pb = DinaPullback(b, i, pullbackRatio);
   if(pb == 0) return;                       // no pullback, no need to continue
   out.c1 = true;

   // ② Squeeze [divergence]: aligned with Python (bb_squeeze | bb_expand | divergence)
   bool sq  = DinaSqueeze(b, i, squeezeLookback, squeezePct);
   bool exp = DinaBandsExpand(b, i, squeezeLookback, squeezePct);
   bool diverge = (pb > 0) ? (r[i].close <= b.bbLo[i] + proxATR * b.atr[i])
                           : (r[i].close >= b.bbUp[i] - proxATR * b.atr[i]);
   out.c2 = (sq || exp || diverge);

   // ③ Exhaustion: aligned with Python (oversold/overbought within last 3 bars, with stochastic K turning up/down)
   double k0 = b.stK[i], k1 = b.stK[i + 1], k2 = b.stK[i + 2];
   if(pb > 0)
      out.c3 = (k1 <= osLevel || k0 <= osLevel || k2 <= osLevel) && (k0 > k1);
   else
      out.c3 = (k1 >= obLevel || k0 >= obLevel || k2 >= obLevel) && (k0 < k1);

   // ④ Proximity (level): aligned with Python (any of the nearest 2 key levels <= prox)
   double d0 = 1e18, d1 = 1e18;
   for(int m = 0; m < ls.count; m++)
   {
      double d = MathAbs(ls.lv[m] - r[i].close);
      if(d < d0) { d1 = d0; d0 = d; }
      else if(d < d1) { d1 = d; }
   }
   out.c4 = (d0 <= proxATR * b.atr[i]) || (d1 <= proxATR * b.atr[i]);

   // ⑤ Contraction (micro convergence/divergence): aligned with Python (convergence(i) | convergence(i+1))
   out.c5 = DinaConvergence(r, i, bodyLookback, bodyRatio, shadowMult, dojiRatio)
            || DinaConvergence(r, i + 1, bodyLookback, bodyRatio, shadowMult, dojiRatio);

   out.score = (out.c1 ? 1 : 0) + (out.c2 ? 1 : 0) + (out.c3 ? 1 : 0)
             + (out.c4 ? 1 : 0) + (out.c5 ? 1 : 0);
   if(out.score < minScore) { out.dir = 0; return; }
   out.dir = pb;

   // initial stop: beyond a valid key level + ATR buffer
   double buf = stopBufferATR * b.atr[i];
   if(pb > 0)
   {
      double sup = DinaSupport(ls, r[i].close);
      double ref = (sup > 0) ? sup : (r[i].close - fallbackATR * b.atr[i]);
      out.stop = ref - buf;
      if(r[i].close - out.stop < minStopATR * b.atr[i])
         out.stop = r[i].close - minStopATR * b.atr[i];
   }
   else
   {
      double res = DinaResistance(ls, r[i].close);
      double ref = (res > 0) ? res : (r[i].close + fallbackATR * b.atr[i]);
      out.stop = ref + buf;
      if(out.stop - r[i].close < minStopATR * b.atr[i])
         out.stop = r[i].close + minStopATR * b.atr[i];
   }
}

//+------------------------------------------------------------------+
//| Exit decision: i = closed-bar index. Returns 0=hold / 1=close                |
//| closeBeyondMiddle: whether to allow "close back through middle band on small move" to close.          |
//|   Default false (aligned with Python backtest close_beyond_middle:false),   |
//|   to avoid the middle band sweeping the position out early and inverting the R:R.                         |
//+------------------------------------------------------------------+
int DinaCheckExit(const MqlRates &r[], const DinaBuf &b, int i,
                  int posType, double entry, double mfe,
                  double bigMoveATR, double atrEntry, bool closeBeyondMiddle)
{
   double a = (atrEntry > 0) ? atrEntry : b.atr[i];
   bool big = (mfe >= bigMoveATR * a);
   if(big)
   {
      // after a large move: close beyond the Bollinger outer band -> close (divergence extreme, take profit)
      if(posType == POSITION_TYPE_BUY  && r[i].close >= b.bbUp[i]) return 1;
      if(posType == POSITION_TYPE_SELL && r[i].close <= b.bbLo[i]) return 1;
   }
   else if(closeBeyondMiddle)
   {
      // after a small move: close back through the Bollinger middle band -> close
      if(posType == POSITION_TYPE_BUY  && r[i].close < b.bbMid[i]) return 1;
      if(posType == POSITION_TYPE_SELL && r[i].close > b.bbMid[i]) return 1;
   }
   return 0;
}

//+------------------------------------------------------------------+
//| Trailing stop price (middle-band method)                                            |
//+------------------------------------------------------------------+
double DinaTrailStop(const DinaBuf &b, int i, int posType, double curStop,
                     double mfe, double activateATR, double atrEntry)
{
   double a = (atrEntry > 0) ? atrEntry : b.atr[i];
   if(mfe < activateATR * a) return curStop;
   if(posType == POSITION_TYPE_BUY)
      return MathMax(curStop, b.bbMid[i]);
   else
      return (curStop > 0) ? MathMin(curStop, b.bbMid[i]) : b.bbMid[i];
}

//+------------------------------------------------------------------+
//| Trailing stop price (ATR-retracement method)                                         |
//|   refHigh/refLow must be the extreme of a "closed" bar (shift=1), not a forming      |
//|   bar (shift=0), otherwise the stop would use future prices.                      |
//| Python backtest evidence: middle-band method tightens too early and cuts trend profit; ATR-retracement is better.  |
//+------------------------------------------------------------------+
double DinaTrailStopATR(int posType, double curStop, double mfe, double a,
                        double refHigh, double refLow, double activateATR,
                        double atrMult)
{
   if(a <= 0) return curStop;
   if(mfe < activateATR * a) return curStop;
   if(posType == POSITION_TYPE_BUY)
   {
      double cand = refHigh - atrMult * a;
      return MathMax(curStop, cand);
   }
   else
   {
      double cand = refLow + atrMult * a;
      return (curStop > 0) ? MathMin(curStop, cand) : cand;
   }
}

#endif
