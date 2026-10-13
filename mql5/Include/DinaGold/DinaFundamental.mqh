//+------------------------------------------------------------------+
//| DinaFundamental.mqh — reads gold_signal.ini produced by the Python side        |
//| Fundamentals do three things only: directional bias / veto reverse signals / position sizing              |
//| The entry trigger is always technical: trend, level, pattern                                |
//+------------------------------------------------------------------+
#ifndef __DINAFUNDAMENTAL_MQH__
#define __DINAFUNDAMENTAL_MQH__

#define DINA_MAX_FACTORS 12   // max number of driver-factor details (for MT5 panel display)

struct DinaFund
{
   double score;       // -10 .. +10
   int    bias;        // +1 long / -1 short / 0 neutral
   int    d1_trend;    // +1 clear daily uptrend / -1 clear downtrend / 0 unclear (used by regime)
   double sizeMult;    // position sizing multiplier
   bool   veto;        // whether to veto signals opposite to the bias
   double kelly;       // Kelly f*
   double atr, bbUp, bbMid, bbLo;
   int    guppyState;
   double pivotP, pivotR1, pivotS1, fib382, fib618, lastPrice;
   string updated;
   bool   loaded;
   bool   stale;         // signal file not updated within timeout
   int    ageHours;      // hours since file was written (-1 = update time unparseable)
   int    biasState;     // 0=ok 1=carried (macro missing, reuse last bias) 2=unknown (missing, unreliable)
   double coverage;      // fundamental factor data coverage 0..1
   bool   dataWarn;      // fundamental data missing/stale warning (for panel display)
   string dataNote;      // data warning text
   int    nFactors;      // number of driver-factor details (stored in global arrays below)
};

// Driver-factor details (global arrays, to avoid struct member-array errors on some MT5 compilers)
string g_fundFactorName[DINA_MAX_FACTORS];
double g_fundFactorScore[DINA_MAX_FACTORS];
double g_fundFactorWeight[DINA_MAX_FACTORS];

//+------------------------------------------------------------------+
bool DinaParseKV(string line, string &key, string &val)
{
   int p = StringFind(line, "=");
   if(p <= 0) return false;
   key = StringSubstr(line, 0, p);
   val = StringSubstr(line, p + 1);
   StringTrimLeft(key); StringTrimRight(key);
   StringTrimLeft(val); StringTrimRight(val);
   return (StringLen(key) > 0);
}

//+------------------------------------------------------------------+
//| Parse Python-side updated=YYYY-MM-DD HH:MM                       |
//+------------------------------------------------------------------+
datetime DinaParseUpdated(string s)
{
   if(StringLen(s) < 8) return 0;
   string t = s;
   StringReplace(t, "-", ".");          // MQL5's StringToTime expects "yyyy.mm.dd hh:mi"
   StringReplace(t, "/", ".");
   StringReplace(t, "T", " ");
   if(StringLen(t) > 16) t = StringSubstr(t, 0, 16);   // truncate to minutes
   return StringToTime(t);
}

//+------------------------------------------------------------------+
bool DinaLoadFundamental(string fileName, DinaFund &f, int maxAgeHours = 24)
{
   f.loaded = false;
   f.score = 0; f.bias = 0; f.d1_trend = 0; f.sizeMult = 1.0; f.veto = true; f.kelly = 0;
   f.atr = 0; f.bbUp = 0; f.bbMid = 0; f.bbLo = 0; f.guppyState = 0;
   f.pivotP = 0; f.pivotR1 = 0; f.pivotS1 = 0;
   f.fib382 = 0; f.fib618 = 0; f.lastPrice = 0; f.updated = "";
   f.stale = false; f.ageHours = -1; f.nFactors = 0;
   f.biasState = 0; f.coverage = 1.0; f.dataWarn = false; f.dataNote = "";

   int h = FileOpen(fileName, FILE_READ | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE)
   {
      Print("[Dina] ", fileName, " not found, running pure-technical mode");
      return false;
   }
   while(!FileIsEnding(h))
   {
      string line = FileReadString(h);
      if(StringLen(line) == 0) continue;
      if(StringGetCharacter(line, 0) == ';') continue;
      string k, v;
      if(!DinaParseKV(line, k, v)) continue;
      if(k      == "score")      f.score      = StringToDouble(v);
      else if(k == "bias")       f.bias       = (int)StringToInteger(v);
      else if(k == "d1_trend")    f.d1_trend   = (int)StringToInteger(v);
      else if(k == "size_mult")  f.sizeMult   = StringToDouble(v);
      else if(k == "veto")       f.veto       = (StringToInteger(v) != 0);
      else if(k == "kelly")      f.kelly      = StringToDouble(v);
      else if(k == "atr")        f.atr        = StringToDouble(v);
      else if(k == "bb_up")      f.bbUp       = StringToDouble(v);
      else if(k == "bb_mid")     f.bbMid      = StringToDouble(v);
      else if(k == "bb_lo")      f.bbLo       = StringToDouble(v);
      else if(k == "guppy_state")f.guppyState = (int)StringToInteger(v);
      else if(k == "pivot_p")    f.pivotP     = StringToDouble(v);
      else if(k == "pivot_r1")   f.pivotR1    = StringToDouble(v);
      else if(k == "pivot_s1")   f.pivotS1    = StringToDouble(v);
      else if(k == "fib_382")    f.fib382     = StringToDouble(v);
      else if(k == "fib_618")    f.fib618     = StringToDouble(v);
      else if(k == "last_price") f.lastPrice  = StringToDouble(v);
      else if(k == "updated")    f.updated    = v;
      else if(k == "bias_state")
      {
         if(v == "carried")      f.biasState = 1;
         else if(v == "unknown") f.biasState = 2;
         else                    f.biasState = 0;
      }
      else if(k == "coverage")   f.coverage   = StringToDouble(v);
      else if(k == "data_note")  f.dataNote   = v;
      else if(k == "factors")    // driver-factor details: name:score:weight|name:score:weight|...
      {
         string items[]; int ni = StringSplit(v, '|', items);
         for(int q = 0; q < ni && f.nFactors < DINA_MAX_FACTORS; q++)
         {
            string seg[3];
            if(StringSplit(items[q], ':', seg) < 2) continue;
            g_fundFactorName[f.nFactors]  = seg[0];
            g_fundFactorScore[f.nFactors] = StringToDouble(seg[1]);
            g_fundFactorWeight[f.nFactors] = (ArraySize(seg) > 2) ? StringToDouble(seg[2]) : 0.0;
            f.nFactors++;
         }
      }
   }
   FileClose(h);
   f.loaded = true;
   if(f.sizeMult <= 0) f.sizeMult = 1.0;

   // --- Signal file freshness protection ---
   // Avoid the EA silently using yesterday's bias to veto today's real signals when Python didn't run today.
   // Threshold passed by caller (EA uses InpMaxSignalAgeHours, default 24 hours).
   datetime ut = DinaParseUpdated(f.updated);
   if(ut > 0)
      f.ageHours = (int)MathMax(0, (TimeCurrent() - ut) / 3600);
   f.stale = (maxAgeHours > 0) && (ut <= 0 || f.ageHours > maxAgeHours);
   if(f.stale)
   {
      f.veto = false;            // disable fundamental veto
      f.sizeMult = 1.0;          // disable fundamental position scaling (back to pure-technical, fixed 1.0)
      // keep kelly as-is: it comes from backtest, intraday variation is minimal; InpUseKelly can disable it separately
      PrintFormat("[Dina] ⚠ signal file %s, fundamental veto & size-scaling disabled (threshold %d h; ageHours=%d)",
                  (ut <= 0 ? "cannot parse updated field" :
                             IntegerToString(f.ageHours) + "h stale"),
                  maxAgeHours, f.ageHours);
   }

   // data warning: macro missing-reuse / missing-unreliable / coverage too low — surface the degradation on the panel
   f.dataWarn = (f.biasState != 0) || (f.coverage > 0 && f.coverage < 0.6);

   PrintFormat("[Dina] driver %.2f  bias %d  d1_trend %d  size x%.2f  kelly %.4f  updated %s  stale=%s  factors %d  dataWarn=%s",
               f.score, f.bias, f.d1_trend, f.sizeMult, f.kelly, f.updated, f.stale ? "Y" : "N", f.nFactors,
               f.dataWarn ? "Y" : "N");
   return true;
}

//+------------------------------------------------------------------+
//| regime matrix: fundamental bias × daily trend -> direction gate + position skew          |
//| returns allowLong/allowShort (direction switches) and longSkew/shortSkew          |
//| (relative to base lot multiplier: favored side = 1.0, unfavored side = skew).                |
//| stale signal file -> fall back to long-only (conservative, consistent with validated system).          |
//|   bearish bias + clear downtrend -> short only;   bearish bias + no clear downtrend -> both (short>long)       |
//|   bullish bias + clear uptrend -> long only;   bullish bias + no clear uptrend -> both (long>short)       |
//|   neutral + daily no trend (=0) -> stand aside (neutralFlatAside, adopted in B3);      |
//|   neutral + daily has direction -> long only (fall back to validated long-edge).             |
//+------------------------------------------------------------------+
void DinaRegimeGate(DinaFund &f, double skew, bool neutralFlatAside,
                    bool &allowLong, bool &allowShort,
                    double &longSkew, double &shortSkew)
{
   allowLong = true;  allowShort = true;  longSkew = 1.0;  shortSkew = 1.0;
   if(f.stale)                       // stale signal file -> conservative fall back to long-only
   {
      allowLong = true;  allowShort = false;  longSkew = 1.0; shortSkew = 0.0;
      return;
   }
   int b = (f.bias > 0 ? 1 : (f.bias < 0 ? -1 : 0));
   int t = (f.d1_trend > 0 ? 1 : (f.d1_trend < 0 ? -1 : 0));
   if(b < 0)                        // bearish bias
   {
      if(t == -1)                   // bearish bias + clear downtrend -> short only
         { allowLong = false; allowShort = true;  longSkew = 0.0; shortSkew = 1.0; }
      else                          // bearish bias + no clear downtrend -> both, short>long
         { allowLong = true;  allowShort = true;  longSkew = skew; shortSkew = 1.0; }
   }
   else if(b > 0)                   // bullish bias
   {
      if(t == 1)                    // bullish bias + clear uptrend -> long only
         { allowLong = true;  allowShort = false; longSkew = 1.0; shortSkew = 0.0; }
      else                          // bullish bias + no clear uptrend -> both, long>short
         { allowLong = true;  allowShort = true;  longSkew = 1.0; shortSkew = skew; }
   }
   else                             // b==0 neutral: no fundamental directional view
   {
      if(t == 0 && neutralFlatAside) // neutral and daily has no clear trend -> stand aside (adopted in B3)
         { allowLong = false; allowShort = false; longSkew = 0.0; shortSkew = 0.0; }
      else                          // neutral + daily has direction -> long only (no shorts)
         { allowLong = true;  allowShort = false; longSkew = 1.0; shortSkew = 0.0; }
   }
}

//+------------------------------------------------------------------+
//| Translate the regime-gate result into English                    |
//| (consistent with Python run_daily.py)                            |
//+------------------------------------------------------------------+
string DinaRegimeText(bool allowLong, bool allowShort, double longSkew, double shortSkew)
{
   if(!allowLong && !allowShort)     return "Stand aside (flat)";
   if(allowLong && !allowShort)      return "Long only";
   if(allowShort && !allowLong)      return "Short only";
   return (longSkew > shortSkew) ? "Long > Short" : "Short > Long";
}

#endif
