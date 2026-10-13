//+------------------------------------------------------------------+
//| DinaIndicators.mqh — Dina system indicator layer                              |
//|   Bands(13, 0, 1.618) / Guppy multiple MA 6+6 / Stochastic / ATR        |
//+------------------------------------------------------------------+
#ifndef __DINAINDICATORS_MQH__
#define __DINAINDICATORS_MQH__

#define DINA_MAXBARS   600
#define DINA_GUPPY_N   6

struct DinaHandles
{
   int   bb;
   int   st;
   int   at;
   int   gs[DINA_GUPPY_N];
   int   gl[DINA_GUPPY_N];
};

struct DinaBuf
{
   double bbUp[];
   double bbMid[];
   double bbLo[];
   double stK[];
   double stD[];
   double atr[];
   double gsMin[];
   double gsMax[];
   double glMin[];
   double glMax[];
};

//+------------------------------------------------------------------+
void DinaInitHandles(DinaHandles &h, string sym, ENUM_TIMEFRAMES tf,
                     int bbPeriod, double bbDev,
                     int kP, int dP, int slow, int atrPeriod,
                     const int &shortArr[], const int &longArr[])
{
   h.bb = iBands(sym, tf, bbPeriod, 0, bbDev, PRICE_CLOSE);
   h.st = iStochastic(sym, tf, kP, dP, slow, MODE_SMA, STO_LOWHIGH);
   h.at = iATR(sym, tf, atrPeriod);
   for(int i = 0; i < DINA_GUPPY_N; i++)
   {
      h.gs[i] = iMA(sym, tf, shortArr[i], 0, MODE_EMA, PRICE_CLOSE);
      h.gl[i] = iMA(sym, tf, longArr[i], 0, MODE_EMA, PRICE_CLOSE);
   }
}

//+------------------------------------------------------------------+
void DinaRelease(DinaHandles &h)
{
   if(h.bb != INVALID_HANDLE) IndicatorRelease(h.bb);
   if(h.st != INVALID_HANDLE) IndicatorRelease(h.st);
   if(h.at != INVALID_HANDLE) IndicatorRelease(h.at);
   for(int i = 0; i < DINA_GUPPY_N; i++)
   {
      if(h.gs[i] != INVALID_HANDLE) IndicatorRelease(h.gs[i]);
      if(h.gl[i] != INVALID_HANDLE) IndicatorRelease(h.gl[i]);
   }
}

//+------------------------------------------------------------------+
//| All arrays are ordered with the closed bar at index 1 and the forming bar at index 0     |
//+------------------------------------------------------------------+
bool DinaRefresh(const DinaHandles &h, DinaBuf &b, int bars)
{
   int n = 0;
   n += CopyBuffer(h.bb, 1, 0, bars, b.bbUp);
   n += CopyBuffer(h.bb, 0, 0, bars, b.bbMid);
   n += CopyBuffer(h.bb, 2, 0, bars, b.bbLo);
   n += CopyBuffer(h.st, 0, 0, bars, b.stK);
   n += CopyBuffer(h.st, 1, 0, bars, b.stD);
   n += CopyBuffer(h.at, 0, 0, bars, b.atr);
   if(n <= 0) return false;

   ArrayResize(b.gsMin, bars);
   ArrayResize(b.gsMax, bars);
   ArrayResize(b.glMin, bars);
   ArrayResize(b.glMax, bars);
   for(int i = 0; i < bars; i++)
   {
      b.gsMin[i] = 1e18; b.gsMax[i] = -1e18;
      b.glMin[i] = 1e18; b.glMax[i] = -1e18;
   }
   double tmp[];
   ArrayResize(tmp, bars);
   for(int m = 0; m < DINA_GUPPY_N; m++)
   {
      if(CopyBuffer(h.gs[m], 0, 0, bars, tmp) != bars) return false;
      for(int i = 0; i < bars; i++)
      {
         if(tmp[i] < b.gsMin[i]) b.gsMin[i] = tmp[i];
         if(tmp[i] > b.gsMax[i]) b.gsMax[i] = tmp[i];
      }
      if(CopyBuffer(h.gl[m], 0, 0, bars, tmp) != bars) return false;
      for(int i = 0; i < bars; i++)
      {
         if(tmp[i] < b.glMin[i]) b.glMin[i] = tmp[i];
         if(tmp[i] > b.glMax[i]) b.glMax[i] = tmp[i];
      }
   }
   return true;
}

//+------------------------------------------------------------------+
//| Guppy state: +1 bullish cross (all short-period MAs above long-period group) / -1 bearish cross / 0 undefined    |
//+------------------------------------------------------------------+
int DinaGuppyState(const DinaBuf &b, int i)
{
   if(b.gsMin[i] > b.glMax[i]) return 1;
   if(b.gsMax[i] < b.glMin[i]) return -1;
   return 0;
}

//+------------------------------------------------------------------+
//| Pullback: after a cross, short group approaches but does not cross the long group                            |
//| returns +1 bullish pullback / -1 bearish pullback / 0 none                             |
//+------------------------------------------------------------------+
int DinaPullback(const DinaBuf &b, int i, double ratio)
{
   int st = 0;
   for(int k = i; k < ArraySize(b.gsMin); k++)
   {
      int s = DinaGuppyState(b, k);
      if(s != 0) { st = s; break; }   // most recent valid cross state (scanning into the past, aligned with Python ffill)
   }
   double a = b.atr[i];
   if(a <= 0) return 0;
   if(st == 1)
   {
      double gap = (b.gsMin[i] - b.glMax[i]) / a;
      if(gap > 0 && gap <= ratio) return 1;
   }
   else if(st == -1)
   {
      double gap = (b.glMin[i] - b.gsMax[i]) / a;
      if(gap > 0 && gap <= ratio) return -1;
   }
   return 0;
}

//+------------------------------------------------------------------+
//| Bollinger squeeze: current bandwidth is in the low quantile of the last lookback bars (narrow)            |
//| Fix: the original counted w>=cur (which detects "expansion"), opposite to this system's "squeeze" meaning  |
//|      now changed to count w<=cur (proportion of history narrower than current), aligned with       |
//|      Python bb_squeeze(w <= quantile(pct)).             |
//+------------------------------------------------------------------+
bool DinaSqueeze(const DinaBuf &b, int i, int lookback, double pct)
{
   int n = ArraySize(b.bbMid);
   int start = i, end = i + lookback;
   if(end >= n) end = n - 1;
   if(end - start < 20) return false;
   double cur = (b.bbUp[i] - b.bbLo[i]) / b.bbMid[i];
   int narrower = 0, total = 0;
   for(int k = start; k <= end; k++)
   {
      if(b.bbMid[k] <= 0) continue;
      double w = (b.bbUp[k] - b.bbLo[k]) / b.bbMid[k];
      total++;
      if(w <= cur) narrower++;          // narrower than current in history
   }
   if(total == 0) return false;
   return ((double)narrower / total <= pct);
}

//+------------------------------------------------------------------+
//| Bollinger expansion burst: 2 consecutive bars of widening bandwidth and the prior bar was a squeeze node           |
//| corresponds to Python bb_expand = (exp_cnt>=2) & squeeze.shift(1)          |
//+------------------------------------------------------------------+
bool DinaBandsExpand(const DinaBuf &b, int i, int lookback, double pct)
{
   int n = ArraySize(b.bbMid);
   if(i + 2 >= n) return false;
   double w0 = (b.bbUp[i]   - b.bbLo[i])   / b.bbMid[i];
   double w1 = (b.bbUp[i+1] - b.bbLo[i+1]) / b.bbMid[i+1];
   double w2 = (b.bbUp[i+2] - b.bbLo[i+2]) / b.bbMid[i+2];
   if(!(w0 > w1 && w1 > w2)) return false;     // 2 consecutive bars of widening bandwidth
   return DinaSqueeze(b, i + 1, lookback, pct); // the prior bar (i+1) is the squeeze node
}

#endif
