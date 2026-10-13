//+------------------------------------------------------------------+
//| DinaCandles.mqh — candle convergence/divergence and reversal patterns                             |
//|   convergence/divergence binary: small body = convergence = alert signal; large body = divergence = confirmation signal           |
//|   4H three patterns: bullish/bearish engulfing / morning-evening star / piercing-dark cloud                  |
//+------------------------------------------------------------------+
#ifndef __DINACANDLES_MQH__
#define __DINACANDLES_MQH__

// series array: index 0 = latest (possibly unclosed), 1 = previous closed bar
double DinaBody(const MqlRates &r[], int i)  { return MathAbs(r[i].close - r[i].open); }
double DinaRange(const MqlRates &r[], int i) { return r[i].high - r[i].low; }
bool   DinaIsBull(const MqlRates &r[], int i){ return r[i].close > r[i].open; }
bool   DinaIsBear(const MqlRates &r[], int i){ return r[i].close < r[i].open; }

double DinaUpShadow(const MqlRates &r[], int i)
{ return r[i].high - MathMax(r[i].open, r[i].close); }
double DinaDnShadow(const MqlRates &r[], int i)
{ return MathMin(r[i].open, r[i].close) - r[i].low; }
double DinaShadow(const MqlRates &r[], int i)
{ return DinaUpShadow(r, i) + DinaDnShadow(r, i); }

//+------------------------------------------------------------------+
//| Convergent candle (alert signal): small body or doji                              |
//+------------------------------------------------------------------+
bool DinaConvergence(const MqlRates &r[], int i, int lookback, double ratio,
                     double shadowMult, double dojiRatio)
{
   int n = ArraySize(r);
   if(i + 1 >= n) return false;
   double body = DinaBody(r, i);
   double rng  = DinaRange(r, i);
   if(rng <= 0) return false;

   if(body / rng <= dojiRatio) return true;                       // doji
   double sum = 0; int cnt = 0;
   for(int k = i + 1; k <= i + lookback && k < n; k++) { sum += DinaBody(r, k); cnt++; }
   if(cnt == 0) return false;
   double avg = sum / cnt;
   bool smallBody = (avg > 0 && body <= ratio * avg);
   bool longShadow = (body > 0 && DinaShadow(r, i) >= shadowMult * body);
   return (smallBody && (longShadow || smallBody));
}

//+------------------------------------------------------------------+
//| Shadow shrinking: shadows shorten and body does not enlarge — pullback exhaustion                       |
//+------------------------------------------------------------------+
bool DinaShadowShrink(const MqlRates &r[], int i)
{
   int n = ArraySize(r);
   if(i + 1 >= n) return false;
   return (DinaShadow(r, i) < DinaShadow(r, i + 1)) &&
          (DinaBody(r, i) <= DinaBody(r, i + 1));
}

//+------------------------------------------------------------------+
//| Bullish engulfing / bearish engulfing                                              |
//+------------------------------------------------------------------+
bool DinaEngulfBull(const MqlRates &r[], int i, double ratio)
{
   int n = ArraySize(r);
   if(i + 1 >= n) return false;
   if(!DinaIsBear(r, i + 1) || !DinaIsBull(r, i)) return false;
   return (r[i].close >= r[i+1].open) && (r[i].open <= r[i+1].close) &&
          (DinaBody(r, i) >= ratio * DinaBody(r, i + 1));
}
bool DinaEngulfBear(const MqlRates &r[], int i, double ratio)
{
   int n = ArraySize(r);
   if(i + 1 >= n) return false;
   if(!DinaIsBull(r, i + 1) || !DinaIsBear(r, i)) return false;
   return (r[i].close <= r[i+1].open) && (r[i].open >= r[i+1].close) &&
          (DinaBody(r, i) >= ratio * DinaBody(r, i + 1));
}

//+------------------------------------------------------------------+
//| Morning star (dawn) / evening star                                       |
//+------------------------------------------------------------------+
bool DinaMorningStar(const MqlRates &r[], int i, int lookback, double midRatio)
{
   int n = ArraySize(r);
   if(i + 2 >= n) return false;
   double sum = 0; int cnt = 0;
   for(int k = i + 2; k <= i + 2 + lookback && k < n; k++) { sum += DinaBody(r, k); cnt++; }
   if(cnt == 0) return false;
   if(DinaBody(r, i + 1) > midRatio * (sum / cnt)) return false;   // the middle candle must be a small body
   double mid = (r[i+2].open + r[i+2].close) / 2.0;
   return DinaIsBear(r, i + 2) && DinaIsBull(r, i) && (r[i].close > mid);
}
bool DinaEveningStar(const MqlRates &r[], int i, int lookback, double midRatio)
{
   int n = ArraySize(r);
   if(i + 2 >= n) return false;
   double sum = 0; int cnt = 0;
   for(int k = i + 2; k <= i + 2 + lookback && k < n; k++) { sum += DinaBody(r, k); cnt++; }
   if(cnt == 0) return false;
   if(DinaBody(r, i + 1) > midRatio * (sum / cnt)) return false;
   double mid = (r[i+2].open + r[i+2].close) / 2.0;
   return DinaIsBull(r, i + 2) && DinaIsBear(r, i) && (r[i].close < mid);
}

//+------------------------------------------------------------------+
//| Piercing line / dark cloud cover                                                  |
//+------------------------------------------------------------------+
bool DinaPiercing(const MqlRates &r[], int i)
{
   int n = ArraySize(r);
   if(i + 1 >= n) return false;
   if(!DinaIsBear(r, i + 1) || !DinaIsBull(r, i)) return false;
   double mid = (r[i+1].open + r[i+1].close) / 2.0;
   return (r[i].open < r[i+1].close) && (r[i].close > mid) && (r[i].close < r[i+1].open);
}
bool DinaDarkCloud(const MqlRates &r[], int i)
{
   int n = ArraySize(r);
   if(i + 1 >= n) return false;
   if(!DinaIsBull(r, i + 1) || !DinaIsBear(r, i)) return false;
   double mid = (r[i+1].open + r[i+1].close) / 2.0;
   return (r[i].open > r[i+1].close) && (r[i].close < mid) && (r[i].close > r[i+1].open);
}

//+------------------------------------------------------------------+
//| 4H three-pattern summary: +1 bullish / -1 bearish / 0 none                       |
//+------------------------------------------------------------------+
int DinaH4Pattern(const MqlRates &r[], int i, double engulfRatio)
{
   if(DinaEngulfBull(r, i, engulfRatio) || DinaMorningStar(r, i, 20, 0.6) ||
      DinaPiercing(r, i)) return 1;
   if(DinaEngulfBear(r, i, engulfRatio) || DinaEveningStar(r, i, 20, 0.6) ||
      DinaDarkCloud(r, i)) return -1;
   return 0;
}

#endif
