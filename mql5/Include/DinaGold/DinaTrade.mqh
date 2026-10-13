//+------------------------------------------------------------------+
//| DinaTrade.mqh — order entry, position sizing (Kelly/fixed risk), stop management            |
//+------------------------------------------------------------------+
#ifndef __DINATRADE_MQH__
#define __DINATRADE_MQH__
#include <Trade/Trade.mqh>
#include <Trade/PositionInfo.mqh>

//+------------------------------------------------------------------+
//| account-currency amount per 1.0 price move and per 1 lot (gold typically 100)     |
//+------------------------------------------------------------------+
double DinaMoneyPerUnit(string sym)
{
   double tv = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double ts = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   if(ts <= 0) return 1.0;
   if(tv <= 0)   // some brokers leave tick value blank, fall back to contract size
      return SymbolInfoDouble(sym, SYMBOL_TRADE_CONTRACT_SIZE);
   return tv / ts;
}

//+------------------------------------------------------------------+
double DinaNormalizeLot(string sym, double lots)
{
   double mn = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double mx = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   double st = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   if(st <= 0) st = 0.01;
   lots = MathFloor(lots / st) * st;
   if(lots < mn) lots = mn;
   if(lots > mx) lots = mx;
   int digits = (int)MathRound(MathLog10(1.0 / st));
   return NormalizeDouble(lots, MathMax(0, digits));
}

//+------------------------------------------------------------------+
//| Position: risk amount / (stop distance * value per point)                            |
//| when kelly > 0, use Kelly f* instead of fixed risk ratio (half-Kelly already applied on Python side)  |
//+------------------------------------------------------------------+
double DinaLotsForRisk(string sym, double equity, double riskPct,
                       double kellyF, double sizeMult, double stopDist,
                       double maxLots)
{
   if(stopDist <= 0) return SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double pct = riskPct;
   if(kellyF > 0) pct = MathMin(kellyF * 100.0, riskPct * 3.0);
   double money = equity * pct / 100.0 * sizeMult;
   double lots  = money / (stopDist * DinaMoneyPerUnit(sym));
   lots = DinaNormalizeLot(sym, lots);
   if(maxLots > 0 && lots > maxLots) lots = DinaNormalizeLot(sym, maxLots);
   return lots;
}

//+------------------------------------------------------------------+
//| push the stop beyond the broker's minimum allowed distance                                  |
//+------------------------------------------------------------------+
double DinaClampStop(string sym, int dir, double price, double sl)
{
   int stops  = (int)SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL);
   int freeze = (int)SymbolInfoInteger(sym, SYMBOL_TRADE_FREEZE_LEVEL);
   int level  = MathMax(stops, freeze) + 1;
   double pt  = SymbolInfoDouble(sym, SYMBOL_POINT);
   double minDist = level * pt;
   double dist = (dir > 0) ? (price - sl) : (sl - price);
   if(dist < minDist)
      sl = (dir > 0) ? (price - minDist) : (price + minDist);
   return sl;
}

//+------------------------------------------------------------------+
//| Open position. dir: +1 buy / -1 sell                                          |
//+------------------------------------------------------------------+
bool DinaOpen(CTrade &trade, string sym, int dir, double lots,
              double sl, string comment, ulong magic, int deviation)
{
   trade.SetExpertMagicNumber(magic);
   trade.SetDeviationInPoints(deviation);
   trade.SetTypeFillingBySymbol(sym);
   double price = (dir > 0) ? SymbolInfoDouble(sym, SYMBOL_ASK)
                            : SymbolInfoDouble(sym, SYMBOL_BID);
   int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   price = NormalizeDouble(price, digits);
   sl    = NormalizeDouble(DinaClampStop(sym, dir, price, sl), digits);
   bool ok = (dir > 0) ? trade.Buy(lots, sym, 0.0, sl, 0.0, comment)
                       : trade.Sell(lots, sym, 0.0, sl, 0.0, comment);
   if(!ok) Print("[Dina] open failed retcode=", trade.ResultRetcode(),
                 " ", trade.ResultRetcodeDescription());
   return ok;
}

//+------------------------------------------------------------------+
//| Modify stop loss (only when improving)                                          |
//+------------------------------------------------------------------+
bool DinaMoveSL(CTrade &trade, string sym, ulong ticket, double newSL, ulong magic)
{
   if(!PositionSelectByTicket(ticket)) return false;
   double old = PositionGetDouble(POSITION_SL);
   long   type = PositionGetInteger(POSITION_TYPE);
   int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   newSL = NormalizeDouble(newSL, digits);
   bool better = (type == POSITION_TYPE_BUY)  ? (newSL > old + 1e-9 && newSL < SymbolInfoDouble(sym, SYMBOL_BID))
                                              : ((old <= 0) || (newSL < old - 1e-9 && newSL > SymbolInfoDouble(sym, SYMBOL_ASK)));
   if(!better) return false;
   trade.SetExpertMagicNumber(magic);
   return trade.PositionModify(ticket, newSL, 0.0);
}

//+------------------------------------------------------------------+
void DinaCloseTicket(CTrade &trade, ulong ticket, ulong magic, int deviation, string why)
{
   if(!PositionSelectByTicket(ticket)) return;
   trade.SetExpertMagicNumber(magic);
   trade.SetDeviationInPoints(deviation);
   if(!trade.PositionClose(ticket))
      Print("[Dina] close failed retcode=", trade.ResultRetcode(), " ", why);
   else
      Print("[Dina] closed ", why);
}

//+------------------------------------------------------------------+
//| Find this EA's open position                                                    |
//+------------------------------------------------------------------+
bool DinaFindPosition(string sym, ulong magic, ulong &ticket, long &type)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(!PositionSelectByTicket(t)) continue;
      if(PositionGetString(POSITION_SYMBOL) != sym) continue;
      if(PositionGetInteger(POSITION_MAGIC) != (long)magic) continue;
      ticket = t; type = PositionGetInteger(POSITION_TYPE);
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Maximum favorable excursion (MFE) since position open, estimated from closed bars                     |
//+------------------------------------------------------------------+
double DinaMFE(const MqlRates &r[], int dir, double entry, int bars)
{
   int n = ArraySize(r);
   int lim = MathMin(bars, n);
   double mfe = 0;
   for(int i = 0; i < lim; i++)
   {
      double d = (dir > 0) ? (r[i].high - entry) : (entry - r[i].low);
      if(d > mfe) mfe = d;
   }
   return mfe;
}

#endif
