//+------------------------------------------------------------------+
//|                                            DinaGuppy.mq5         |
//|  Guppy Multiple Moving Average (short group 6 lines + long group 6 lines)      |
//|  Usage: drag onto XAUUSD H1 chart; watch "cross (alert) -> pullback (confirm)" |
//+------------------------------------------------------------------+
#property copyright "Dina Gold Trading System"
#property version   "1.00"
#property indicator_chart_window
#property indicator_buffers 12
#property indicator_plots   12

#property indicator_label1  "GMMA-S1"
#property indicator_type1   DRAW_LINE
#property indicator_color1  clrDodgerBlue
#property indicator_width1  1
#property indicator_label2  "GMMA-S2"
#property indicator_type2   DRAW_LINE
#property indicator_color2  clrDodgerBlue
#property indicator_width2  1
#property indicator_label3  "GMMA-S3"
#property indicator_type3   DRAW_LINE
#property indicator_color3  clrDodgerBlue
#property indicator_width3  1
#property indicator_label4  "GMMA-S4"
#property indicator_type4   DRAW_LINE
#property indicator_color4  clrDodgerBlue
#property indicator_width4  1
#property indicator_label5  "GMMA-S5"
#property indicator_type5   DRAW_LINE
#property indicator_color5  clrDodgerBlue
#property indicator_width5  1
#property indicator_label6  "GMMA-S6"
#property indicator_type6   DRAW_LINE
#property indicator_color6  clrDodgerBlue
#property indicator_width6  1

#property indicator_label7  "GMMA-L1"
#property indicator_type7   DRAW_LINE
#property indicator_color7  clrOrangeRed
#property indicator_width7  1
#property indicator_label8  "GMMA-L2"
#property indicator_type8   DRAW_LINE
#property indicator_color8  clrOrangeRed
#property indicator_width8  1
#property indicator_label9  "GMMA-L3"
#property indicator_type9   DRAW_LINE
#property indicator_color9  clrOrangeRed
#property indicator_width9  1
#property indicator_label10 "GMMA-L4"
#property indicator_type10  DRAW_LINE
#property indicator_color10 clrOrangeRed
#property indicator_width10 1
#property indicator_label11 "GMMA-L5"
#property indicator_type11  DRAW_LINE
#property indicator_color11 clrOrangeRed
#property indicator_width11 1
#property indicator_label12 "GMMA-L6"
#property indicator_type12  DRAW_LINE
#property indicator_color12 clrOrangeRed
#property indicator_width12 1

input int    InpShort1 = 3;
input int    InpShort2 = 5;
input int    InpShort3 = 8;
input int    InpShort4 = 10;
input int    InpShort5 = 12;
input int    InpShort6 = 15;
input int    InpLong1  = 30;
input int    InpLong2  = 35;
input int    InpLong3  = 40;
input int    InpLong4  = 45;
input int    InpLong5  = 50;
input int    InpLong6  = 60;
input ENUM_MA_METHOD InpMethod = MODE_EMA;

double buf1[], buf2[], buf3[], buf4[], buf5[], buf6[];
double buf7[], buf8[], buf9[], buf10[], buf11[], buf12[];
int    h[12];

//+------------------------------------------------------------------+
int OnInit()
{
   int p[12];
   p[0]=InpShort1; p[1]=InpShort2; p[2]=InpShort3; p[3]=InpShort4;
   p[4]=InpShort5; p[5]=InpShort6; p[6]=InpLong1;  p[7]=InpLong2;
   p[8]=InpLong3;  p[9]=InpLong4;  p[10]=InpLong5; p[11]=InpLong6;

   SetIndexBuffer(0,  buf1,  INDICATOR_DATA);
   SetIndexBuffer(1,  buf2,  INDICATOR_DATA);
   SetIndexBuffer(2,  buf3,  INDICATOR_DATA);
   SetIndexBuffer(3,  buf4,  INDICATOR_DATA);
   SetIndexBuffer(4,  buf5,  INDICATOR_DATA);
   SetIndexBuffer(5,  buf6,  INDICATOR_DATA);
   SetIndexBuffer(6,  buf7,  INDICATOR_DATA);
   SetIndexBuffer(7,  buf8,  INDICATOR_DATA);
   SetIndexBuffer(8,  buf9,  INDICATOR_DATA);
   SetIndexBuffer(9,  buf10, INDICATOR_DATA);
   SetIndexBuffer(10, buf11, INDICATOR_DATA);
   SetIndexBuffer(11, buf12, INDICATOR_DATA);
   for(int i = 0; i < 12; i++)
   {
      PlotIndexSetInteger(i, PLOT_SHIFT, 0);
      PlotIndexSetString(i, PLOT_LABEL, (i < 6 ? "GMMA-S" : "GMMA-L") + IntegerToString(i % 6 + 1));
      h[i] = iMA(_Symbol, PERIOD_CURRENT, p[i], 0, InpMethod, PRICE_CLOSE);
      if(h[i] == INVALID_HANDLE) return INIT_FAILED;
   }
   IndicatorSetString(INDICATOR_SHORTNAME, "DinaGuppy");
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   for(int i = 0; i < 12; i++)
      if(h[i] != INVALID_HANDLE) IndicatorRelease(h[i]);
}

//+------------------------------------------------------------------+
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
{
   if(rates_total < 70) return 0;
   if(CopyBuffer(h[0],  0, 0, rates_total, buf1)  <= 0) return 0;
   if(CopyBuffer(h[1],  0, 0, rates_total, buf2)  <= 0) return 0;
   if(CopyBuffer(h[2],  0, 0, rates_total, buf3)  <= 0) return 0;
   if(CopyBuffer(h[3],  0, 0, rates_total, buf4)  <= 0) return 0;
   if(CopyBuffer(h[4],  0, 0, rates_total, buf5)  <= 0) return 0;
   if(CopyBuffer(h[5],  0, 0, rates_total, buf6)  <= 0) return 0;
   if(CopyBuffer(h[6],  0, 0, rates_total, buf7)  <= 0) return 0;
   if(CopyBuffer(h[7],  0, 0, rates_total, buf8)  <= 0) return 0;
   if(CopyBuffer(h[8],  0, 0, rates_total, buf9)  <= 0) return 0;
   if(CopyBuffer(h[9],  0, 0, rates_total, buf10) <= 0) return 0;
   if(CopyBuffer(h[10], 0, 0, rates_total, buf11) <= 0) return 0;
   if(CopyBuffer(h[11], 0, 0, rates_total, buf12) <= 0) return 0;
   return rates_total;
}
//+------------------------------------------------------------------+
