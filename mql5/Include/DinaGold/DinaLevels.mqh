//+------------------------------------------------------------------+
//| DinaLevels.mqh — pivot-point mixed Fibonacci levels (level)                  |
//|   Fibonacci retracement 0/0.236/0.382/0.5/0.618/0.786/1                     |
//|   Fibonacci extension 1.272/1.618/2.618                                  |
//|   classic pivot points P/R1/S1/R2/S2 (from previous day D1 HLC)                  |
//+------------------------------------------------------------------+
#ifndef __DINALEVELS_MQH__
#define __DINALEVELS_MQH__

#define DINA_MAX_LEVELS 16

struct DinaLevelSet
{
   double lv[DINA_MAX_LEVELS];
   int    count;
   double legHigh;
   double legLow;
   int    legDir;      // +1 rising impulse wave / -1 falling impulse wave
};

//+------------------------------------------------------------------+
bool DinaIsSwingHigh(const MqlRates &r[], int i, int L, int R)
{
   int n = ArraySize(r);
   if(i - R < 0 || i + L >= n) return false;
   for(int k = i - R; k <= i + L; k++)
      if(r[k].high > r[i].high) return false;
   return true;
}
bool DinaIsSwingLow(const MqlRates &r[], int i, int L, int R)
{
   int n = ArraySize(r);
   if(i - R < 0 || i + L >= n) return false;
   for(int k = i - R; k <= i + L; k++)
      if(r[k].low < r[i].low) return false;
   return true;
}

//+------------------------------------------------------------------+
//| Take the two most recent confirmed alternating swing points to form an "impulse wave"                        |
//+------------------------------------------------------------------+
void DinaFindLeg(const MqlRates &r[], int L, int R, int window,
                 double &hi, double &lo, int &dir)
{
   int n = ArraySize(r);
   int lim = MathMin(window, n - 1);
   int iH = -1, iL = -1;
   for(int i = R; i <= lim; i++)
   {
      if(iH < 0 && DinaIsSwingHigh(r, i, L, R)) iH = i;
      if(iL < 0 && DinaIsSwingLow(r, i, L, R))  iL = i;
      if(iH >= 0 && iL >= 0) break;
   }
   if(iH < 0 || iL < 0) { dir = 0; hi = 0; lo = 0; return; }
   hi = r[iH].high;
   lo = r[iL].low;
   dir = (iH < iL) ? 1 : -1;     // smaller index = more recent; a closer high => rising impulse wave
}

//+------------------------------------------------------------------+
void DinaBuildLevels(DinaLevelSet &ls, const MqlRates &r1h[], int L, int R,
                     int window, const double &fibRet[], const double &fibExt[],
                     double pivotP, double pivotR1, double pivotS1,
                     double pivotR2, double pivotS2)
{
   double hi, lo; int dir;
   DinaFindLeg(r1h, L, R, window, hi, lo, dir);
   ls.legHigh = hi; ls.legLow = lo; ls.legDir = dir; ls.count = 0;

   double rng = hi - lo;
   if(dir != 0 && rng > 0)
   {
      int nr = ArraySize(fibRet);
      for(int i = 0; i < nr && ls.count < DINA_MAX_LEVELS - 5; i++)
      {
         double v = (dir == 1) ? (hi - rng * fibRet[i]) : (lo + rng * fibRet[i]);
         ls.lv[ls.count++] = v;
      }
      int ne = ArraySize(fibExt);
      for(int i = 0; i < ne && ls.count < DINA_MAX_LEVELS - 5; i++)
      {
         double v = (dir == 1) ? (hi + rng * (fibExt[i] - 1.0))
                               : (lo - rng * (fibExt[i] - 1.0));
         ls.lv[ls.count++] = v;
      }
   }
   if(pivotP > 0)
   {
      ls.lv[ls.count++] = pivotP;
      ls.lv[ls.count++] = pivotR1;
      ls.lv[ls.count++] = pivotS1;
      ls.lv[ls.count++] = pivotR2;
      ls.lv[ls.count++] = pivotS2;
   }
}

//+------------------------------------------------------------------+
//| Nearest key level to price and its distance                                     |
//+------------------------------------------------------------------+
double DinaNearestLevel(const DinaLevelSet &ls, double price, double &dist)
{
   double best = 0; dist = 1e18;
   for(int i = 0; i < ls.count; i++)
   {
      double d = MathAbs(ls.lv[i] - price);
      if(d < dist) { dist = d; best = ls.lv[i]; }
   }
   return best;
}

//+------------------------------------------------------------------+
//| Effective support (nearest level below price) / effective resistance (nearest level above price)        |
//+------------------------------------------------------------------+
double DinaSupport(const DinaLevelSet &ls, double price)
{
   double best = 0, bd = 1e18;
   for(int i = 0; i < ls.count; i++)
   {
      if(ls.lv[i] >= price) continue;
      double d = price - ls.lv[i];
      if(d < bd) { bd = d; best = ls.lv[i]; }
   }
   return best;
}
double DinaResistance(const DinaLevelSet &ls, double price)
{
   double best = 0, bd = 1e18;
   for(int i = 0; i < ls.count; i++)
   {
      if(ls.lv[i] <= price) continue;
      double d = ls.lv[i] - price;
      if(d < bd) { bd = d; best = ls.lv[i]; }
   }
   return best;
}

//+------------------------------------------------------------------+
//| Classic pivot points (input previous day D1 H/L/C)                              |
//+------------------------------------------------------------------+
void DinaPivot(double H, double L, double C,
               double &P, double &R1, double &S1, double &R2, double &S2)
{
   P  = (H + L + C) / 3.0;
   R1 = 2.0 * P - L;
   S1 = 2.0 * P - H;
   R2 = P + (H - L);
   S2 = P - (H - L);
}

#endif
