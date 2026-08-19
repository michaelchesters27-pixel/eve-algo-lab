//+------------------------------------------------------------------+
//| EVE_4CCB_IC_Broker_Calibrator.mq5                                |
//| Research-only telemetry for the frozen 4CCB project.             |
//| This EA NEVER places, modifies or closes trades.                 |
//+------------------------------------------------------------------+
#property strict
#property version   "0.10"
#property description "EVE 4CCB broker/symbol calibration telemetry - no trading"

input bool   InpEnableTelemetry       = true;
input int    InpSampleSeconds         = 30;
input string InpEndpoint              = "https://evealgolab.netlify.app/api/research/4ccb-broker-calibration/sample";
input bool   InpVerboseLogging        = true;

const string CLIENT_VERSION = "EVE-4CCB-calibrator-0.1";

string JsonEscape(string value)
{
   StringReplace(value,"\\","\\\\");
   StringReplace(value,"\"","\\\"");
   StringReplace(value,"\r","\\r");
   StringReplace(value,"\n","\\n");
   return value;
}

string JsonBool(const bool value)
{
   return value ? "true" : "false";
}

string JsonNumber(const double value,const int precision=10)
{
   if(!MathIsValidNumber(value)) return "0";
   return DoubleToString(value,precision);
}

int ServerUtcOffsetSeconds()
{
   datetime server=TimeTradeServer();
   datetime utc=TimeGMT();
   if(server <= 0 || utc <= 0) return 0;
   return (int)(server-utc);
}

bool BuildPayload(string &payload)
{
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol,tick))
   {
      if(InpVerboseLogging) Print("EVE 4CCB calibrator: SymbolInfoTick failed, error=",GetLastError());
      return false;
   }

   const double point=SymbolInfoDouble(_Symbol,SYMBOL_POINT);
   const double tick_size=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   const double tick_value=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE);
   const double tick_value_profit=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE_PROFIT);
   const double tick_value_loss=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE_LOSS);
   const double contract_size=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_CONTRACT_SIZE);
   const double volume_min=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   const double volume_step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   const double volume_max=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   const double swap_long=SymbolInfoDouble(_Symbol,SYMBOL_SWAP_LONG);
   const double swap_short=SymbolInfoDouble(_Symbol,SYMBOL_SWAP_SHORT);
   const long digits=SymbolInfoInteger(_Symbol,SYMBOL_DIGITS);
   const long stops_level=SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL);
   const bool spread_float=(bool)SymbolInfoInteger(_Symbol,SYMBOL_SPREAD_FLOAT);

   if(point <= 0 || tick_size <= 0 || contract_size <= 0 || volume_min <= 0 || volume_step <= 0 || volume_max <= 0)
   {
      if(InpVerboseLogging) Print("EVE 4CCB calibrator: incomplete symbol specification; nothing sent.");
      return false;
   }

   const double spread_price=MathMax(0.0,tick.ask-tick.bid);
   const double spread_points=spread_price/point;
   const long trade_mode=AccountInfoInteger(ACCOUNT_TRADE_MODE);

   payload="{";
   payload+="\"symbol\":\""+JsonEscape(_Symbol)+"\",";
   payload+="\"broker_company\":\""+JsonEscape(AccountInfoString(ACCOUNT_COMPANY))+"\",";
   payload+="\"broker_server\":\""+JsonEscape(AccountInfoString(ACCOUNT_SERVER))+"\",";
   payload+="\"account_currency\":\""+JsonEscape(AccountInfoString(ACCOUNT_CURRENCY))+"\",";
   payload+="\"account_trade_mode\":"+IntegerToString(trade_mode)+",";
   payload+="\"terminal_time\":"+IntegerToString((long)TimeTradeServer())+",";
   payload+="\"server_utc_offset_seconds\":"+IntegerToString(ServerUtcOffsetSeconds())+",";
   payload+="\"bid\":"+JsonNumber(tick.bid,10)+",";
   payload+="\"ask\":"+JsonNumber(tick.ask,10)+",";
   payload+="\"spread_price\":"+JsonNumber(spread_price,10)+",";
   payload+="\"spread_points\":"+JsonNumber(spread_points,4)+",";
   payload+="\"digits\":"+IntegerToString(digits)+",";
   payload+="\"point\":"+JsonNumber(point,12)+",";
   payload+="\"tick_size\":"+JsonNumber(tick_size,12)+",";
   payload+="\"tick_value\":"+JsonNumber(tick_value,10)+",";
   payload+="\"tick_value_profit\":"+JsonNumber(tick_value_profit,10)+",";
   payload+="\"tick_value_loss\":"+JsonNumber(tick_value_loss,10)+",";
   payload+="\"contract_size\":"+JsonNumber(contract_size,4)+",";
   payload+="\"volume_min\":"+JsonNumber(volume_min,4)+",";
   payload+="\"volume_step\":"+JsonNumber(volume_step,4)+",";
   payload+="\"volume_max\":"+JsonNumber(volume_max,4)+",";
   payload+="\"stops_level_points\":"+IntegerToString(stops_level)+",";
   payload+="\"spread_float\":"+JsonBool(spread_float)+",";
   payload+="\"swap_long\":"+JsonNumber(swap_long,8)+",";
   payload+="\"swap_short\":"+JsonNumber(swap_short,8)+",";
   payload+="\"client_version\":\""+CLIENT_VERSION+"\"";
   payload+="}";
   return true;
}

void SendSample(const bool force_log=false)
{
   if(!InpEnableTelemetry || MQLInfoInteger(MQL_TESTER)) return;

   string payload;
   if(!BuildPayload(payload)) return;

   char data[];
   int copied=StringToCharArray(payload,data,0,WHOLE_ARRAY,CP_UTF8);
   if(copied <= 0) return;
   if(ArraySize(data) > 0) ArrayResize(data,ArraySize(data)-1);

   char result[];
   string response_headers;
   string headers="Content-Type: application/json\r\nAccept: application/json\r\n";
   ResetLastError();
   int status=WebRequest("POST",InpEndpoint,headers,5000,data,result,response_headers);
   int mql_error=GetLastError();

   if(status >= 200 && status < 300)
   {
      if(InpVerboseLogging && force_log)
         Print("EVE 4CCB calibrator: connected. Broker telemetry sample accepted. No trading functions are present in this EA.");
      return;
   }

   if(InpVerboseLogging)
      Print("EVE 4CCB calibrator: telemetry failed HTTP=",status," MQL=",mql_error,
            ". In MT5 add https://evealgolab.netlify.app under Tools > Options > Expert Advisors > Allow WebRequest for listed URL.");
}

int OnInit()
{
   int seconds=InpSampleSeconds;
   if(seconds < 10) seconds=10;
   EventSetTimer(seconds);
   Print("EVE 4CCB broker calibrator loaded on ",_Symbol,". TELEMETRY ONLY — it cannot place trades.");
   SendSample(true);
   return INIT_SUCCEEDED;
}

void OnTimer()
{
   SendSample(false);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("EVE 4CCB broker calibrator stopped. reason=",reason);
}

void OnTick()
{
   // Intentionally empty. The calibrator never trades.
}
