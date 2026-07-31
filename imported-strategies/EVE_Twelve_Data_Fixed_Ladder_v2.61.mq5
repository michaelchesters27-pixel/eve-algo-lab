#property copyright "EVE Momentum"
#property version   "2.61"
#property strict
#property description "XAUUSD fixed 8x8 ladder with Bullet 1 quick-cut, individual BE, audit-corrected basket peak protection, and reconciled flight-recorder telemetry."

#include <Trade/Trade.mqh>

CTrade trade;

input group "Identity"
input string InpTradeSymbol                    = "XAUUSD";
input ulong  InpMagicNumber                    = 2907202622;
input string InpOrderCommentPrefix             = "EVEL261";

input group "Position sizing and hard capital protection"
input double InpFixedLot                       = 0.01;
input int    InpMaximumPositions               = 16;
input double InpMaximumTotalLots               = 0.16;
input double InpEmergencyBasketLossMoney       = 5.00;
input double InpEmergencyBasketLossPercent     = 1.00;
input bool   InpDailyLossEnabledAtStart        = false;
input double InpMaximumDailyLossMoney          = 20.00;
input double InpMaximumDailyLossPercent        = 0.00; // legacy compatibility only; dashboard money limit controls v2.61
input int    InpMaximumSpreadPoints            = 150;
input int    InpSlippagePoints                 = 30;

input group "Fixed ladder geometry"
input int    InpATRPeriod                      = 14;
input int    InpLevelsPerSide                  = 8;
input double InpGridSpacingPrice               = 3.000;
input double InpFixedFallbackPrice             = 2.000;
input bool   InpImmediateRearm                  = true;
input bool   InpRefreshBracketEveryM1Candle    = false;
input int    InpPendingCancelRetryMilliseconds = 250;

input group "Bullet proof and sentinel"
input bool   InpMoveEveryBulletToBreakEven     = true;
input double InpBreakEvenTriggerPrice          = 1.500;
input double InpBreakEvenBufferPrice           = 0.150;
input bool   InpCloseBasketOnNewestLegSL       = true;
input bool   InpUseFirstBulletQuickCut         = true;
input double InpFirstBulletAdverseCutPrice     = 0.750;

input group "Campaign profit target"
input bool   InpProfitTargetEnabledAtStart     = true;
input double InpProfitTargetMoneyAtStart       = 5.00;

input group "Basket peak protection"
input bool   InpBasketPeakProtectionAtStart    = true;
input double InpBasketPeakActivationMoney      = 4.00;
input double InpBasketPeakGivebackMoney        = 1.00;

// Legacy geometry inputs retained only so older set files still load.
input double InpBracketOffsetATR               = 0.0;
input double InpMinimumBracketOffsetPrice      = 0.0;
input double InpFallbackATR                    = 0.0;
input double InpMinimumFallbackPrice           = 0.0;
input double InpFallbackSpreadMultiplier       = 0.0;
input double InpEntrySpacingATR                = 0.0;
input double InpMinimumEntrySpacingPrice       = 0.0;
input double InpSpacingToFallbackRatio         = 1.0;
input int    InpMaximumCampaignEntries         = 16;

input group "Optional natural-mode basket protection"
input bool   InpUseBasketProfitLock            = false;
input int    InpProfitLockMinimumLegs          = 2;
input double InpBasketLockMinimumMoney         = 1.00;
input double InpBasketLockTriggerRiskFraction  = 1.00;
input double InpBasketLockRetainPercent        = 60.0;
input double InpCommissionReservePer001Lot     = 0.08;
input int    InpScanLogSeconds                 = 10;
input int    InpReplayLogSeconds               = 3;

input group "Legacy optional protection inputs (not used in v2.61)"
input bool   InpUseBreakEven                   = false;
input double InpBreakEvenTriggerATR            = 0.60;
input double InpBreakEvenBufferATR             = 0.03;
input bool   InpUseTrailingStop                = false;
input double InpTrailingActivationATR          = 0.90;
input double InpTrailingDistanceATR            = 0.35;
input double InpMinimumTrailStepATR            = 0.08;

input group "Twelve Data telemetry only - never blocks ordinary trades"
input int    InpSignalScoreRequired            = 4;
input int    InpSignalScoreDifference          = 1;
input double InpVelocity1ATR                   = 0.025;
input double InpVelocity3ATR                   = 0.045;
input double InpVelocity10ATR                  = 0.080;
input double InpTickExpansion                  = 1.05;
input double InpAcceleration                   = 1.00;
input int    InpMicroBreakLookbackMilliseconds = 1800;

// Legacy names retained for source compatibility. They do not gate entries in v2.61.
input int    InpSignalHoldMilliseconds         = 0;
input int    InpOppositeSignalHoldMilliseconds = 0;
input double InpOppositeThresholdMultiplier    = 1.00;
input double InpStopLossATR                    = 0.22;
input double InpTakeProfitATR                  = 0.00;
input double InpAddSupportVelocity1ATR         = 0.0;
input double InpAddSupportVelocity3ATR         = 0.0;
input int    InpAddSignalScoreRequired         = 0;
input int    InpAddScoreDifference             = 0;
input double InpMinimumAddMomentumRetention    = 0.0;
input double InpHardFadeVelocityATR            = 999.0;
input bool   InpUseFirstLegFailureExit         = false;
input double InpFirstLegFailureATR             = 0.22;
input bool   InpBankPositiveOnHardFade         = false;
input double InpQuietVelocity1ATR              = 0.0;
input double InpQuietVelocity3ATR              = 0.0;
input int    InpQuietResetMilliseconds         = 0;

input group "Railway connection"
input string InpRailwayBaseUrl                 = "https://YOUR-SERVICE.up.railway.app";
input string InpBotToken                       = "CHANGE-ME";
input int    InpHeartbeatSeconds               = 4;
input int    InpCommandPollSeconds             = 4;
input int    InpWebTimeoutMilliseconds         = 3500;

input group "Operation"
input bool   InpStartAutonomous                = true;
input bool   InpShowPanel                      = true;

#define TICK_BUFFER_SIZE 1024
#define MODIFY_MEMORY_SIZE 128

struct TickSample
{
   ulong  ms;
   double mid;
};

struct MomentumSnapshot
{
   bool   ready;
   double atr;
   double mid;
   double velocity1;
   double velocity3;
   double velocity10;
   double tickRatio;
   double acceleration;
   double bodyATR;
   double microHigh;
   double microLow;
   int    buyScore;
   int    sellScore;
   string direction;
   string reason;
};

enum EngineState
{
   STATE_WARMING = 0,
   STATE_IDLE,
   STATE_ARMED,
   STATE_RUNNING,
   STATE_CANCELLING,
   STATE_PAUSED,
   STATE_EMERGENCY
};

string trade_symbol = "";
int atr_handle = INVALID_HANDLE;
TickSample tick_buffer[TICK_BUFFER_SIZE];
int tick_head = 0;
int tick_count = 0;

MomentumSnapshot momentum;
EngineState engine_state = STATE_WARMING;
string campaign_side = "NONE";
string last_campaign_side = "NONE";
int direction_leg_count = 0;
int buy_leg_count = 0;
int sell_leg_count = 0;
double ladder_anchor_price = 0.0;
datetime last_m1_bar_time = 0;
bool immediate_rearm_pending = true;
bool adding_stopped = false;
int campaign_entries = 0; // unique bullets fired in this campaign
int campaign_buy_bullets_fired = 0;
int campaign_sell_bullets_fired = 0;
int campaign_max_positions = 0;
long campaign_event_sequence = 0;
string next_ladder_reason = "EA START - IMMEDIATE REARM";
datetime campaign_started_at = 0;
double campaign_start_balance = 0.0;
double campaign_peak_floating = 0.0;
double campaign_worst_floating = 0.0;
double campaign_fallback_distance = 0.0;
double campaign_bullet_spacing = 0.0;
bool campaign_profit_target_enabled = true;
double campaign_profit_target_money = 5.00;
int campaign_settings_version = 0;
bool campaign_peak_protection_enabled = true;
double campaign_peak_activation_money = 4.00;
double campaign_peak_giveback_money = 1.00;
bool campaign_peak_protection_armed = false;
double campaign_peak_protection_floor = 0.0;
string campaign_exit_reason = "CAMPAIGN COMPLETE";
bool basket_close_requested = false;
string basket_close_reason = "";
int basket_close_attempts = 0;
ulong newest_position_id = 0;
ulong newest_ticket = 0;
datetime newest_leg_open_time = 0;
double newest_leg_current_profit = 0.0;
double newest_leg_peak_profit = 0.0;
bool newest_leg_sl_exit_detected = false;
bool first_bullet_quick_cut_applied = false;
bool first_bullet_quick_cut_triggered = false;
double first_bullet_quick_cut_sl = 0.0;
double first_leg_entry_price = 0.0;
double first_leg_entry_atr = 0.0;
ulong first_leg_position_id = 0;
double last_fill_velocity_abs = 0.0;
int last_fill_same_score = 0;
int last_fill_opposite_score = 0;
string last_event = "EA starting";

bool local_paused = false;
bool remote_autonomous = true;
bool emergency_stopped = false;
long last_command_id = 0;
string last_command_result = "No command received";

ulong last_trade_request_ms = 0;
ulong last_cancel_request_ms = 0;
ulong last_heartbeat_ms = 0;
ulong last_poll_ms = 0;
ulong heartbeat_sequence = 0;
ulong last_successful_http_ms = 0;
ulong next_http_allowed_ms = 0;
int http_failure_count = 0;
string last_http_status = "Not connected";
string queued_basket_json = "";
#define TELEMETRY_QUEUE_SIZE 2048
string telemetry_endpoints[TELEMETRY_QUEUE_SIZE];
string telemetry_payloads[TELEMETRY_QUEUE_SIZE];
int telemetry_head = 0;
int telemetry_tail = 0;
int telemetry_count = 0;
ulong last_scan_log_ms = 0;
double cached_atr = 0.0;
ulong cached_atr_ms = 0;
double cached_daily_pnl = 0.0;
ulong cached_daily_pnl_ms = 0;
double runtime_fixed_lot = 0.01;
bool runtime_use_equity_scaling = false;
double runtime_equity_per_001 = 1000.0;
int runtime_settings_version = 0;
bool runtime_profit_target_enabled = true;
double runtime_profit_target_money = 5.00;
bool runtime_basket_peak_protection_enabled = true;
double runtime_basket_peak_activation_money = 4.00;
double runtime_basket_peak_giveback_money = 1.00;
bool runtime_daily_loss_enabled = false;
double runtime_daily_loss_money = 20.00;
datetime runtime_daily_loss_reset_at = 0;
long runtime_daily_loss_reset_server_ms = 0;
string campaign_id = "";
string last_reporting_campaign_id = "";
ulong last_replay_log_ms = 0;

#define BULLET_MEMORY_SIZE 64
ulong bullet_position_ids[BULLET_MEMORY_SIZE];
ulong bullet_tickets[BULLET_MEMORY_SIZE];
string bullet_sides[BULLET_MEMORY_SIZE];
string bullet_campaign_ids[BULLET_MEMORY_SIZE];
int bullet_numbers[BULLET_MEMORY_SIZE];
double bullet_entries[BULLET_MEMORY_SIZE];
double bullet_initial_sls[BULLET_MEMORY_SIZE];
double bullet_final_sls[BULLET_MEMORY_SIZE];
double bullet_mfe_price[BULLET_MEMORY_SIZE];
double bullet_mae_price[BULLET_MEMORY_SIZE];
bool bullet_be_active[BULLET_MEMORY_SIZE];
datetime bullet_open_times[BULLET_MEMORY_SIZE];
datetime bullet_be_times[BULLET_MEMORY_SIZE];
int bullet_memory_count = 0;

#define DEAL_MEMORY_SIZE 512
ulong processed_deals[DEAL_MEMORY_SIZE];
int processed_deal_count = 0;

ulong modified_tickets[MODIFY_MEMORY_SIZE];
ulong modified_times[MODIFY_MEMORY_SIZE];
int modified_count = 0;

string PANEL_PREFIX = "EVEL261_";

bool MarkDealProcessed(ulong deal)
{
   if(deal == 0) return false;
   for(int i=0; i<processed_deal_count; i++)
      if(processed_deals[i] == deal) return false;
   if(processed_deal_count < DEAL_MEMORY_SIZE)
      processed_deals[processed_deal_count++] = deal;
   else
   {
      for(int i=1; i<DEAL_MEMORY_SIZE; i++) processed_deals[i-1] = processed_deals[i];
      processed_deals[DEAL_MEMORY_SIZE-1] = deal;
   }
   return true;
}

string SettingsGlobalPrefix()
{
   string key = StringFormat("EVEFL_%I64d_%s_", AccountInfoInteger(ACCOUNT_LOGIN), trade_symbol);
   StringReplace(key, "/", "_");
   StringReplace(key, " ", "_");
   return key;
}

void SaveLocalSettings()
{
   string prefix = SettingsGlobalPrefix();
   GlobalVariableSet(prefix + "READY", 1.0);
   GlobalVariableSet(prefix + "VER", (double)runtime_settings_version);
   GlobalVariableSet(prefix + "TARGET_ON", runtime_profit_target_enabled ? 1.0 : 0.0);
   GlobalVariableSet(prefix + "TARGET_MONEY", runtime_profit_target_money);
   GlobalVariableSet(prefix + "PEAK_ON", runtime_basket_peak_protection_enabled ? 1.0 : 0.0);
   GlobalVariableSet(prefix + "PEAK_AT", runtime_basket_peak_activation_money);
   GlobalVariableSet(prefix + "PEAK_GIVEBACK", runtime_basket_peak_giveback_money);
   GlobalVariableSet(prefix + "DAILY_ON", runtime_daily_loss_enabled ? 1.0 : 0.0);
   GlobalVariableSet(prefix + "DAILY_MONEY", runtime_daily_loss_money);
   GlobalVariableSet(prefix + "DAILY_RESET_MS", (double)runtime_daily_loss_reset_server_ms);
}

void LoadLocalSettings()
{
   string prefix = SettingsGlobalPrefix();
   if(!GlobalVariableCheck(prefix + "READY")) return;
   runtime_settings_version = (int)GlobalVariableGet(prefix + "VER");
   runtime_profit_target_enabled = GlobalVariableGet(prefix + "TARGET_ON") > 0.5;
   double target = GlobalVariableGet(prefix + "TARGET_MONEY");
   if(target > 0.0) runtime_profit_target_money = target;
   runtime_basket_peak_protection_enabled = GlobalVariableGet(prefix + "PEAK_ON") > 0.5;
   double activation = GlobalVariableGet(prefix + "PEAK_AT");
   double giveback = GlobalVariableGet(prefix + "PEAK_GIVEBACK");
   if(activation > 0.0) runtime_basket_peak_activation_money = activation;
   if(giveback > 0.0) runtime_basket_peak_giveback_money = giveback;
   runtime_daily_loss_enabled = GlobalVariableGet(prefix + "DAILY_ON") > 0.5;
   double daily = GlobalVariableGet(prefix + "DAILY_MONEY");
   if(daily > 0.0) runtime_daily_loss_money = daily;
   runtime_daily_loss_reset_server_ms = (long)GlobalVariableGet(prefix + "DAILY_RESET_MS");
}

int OnInit()
{
   trade_symbol = InpTradeSymbol == "" ? _Symbol : InpTradeSymbol;
   if(!SymbolSelect(trade_symbol, true))
   {
      Print("EVE Fixed Ladder v2.61 cannot select symbol ", trade_symbol);
      return INIT_FAILED;
   }

   long margin_mode = AccountInfoInteger(ACCOUNT_MARGIN_MODE);
   if(margin_mode != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
   {
      Alert("EVE Fixed Ladder v2.61 requires a HEDGING demo account.");
      return INIT_FAILED;
   }

   atr_handle = iATR(trade_symbol, PERIOD_M1, MathMax(2, InpATRPeriod));
   if(atr_handle == INVALID_HANDLE)
   {
      Print("EVE Fixed Ladder v2.61 failed to create ATR handle. Error ", GetLastError());
      return INIT_FAILED;
   }

   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(InpSlippagePoints);
   trade.SetTypeFillingBySymbol(trade_symbol);
   trade.SetMarginMode();

   remote_autonomous = InpStartAutonomous;
   runtime_fixed_lot = InpFixedLot;
   runtime_profit_target_enabled = InpProfitTargetEnabledAtStart;
   runtime_profit_target_money = MathMax(0.01, InpProfitTargetMoneyAtStart);
   runtime_basket_peak_protection_enabled = InpBasketPeakProtectionAtStart;
   runtime_basket_peak_activation_money = MathMax(0.01, InpBasketPeakActivationMoney);
   runtime_basket_peak_giveback_money = MathMax(0.01, InpBasketPeakGivebackMoney);
   runtime_daily_loss_enabled = InpDailyLossEnabledAtStart;
   runtime_daily_loss_money = MathMax(0.01, InpMaximumDailyLossMoney);
   runtime_daily_loss_reset_at = 0;
   runtime_daily_loss_reset_server_ms = 0;
   LoadLocalSettings();
   SaveLocalSettings();
   last_m1_bar_time = iTime(trade_symbol, PERIOD_M1, 0);
   immediate_rearm_pending = true;
   next_ladder_reason = "EA START - IMMEDIATE REARM";
   EventSetTimer(1);
   if(InpShowPanel) CreatePanel();
   last_event = "v2.61 ready: $5 target ON and basket peak protection ON at +$4.00 with $1.00 maximum giveback";
   Print(last_event);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   if(atr_handle != INVALID_HANDLE) IndicatorRelease(atr_handle);
   DeletePanel();
}

void OnTick()
{
   MqlTick tick;
   if(!SymbolInfoTick(trade_symbol, tick)) return;
   RecordTick(tick);
   BuildMomentum(tick, momentum);
   UpdateBulletMetrics(tick);
   UpdateNewestLegStats();
   ManageFirstBulletQuickCut(tick);
   ManageIndividualProtection(tick);
   ManageBasketProtection(tick);
   EnforceCapitalProtection();
   RunEngine(tick);
   if(InpShowPanel) UpdatePanel();
}

void OnTimer()
{
   MaybeQueueScanReport();
   MaybeQueueReplaySnapshot();
   ProcessRailway();
   if(InpShowPanel) UpdatePanel();
}

void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD || trans.deal == 0) return;
   if(!HistoryDealSelect(trans.deal)) return;
   if(HistoryDealGetString(trans.deal, DEAL_SYMBOL) != trade_symbol) return;
   if((ulong)HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != InpMagicNumber) return;
   if(!MarkDealProcessed(trans.deal))
   {
      PrintFormat("EVE Fixed Ladder v2.61 ignored duplicate deal callback %I64u", trans.deal);
      return;
   }

   ENUM_DEAL_ENTRY entry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
   ENUM_DEAL_TYPE type = (ENUM_DEAL_TYPE)HistoryDealGetInteger(trans.deal, DEAL_TYPE);
   ENUM_DEAL_REASON reason = (ENUM_DEAL_REASON)HistoryDealGetInteger(trans.deal, DEAL_REASON);
   ulong position_id = (ulong)HistoryDealGetInteger(trans.deal, DEAL_POSITION_ID);
   ulong position_ticket = trans.position > 0 ? trans.position : position_id;
   double price = HistoryDealGetDouble(trans.deal, DEAL_PRICE);
   double volume = HistoryDealGetDouble(trans.deal, DEAL_VOLUME);

   if(entry == DEAL_ENTRY_IN || entry == DEAL_ENTRY_INOUT)
   {
      string side = type == DEAL_TYPE_BUY ? "BUY" : "SELL";
      bool first_entry = campaign_started_at <= 0;
      if(first_entry) StartCampaign(side);

      int existing_idx = FindBullet(position_id);
      if(existing_idx >= 0)
      {
         last_event = StringFormat("Duplicate OPEN callback ignored for position %I64u", position_id);
         return;
      }

      int bullet_number = side == "BUY" ? campaign_buy_bullets_fired + 1 : campaign_sell_bullets_fired + 1;
      double initial_sl = side == "BUY" ? price - FallbackDistance() : price + FallbackDistance();
      if(PositionSelectByTicket(position_ticket)) initial_sl = PositionGetDouble(POSITION_SL);
      RegisterBullet(position_id, position_ticket, side, bullet_number, price, initial_sl);

      if(side == "BUY") campaign_buy_bullets_fired++;
      else campaign_sell_bullets_fired++;
      campaign_entries = bullet_memory_count;
      SyncCampaignCountersFromBulletMemory();
      buy_leg_count = CountPositionsSide("BUY");
      sell_leg_count = CountPositionsSide("SELL");
      direction_leg_count = CountOurPositions();
      campaign_max_positions = (int)MathMax(campaign_max_positions, direction_leg_count);
      campaign_side = RecordedCampaignSide();
      last_campaign_side = campaign_side;

      newest_position_id = position_id;
      newest_ticket = position_ticket;
      newest_leg_open_time = TimeCurrent();
      newest_leg_current_profit = 0.0;
      newest_leg_peak_profit = 0.0;

      if(first_entry)
      {
         first_leg_entry_price = price;
         first_leg_entry_atr = momentum.atr > 0.0 ? momentum.atr : CurrentATR();
         first_leg_position_id = position_id;
         campaign_fallback_distance = FallbackDistance();
         campaign_bullet_spacing = BulletSpacing();
      }

      last_fill_velocity_abs = MathAbs(momentum.velocity1);
      last_fill_same_score = side == "BUY" ? momentum.buyScore : momentum.sellScore;
      last_fill_opposite_score = side == "BUY" ? momentum.sellScore : momentum.buyScore;

      QueueLegReportDetailed("OPEN", side, position_ticket, position_id, bullet_number, volume, price, initial_sl, initial_sl, false, 0, 0.0, 0.0, 0.0,
                             first_entry ? "FIRST FIXED-LADDER BULLET" : "PRICE TRIGGERED FIXED LADDER LEVEL");
      QueueSignalReport(first_entry ? "SCOUT_FIRED" : "BULLET_FIRED", side, price,
                        StringFormat("Unique fixed-ladder bullet %d fired; total unique bullets %d", bullet_number, campaign_entries));
      last_event = StringFormat("%s bullet %d fired at %.2f; unique campaign bullets %d; newest bullet is sentinel", side, bullet_number, price, campaign_entries);
   }
   else if(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_OUT_BY)
   {
      string position_side = type == DEAL_TYPE_SELL ? "BUY" : "SELL";
      double profit = HistoryDealGetDouble(trans.deal, DEAL_PROFIT) +
                      HistoryDealGetDouble(trans.deal, DEAL_COMMISSION) +
                      HistoryDealGetDouble(trans.deal, DEAL_SWAP) +
                      HistoryDealGetDouble(trans.deal, DEAL_FEE);
      int idx = FindBullet(position_id);
      int bullet_number = idx >= 0 ? bullet_numbers[idx] : 0;
      bool be_active = idx >= 0 ? bullet_be_active[idx] : false;
      double initial_sl = idx >= 0 ? bullet_initial_sls[idx] : 0.0;
      double final_sl = idx >= 0 ? bullet_final_sls[idx] : 0.0;
      double mfe = idx >= 0 ? bullet_mfe_price[idx] : 0.0;
      double mae = idx >= 0 ? bullet_mae_price[idx] : 0.0;
      int time_to_be = idx >= 0 && bullet_be_times[idx] > 0 ? (int)(bullet_be_times[idx] - bullet_open_times[idx]) : 0;
      bool was_newest = position_id > 0 && position_id == newest_position_id;

      string close_reason = DealReasonText(reason);
      bool first_quick_cut_exit = !be_active &&
                                  position_id == first_leg_position_id &&
                                  (first_bullet_quick_cut_applied || first_bullet_quick_cut_triggered);
      bool first_quick_cut_stop = reason == DEAL_REASON_SL && first_quick_cut_exit;
      if(reason == DEAL_REASON_SL)
         close_reason = be_active ? "BE PROTECTED STOP - BULLET ONLY" :
                        (first_quick_cut_stop ? "FIRST BULLET QUICK CUT STOP" : "INITIAL STOP LOSS");
      else if(first_bullet_quick_cut_triggered)
         close_reason = "FIRST BULLET QUICK CUT MARKET EXIT";

      // Only an unprotected newest bullet can kill the complete campaign.
      // Once any bullet, including Bullet 1, earns BE protection at +1.500,
      // its protected stop closes that bullet only and the remaining campaign continues.
      bool newest_failed_before_halfway = was_newest && InpCloseBasketOnNewestLegSL && reason == DEAL_REASON_SL && !be_active;
      if(newest_failed_before_halfway)
      {
         newest_leg_sl_exit_detected = true;
         basket_close_reason = first_quick_cut_stop
            ? StringFormat("FIRST BULLET QUICK CUT %.3f ADVERSE - CLOSE FULL CAMPAIGN", InpFirstBulletAdverseCutPrice)
            : "NEWEST BULLET FAILED BEFORE HALFWAY - CLOSE FULL CAMPAIGN";
         campaign_exit_reason = basket_close_reason;
         adding_stopped = true;
      }

      QueueLegReportDetailed("CLOSE", position_side, position_ticket, position_id, bullet_number, volume, price, initial_sl, final_sl, be_active, time_to_be, mfe, mae, profit, close_reason);

      buy_leg_count = CountPositionsSide("BUY");
      sell_leg_count = CountPositionsSide("SELL");
      direction_leg_count = CountOurPositions();
      if(newest_failed_before_halfway)
         last_event = first_quick_cut_stop
            ? StringFormat("First %s bullet hit quick-cut %.3f; closing campaign and rearming", position_side, InpFirstBulletAdverseCutPrice)
            : StringFormat("Newest %s bullet %d failed before halfway; closing every position and pending order", position_side, bullet_number);
      else if(was_newest && reason == DEAL_REASON_SL && be_active)
      {
         if(direction_leg_count == 0)
            campaign_exit_reason = "LAST LIVE BULLET CLOSED AT BE PROTECTION";
         last_event = StringFormat("Newest %s bullet %d hit BE protection; only that bullet closed and the remaining campaign continues", position_side, bullet_number);
      }
      else
         last_event = StringFormat("%s bullet %d closed %.2f by %s", position_side, bullet_number, profit, close_reason);
   }
}

void OnChartEvent(const int id,const long &lparam,const double &dparam,const string &sparam)
{
   if(id != CHARTEVENT_OBJECT_CLICK) return;
   if(sparam == PANEL_PREFIX + "PAUSE")
   {
      local_paused = !local_paused;
      if(local_paused) CancelAllPending("manual pause");
      last_event = local_paused ? "EA paused; open positions remain protected" : "EA resumed";
   }
   else if(sparam == PANEL_PREFIX + "CLOSE")
   {
      RequestBasketClose("MANUAL CLOSE");
   }
   else if(sparam == PANEL_PREFIX + "STOP")
   {
      emergency_stopped = true;
      local_paused = true;
      RequestBasketClose("EMERGENCY STOP");
      last_event = "EMERGENCY STOP active";
   }
}

void RecordTick(const MqlTick &tick)
{
   tick_buffer[tick_head].ms = GetTickCount64();
   tick_buffer[tick_head].mid = (tick.bid + tick.ask) * 0.5;
   tick_head = (tick_head + 1) % TICK_BUFFER_SIZE;
   if(tick_count < TICK_BUFFER_SIZE) tick_count++;
}

int BufferIndexFromNewest(int offset)
{
   int index = tick_head - 1 - offset;
   while(index < 0) index += TICK_BUFFER_SIZE;
   return index % TICK_BUFFER_SIZE;
}

bool PriceAtAge(ulong age_ms, double &price)
{
   if(tick_count < 2) return false;
   ulong target = GetTickCount64() > age_ms ? GetTickCount64() - age_ms : 0;
   for(int offset=0; offset<tick_count; offset++)
   {
      int index = BufferIndexFromNewest(offset);
      if(tick_buffer[index].ms <= target)
      {
         price = tick_buffer[index].mid;
         return true;
      }
   }
   return false;
}

int CountTicksSince(ulong age_ms)
{
   ulong target = GetTickCount64() > age_ms ? GetTickCount64() - age_ms : 0;
   int count = 0;
   for(int offset=0; offset<tick_count; offset++)
   {
      int index = BufferIndexFromNewest(offset);
      if(tick_buffer[index].ms < target) break;
      count++;
   }
   return count;
}

bool MicroRange(int lookback_ms, double &high, double &low)
{
   if(tick_count < 5) return false;
   ulong now = GetTickCount64();
   ulong target = now > (ulong)lookback_ms ? now - (ulong)lookback_ms : 0;
   high = -1.0e100;
   low = 1.0e100;
   int used = 0;
   for(int offset=1; offset<tick_count; offset++)
   {
      int index = BufferIndexFromNewest(offset);
      if(tick_buffer[index].ms < target) break;
      high = MathMax(high, tick_buffer[index].mid);
      low = MathMin(low, tick_buffer[index].mid);
      used++;
   }
   return used >= 3;
}

double CurrentATR()
{
   ulong now = GetTickCount64();
   if(cached_atr > 0.0 && cached_atr_ms > 0 && now - cached_atr_ms < 250) return cached_atr;
   if(atr_handle == INVALID_HANDLE) return cached_atr;
   double buffer[2];
   int copied = CopyBuffer(atr_handle, 0, 0, 2, buffer);
   if(copied < 1) return cached_atr;
   double value = copied > 1 && buffer[1] > 0.0 ? buffer[1] : buffer[0];
   if(value > 0.0)
   {
      cached_atr = value;
      cached_atr_ms = now;
   }
   return cached_atr;
}

void BuildMomentum(const MqlTick &tick, MomentumSnapshot &out)
{
   out.ready = false;
   out.atr = CurrentATR();
   out.mid = (tick.bid + tick.ask) * 0.5;
   out.buyScore = 0;
   out.sellScore = 0;
   out.direction = "NONE";
   out.reason = "warming";
   if(out.atr <= 0.0 || tick_count < 20) return;

   double p1, p3, p10;
   if(!PriceAtAge(1000, p1) || !PriceAtAge(3000, p3) || !PriceAtAge(10000, p10)) return;
   if(!MicroRange(InpMicroBreakLookbackMilliseconds, out.microHigh, out.microLow)) return;

   out.velocity1 = (out.mid - p1) / out.atr;
   out.velocity3 = (out.mid - p3) / out.atr;
   out.velocity10 = (out.mid - p10) / out.atr;
   int ticks1 = CountTicksSince(1000);
   int ticks10 = CountTicksSince(10000);
   double normal_per_second = MathMax(1.0, (double)ticks10 / 10.0);
   out.tickRatio = (double)ticks1 / normal_per_second;
   double baseline = MathMax(0.004, MathAbs(out.velocity3) / 3.0);
   out.acceleration = MathAbs(out.velocity1) / baseline;
   double open = iOpen(trade_symbol, PERIOD_M1, 0);
   out.bodyATR = open > 0.0 ? (out.mid - open) / out.atr : 0.0;

   if(out.velocity1 >= InpVelocity1ATR) out.buyScore++;
   if(out.velocity3 >= InpVelocity3ATR) out.buyScore++;
   if(out.velocity10 >= InpVelocity10ATR) out.buyScore++;
   if(out.tickRatio >= InpTickExpansion) out.buyScore++;
   if(out.acceleration >= InpAcceleration && out.velocity1 > 0.0) out.buyScore++;
   if(out.mid >= out.microHigh) out.buyScore++;
   if(out.bodyATR >= 0.08) out.buyScore++;

   if(out.velocity1 <= -InpVelocity1ATR) out.sellScore++;
   if(out.velocity3 <= -InpVelocity3ATR) out.sellScore++;
   if(out.velocity10 <= -InpVelocity10ATR) out.sellScore++;
   if(out.tickRatio >= InpTickExpansion) out.sellScore++;
   if(out.acceleration >= InpAcceleration && out.velocity1 < 0.0) out.sellScore++;
   if(out.mid <= out.microLow) out.sellScore++;
   if(out.bodyATR <= -0.08) out.sellScore++;

   if(out.buyScore >= InpSignalScoreRequired && out.buyScore - out.sellScore >= InpSignalScoreDifference)
      out.direction = "BUY";
   else if(out.sellScore >= InpSignalScoreRequired && out.sellScore - out.buyScore >= InpSignalScoreDifference)
      out.direction = "SELL";

   out.reason = StringFormat("BUY %d/7 SELL %d/7 v1 %.3f v3 %.3f ticks x%.2f", out.buyScore, out.sellScore, out.velocity1, out.velocity3, out.tickRatio);
   out.ready = true;
}

bool SpreadOkay()
{
   MqlTick tick;
   if(!SymbolInfoTick(trade_symbol, tick)) return false;
   double point = SymbolInfoDouble(trade_symbol, SYMBOL_POINT);
   if(point <= 0.0) return false;
   double spread_points = (tick.ask - tick.bid) / point;
   return spread_points <= InpMaximumSpreadPoints;
}

double CurrentSpreadPoints()
{
   MqlTick tick;
   if(!SymbolInfoTick(trade_symbol, tick)) return 0.0;
   double point = SymbolInfoDouble(trade_symbol, SYMBOL_POINT);
   return point > 0.0 ? (tick.ask - tick.bid) / point : 0.0;
}

string EntryBlockReason()
{
   if(local_paused) return "PAUSED - NO NEW LADDER";
   if(emergency_stopped) return "EMERGENCY STOP ACTIVE";
   if(!remote_autonomous) return "AUTONOMOUS DISABLED";
   if(!TerminalInfoInteger(TERMINAL_CONNECTED)) return "MT5 TERMINAL DISCONNECTED";
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)) return "TERMINAL TRADING NOT ALLOWED";
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED)) return "EA ALGO TRADING NOT ALLOWED";
   if(!SpreadOkay()) return StringFormat("SPREAD %.1f ABOVE HARD LIMIT %d", CurrentSpreadPoints(), InpMaximumSpreadPoints);
   if(DailyLossBlocked()) return "DAILY LOSS HARD LIMIT REACHED";
   return "";
}

bool NewEntriesAllowed()
{
   return EntryBlockReason() == "";
}

void RunEngine(const MqlTick &tick)
{
   int positions = CountOurPositions();

   // Trade-transaction callbacks only mark a newest unprotected SL failure.
   // The engine performs the basket close so the banking decision and every
   // remaining close request are recorded through one consistent path.
   if(newest_leg_sl_exit_detected && !basket_close_requested)
   {
      newest_leg_sl_exit_detected = false;
      RequestBasketClose(basket_close_reason == "" ? "NEWEST BULLET FAILED BEFORE HALFWAY - CLOSE FULL CAMPAIGN" : basket_close_reason);
      positions = CountOurPositions();
   }

   if(basket_close_requested)
   {
      engine_state = STATE_CANCELLING;
      adding_stopped = true;
      CancelAllPending(basket_close_reason);
      if(positions > 0)
      {
         basket_close_attempts++;
         CloseAllPositions(basket_close_reason);
      }
      if(CountOurPositions() == 0 && CountOurPending() == 0 && campaign_started_at > 0)
         FinishCampaign();
      return;
   }

   if(emergency_stopped)
   {
      engine_state = STATE_EMERGENCY;
      CancelAllPending("emergency state");
      if(positions > 0) RequestBasketClose("EMERGENCY STOP");
      return;
   }

   if(local_paused || !remote_autonomous)
   {
      engine_state = STATE_PAUSED;
      CancelAllPending("paused");
      return;
   }

   if(positions > 0 && campaign_started_at <= 0)
      RecoverCampaignFromLivePositions();

   if(positions > 0)
   {
      engine_state = STATE_RUNNING;
      UpdateCampaignStats();
      buy_leg_count = CountPositionsSide("BUY");
      sell_leg_count = CountPositionsSide("SELL");
      campaign_side = RecordedCampaignSide();
      direction_leg_count = positions;
      campaign_max_positions = (int)MathMax(campaign_max_positions, positions);
      UpdateNewestLegStats();
      return;
   }

   if(campaign_started_at > 0)
   {
      CancelAllPending("campaign flat - rebuild fresh fixed ladder");
      if(CountOurPending() == 0) FinishCampaign();
      return;
   }

   engine_state = STATE_IDLE;
   datetime current_bar = iTime(trade_symbol, PERIOD_M1, 0);
   bool new_bar = current_bar > 0 && current_bar != last_m1_bar_time;
   if(new_bar) last_m1_bar_time = current_bar;

   string block_reason = EntryBlockReason();
   if(block_reason != "")
   {
      CancelAllPending(block_reason);
      last_event = block_reason;
      return;
   }

   bool ladder_missing = CountOurPending() < MathMax(2, InpLevelsPerSide * 2);
   bool optional_m1_refresh = InpRefreshBracketEveryM1Candle && new_bar;
   if(immediate_rearm_pending || ladder_missing || optional_m1_refresh)
   {
      string arm_reason = "LADDER MISSING - REPAIR";
      if(immediate_rearm_pending)
         arm_reason = next_ladder_reason == "" ? "IMMEDIATE REARM" : next_ladder_reason;
      else if(optional_m1_refresh)
         arm_reason = "OPTIONAL M1 REFRESH";
      bool armed = ArmFreshTwoSidedBracket(arm_reason);
      immediate_rearm_pending = !armed;
   }
   else
      engine_state = STATE_ARMED;
}

int CountPositionsSide(string side)
{
   int count = 0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket) || !IsOurSelectedPosition()) continue;
      ENUM_POSITION_TYPE type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      if((side == "BUY" && type == POSITION_TYPE_BUY) || (side == "SELL" && type == POSITION_TYPE_SELL)) count++;
   }
   return count;
}

bool HasPendingSide(string side)
{
   for(int i=OrdersTotal()-1; i>=0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0 || !OrderSelect(ticket) || !IsOurSelectedOrder()) continue;
      ENUM_ORDER_TYPE type = (ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
      if((side == "BUY" && type == ORDER_TYPE_BUY_STOP) || (side == "SELL" && type == ORDER_TYPE_SELL_STOP)) return true;
   }
   return false;
}

void RecoverCampaignFromLivePositions()
{
   int buys = CountPositionsSide("BUY");
   int sells = CountPositionsSide("SELL");
   if(buys <= 0 && sells <= 0) return;
   StartCampaign(buys > 0 && sells > 0 ? "MIXED" : (buys > 0 ? "BUY" : "SELL"));
   buy_leg_count = buys;
   sell_leg_count = sells;
   campaign_side = buys > 0 && sells > 0 ? "MIXED" : (buys > 0 ? "BUY" : "SELL");
   RebuildBulletMemoryFromLivePositions();
   campaign_buy_bullets_fired = buys;
   campaign_sell_bullets_fired = sells;
   campaign_entries = bullet_memory_count;
   direction_leg_count = CountOurPositions();
   UpdateNewestLegStats();
   last_event = "Recovered live campaign after restart; counters rebuilt from unique position identifiers";
}


bool ClosePositionsSide(string side, string reason)
{
   bool all_closed = true;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket) || !IsOurSelectedPosition()) continue;
      ENUM_POSITION_TYPE type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      bool matches = (side == "BUY" && type == POSITION_TYPE_BUY) || (side == "SELL" && type == POSITION_TYPE_SELL);
      if(!matches) continue;
      ResetLastError();
      if(!trade.PositionClose(ticket, InpSlippagePoints))
      {
         all_closed = false;
         last_event = StringFormat("Flip close failed %I64u: %u %s", ticket, trade.ResultRetcode(), trade.ResultRetcodeDescription());
      }
   }
   return all_closed;
}

bool ArmFreshTwoSidedBracket(string reason)
{
   CancelAllPending("rebuild fixed two-sided ladder: " + reason);
   if(CountOurPending() > 0) return false;

   MqlTick tick;
   if(!SymbolInfoTick(trade_symbol, tick))
   {
      last_event = "Cannot read broker price to anchor ladder";
      return false;
   }

   ladder_anchor_price = NormalisePrice((tick.bid + tick.ask) * 0.5);
   campaign_id = BuildCampaignId("LADDER");
   campaign_event_sequence = 0;
   int levels = (int)MathMax(1, MathMin(50, InpLevelsPerSide));
   bool all_ok = true;
   int placed = 0;
   for(int level=1; level<=levels; level++)
   {
      if(PlaceBulletStop("BUY", "FIXED_LADDER", level, reason)) placed++; else all_ok = false;
      if(PlaceBulletStop("SELL", "FIXED_LADDER", level, reason)) placed++; else all_ok = false;
   }

   engine_state = placed >= 2 ? STATE_ARMED : STATE_CANCELLING;
   if(placed >= 2)
   {
      last_event = StringFormat("Fixed ladder armed: %d BUY STOPs + %d SELL STOPs, spacing %.3f, lot %.2f | %s", levels, levels, BulletSpacing(), EffectiveLot(), reason);
      QueueLadderReport(reason);
      next_ladder_reason = "";
   }
   else
      last_event = "Fixed ladder could not be armed";
   return all_ok && placed == levels * 2;
}


void EnsureCampaignPendings()
{
   // Fixed at campaign start. Never slide and never cancel the opposite ladder.
}



void StartCampaign(string side)
{
   if(campaign_id == "")
   {
      campaign_id = BuildCampaignId(side);
      campaign_event_sequence = 0;
   }
   ResetBulletTracking();
   campaign_side = side;
   last_campaign_side = side;
   campaign_started_at = TimeCurrent();
   campaign_start_balance = AccountInfoDouble(ACCOUNT_BALANCE);
   campaign_peak_floating = BasketFloatingProfit();
   campaign_worst_floating = campaign_peak_floating;
   campaign_fallback_distance = FallbackDistance();
   campaign_bullet_spacing = MathMax(BulletSpacing(), campaign_fallback_distance * InpSpacingToFallbackRatio);
   campaign_profit_target_enabled = runtime_profit_target_enabled;
   campaign_profit_target_money = MathMax(0.01, runtime_profit_target_money);
   campaign_settings_version = runtime_settings_version;
   campaign_peak_protection_enabled = runtime_basket_peak_protection_enabled;
   campaign_peak_activation_money = MathMax(0.01, runtime_basket_peak_activation_money);
   campaign_peak_giveback_money = MathMax(0.01, runtime_basket_peak_giveback_money);
   campaign_peak_protection_armed = false;
   campaign_peak_protection_floor = 0.0;
   campaign_exit_reason = "CAMPAIGN COMPLETE";
   basket_close_requested = false;
   basket_close_reason = "";
   basket_close_attempts = 0;
   newest_leg_sl_exit_detected = false;
   first_bullet_quick_cut_applied = false;
   first_bullet_quick_cut_triggered = false;
   first_bullet_quick_cut_sl = 0.0;
   first_leg_entry_price = 0.0;
   first_leg_entry_atr = 0.0;
   first_leg_position_id = 0;
   newest_position_id = 0;
   newest_ticket = 0;
   newest_leg_open_time = 0;
   newest_leg_current_profit = 0.0;
   newest_leg_peak_profit = 0.0;
   last_fill_velocity_abs = 0.0;
   last_fill_same_score = 0;
   last_fill_opposite_score = 0;
   adding_stopped = false;
   direction_leg_count = 0;
   buy_leg_count = 0;
   sell_leg_count = 0;
   campaign_entries = 0;
   campaign_buy_bullets_fired = 0;
   campaign_sell_bullets_fired = 0;
   campaign_max_positions = 0;
   engine_state = STATE_RUNNING;
}


void UpdateCampaignStats()
{
   double floating = BasketFloatingProfit();
   campaign_peak_floating = MathMax(campaign_peak_floating, floating);
   campaign_worst_floating = MathMin(campaign_worst_floating, floating);
}

void FinishCampaign()
{
   double realised = CampaignRealisedProfit();
   string finished_side = RecordedCampaignSide();
   if(finished_side == "NONE") finished_side = last_campaign_side;
   string finished_reason = campaign_exit_reason;
   QueueBasketReport(finished_side, realised);
   last_reporting_campaign_id = campaign_id;
   last_event = StringFormat("%s campaign finished %.2f by %s; rearming immediately", finished_side, realised, finished_reason);
   next_ladder_reason = "CAMPAIGN COMPLETE - " + finished_reason;
   campaign_side = "NONE";
   campaign_id = "";
   // Keep the finished bullet map until the next campaign starts so delayed
   // close callbacks retain the correct campaign ID. StartCampaign clears it.
   campaign_entries = 0;
   campaign_buy_bullets_fired = 0;
   campaign_sell_bullets_fired = 0;
   direction_leg_count = 0;
   buy_leg_count = 0;
   sell_leg_count = 0;
   ladder_anchor_price = 0.0;
   campaign_started_at = 0;
   campaign_start_balance = 0.0;
   campaign_peak_floating = 0.0;
   campaign_worst_floating = 0.0;
   campaign_fallback_distance = 0.0;
   campaign_bullet_spacing = 0.0;
   campaign_profit_target_enabled = runtime_profit_target_enabled;
   campaign_profit_target_money = runtime_profit_target_money;
   campaign_settings_version = runtime_settings_version;
   campaign_peak_protection_enabled = runtime_basket_peak_protection_enabled;
   campaign_peak_activation_money = runtime_basket_peak_activation_money;
   campaign_peak_giveback_money = runtime_basket_peak_giveback_money;
   campaign_peak_protection_armed = false;
   campaign_peak_protection_floor = 0.0;
   campaign_exit_reason = "CAMPAIGN COMPLETE";
   basket_close_requested = false;
   basket_close_reason = "";
   basket_close_attempts = 0;
   newest_leg_sl_exit_detected = false;
   first_bullet_quick_cut_applied = false;
   first_bullet_quick_cut_triggered = false;
   first_bullet_quick_cut_sl = 0.0;
   first_leg_entry_price = 0.0;
   first_leg_entry_atr = 0.0;
   first_leg_position_id = 0;
   newest_position_id = 0;
   newest_ticket = 0;
   newest_leg_open_time = 0;
   newest_leg_current_profit = 0.0;
   newest_leg_peak_profit = 0.0;
   last_fill_velocity_abs = 0.0;
   last_fill_same_score = 0;
   last_fill_opposite_score = 0;
   adding_stopped = false;
   campaign_max_positions = 0;
   immediate_rearm_pending = InpImmediateRearm;
   engine_state = STATE_IDLE;
}


bool CampaignCanAdd()
{
   int positions = CountOurPositions();
   if(positions >= InpMaximumPositions) return false;
   if(campaign_entries >= InpMaximumCampaignEntries) return false;
   double lots = OurTotalLots();
   if(InpMaximumTotalLots > 0.0 && lots + EffectiveLot() > InpMaximumTotalLots + 0.000001) return false;
   return true;
}

double CurrentSpreadPrice()
{
   MqlTick tick;
   if(!SymbolInfoTick(trade_symbol, tick)) return 0.0;
   return MathMax(0.0, tick.ask - tick.bid);
}

double FallbackDistance()
{
   double point = SymbolInfoDouble(trade_symbol, SYMBOL_POINT);
   double broker_min = BrokerMinimumDistancePrice() + point * 2.0;
   return MathMax(MathMax(point * 10.0, InpFixedFallbackPrice), broker_min);
}

double BulletSpacing()
{
   double point = SymbolInfoDouble(trade_symbol, SYMBOL_POINT);
   double broker_min = BrokerMinimumDistancePrice() + point * 2.0;
   return MathMax(MathMax(point * 10.0, InpGridSpacingPrice), broker_min);
}

double BracketOffset()
{
   return BulletSpacing();
}

bool PlaceBulletStop(string side, string role, int leg_number, string reason)
{
   if(side != "BUY" && side != "SELL") return false;
   if(leg_number < 1) return false;

   MqlTick tick;
   if(!SymbolInfoTick(trade_symbol, tick)) return false;
   double spacing = BulletSpacing();
   double fallback = FallbackDistance();
   if(ladder_anchor_price <= 0.0)
      ladder_anchor_price = NormalisePrice((tick.bid + tick.ask) * 0.5);

   double entry = side == "BUY"
      ? ladder_anchor_price + spacing * leg_number
      : ladder_anchor_price - spacing * leg_number;

   double min_distance = BrokerMinimumDistancePrice() + SymbolInfoDouble(trade_symbol, SYMBOL_POINT) * 2.0;
   if(side == "BUY") entry = MathMax(entry, tick.ask + min_distance);
   else entry = MathMin(entry, tick.bid - min_distance);
   entry = NormalisePrice(entry);

   double sl = NormalisePrice(side == "BUY" ? entry - fallback : entry + fallback);
   double volume = EffectiveLot();
   string comment = StringFormat("%s-%s-%02d", InpOrderCommentPrefix, side, leg_number);

   ResetLastError();
   bool submitted = side == "BUY"
      ? trade.BuyStop(volume, entry, trade_symbol, sl, 0.0, ORDER_TIME_GTC, 0, comment)
      : trade.SellStop(volume, entry, trade_symbol, sl, 0.0, ORDER_TIME_GTC, 0, comment);
   uint code = trade.ResultRetcode();
   bool accepted = submitted && IsAcceptedTradeRetcode(code);
   if(!accepted)
   {
      last_event = StringFormat("%s ladder level %d rejected %u: %s", side, leg_number, code, trade.ResultRetcodeDescription());
      Print("EVE Fixed Ladder v2.61 ", last_event, " MQL=", GetLastError());
      QueueOrderReport("REJECTED", role, side == "BUY" ? "BUY_STOP" : "SELL_STOP", leg_number, 0, volume, entry, last_event);
      return false;
   }

   ulong order_ticket = trade.ResultOrder();
   QueueOrderReport("PLACED", role, side == "BUY" ? "BUY_STOP" : "SELL_STOP", leg_number, order_ticket, volume, entry,
                    StringFormat("%s | fixed spacing %.3f | fixed fallback %.3f | level %d", reason, spacing, fallback, leg_number));
   return true;
}

bool NewestFallbackReached(const MqlTick &tick)
{
   if(newest_ticket == 0 || !PositionSelectByTicket(newest_ticket)) return false;
   if(!IsOurSelectedPosition()) return false;
   ENUM_POSITION_TYPE type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
   double sl = PositionGetDouble(POSITION_SL);
   if(sl <= 0.0) return false;
   double point = SymbolInfoDouble(trade_symbol, SYMBOL_POINT);
   if(type == POSITION_TYPE_BUY) return tick.bid <= sl + point * 0.25;
   return tick.ask >= sl - point * 0.25;
}

bool IsAcceptedTradeRetcode(uint code)
{
   return code == TRADE_RETCODE_DONE || code == TRADE_RETCODE_PLACED || code == TRADE_RETCODE_DONE_PARTIAL || code == TRADE_RETCODE_NO_CHANGES;
}

bool CancelAllPending(string reason)
{
   bool all_clear = true;
   ulong now = GetTickCount64();
   if(last_cancel_request_ms > 0 && now - last_cancel_request_ms < (ulong)MathMax(100, InpPendingCancelRetryMilliseconds))
      return CountOurPending() == 0;

   for(int i=OrdersTotal()-1; i>=0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0 || !OrderSelect(ticket)) continue;
      if(!IsOurSelectedOrder()) continue;

      ENUM_ORDER_STATE state = (ENUM_ORDER_STATE)OrderGetInteger(ORDER_STATE);
      if(state != ORDER_STATE_PLACED && state != ORDER_STATE_PARTIAL && state != ORDER_STATE_STARTED) continue;

      if(OrderInsideFreezeZone())
      {
         all_clear = false;
         last_event = "Pending order entered broker freeze zone; cancellation deferred and any fill will remain protected";
         continue;
      }

      ENUM_ORDER_TYPE order_type = (ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
      double order_volume = OrderGetDouble(ORDER_VOLUME_CURRENT);
      double order_price = OrderGetDouble(ORDER_PRICE_OPEN);
      string order_type_text = order_type == ORDER_TYPE_BUY_STOP ? "BUY_STOP" : "SELL_STOP";
      last_cancel_request_ms = now;
      ResetLastError();
      bool submitted = trade.OrderDelete(ticket);
      uint code = trade.ResultRetcode();
      if(submitted && IsAcceptedTradeRetcode(code))
      {
         QueueOrderReport("CANCELLED", "CONTINUATION", order_type_text, 0, ticket, order_volume, order_price, reason);
         continue;
      }

      if(!OrderSelect(ticket)) continue;
      all_clear = false;
      last_event = StringFormat("Cancel deferred for order %I64u: %u %s", ticket, code, trade.ResultRetcodeDescription());
      Print("EVE Fixed Ladder v2.61 ", last_event, " reason=", reason, " MQL=", GetLastError());
   }
   return all_clear && CountOurPending() == 0;
}

bool OrderInsideFreezeZone()
{
   MqlTick tick;
   if(!SymbolInfoTick(trade_symbol, tick)) return false;
   double point = SymbolInfoDouble(trade_symbol, SYMBOL_POINT);
   double freeze = (double)SymbolInfoInteger(trade_symbol, SYMBOL_TRADE_FREEZE_LEVEL) * point;
   if(freeze <= 0.0) return false;
   ENUM_ORDER_TYPE type = (ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
   double price = OrderGetDouble(ORDER_PRICE_OPEN);
   double reference = type == ORDER_TYPE_BUY_STOP ? tick.ask : tick.bid;
   return MathAbs(price - reference) <= freeze + point * 2.0;
}

void QueueFirstBulletQuickCutProtection(ulong position_id, ulong ticket, string side, double entry, double new_sl)
{
   long now_ms=(long)TimeCurrent()*1000;
   long seq=NextCampaignEventSequence();
   string json=StringFormat("{\"id\":\"%I64d-%I64u-QUICKCUT\",\"campaignId\":\"%s\",\"eventSequence\":%I64d,\"account\":\"%I64d\",\"symbol\":\"%s\",\"version\":\"2.61\",\"strategy\":\"FIXED_LADDER_FLIGHT_RECORDER\",\"magic\":\"%I64u\",\"at\":%I64d,\"action\":\"FIRST_BULLET_QUICK_CUT_ARMED\",\"side\":\"%s\",\"bulletNumber\":1,\"ticket\":\"%I64u\",\"positionId\":\"%I64u\",\"entryPrice\":%.5f,\"newSl\":%.5f,\"progressPrice\":0.00000,\"triggerPrice\":%.5f,\"bufferPrice\":0.00000,\"reason\":\"FIRST BULLET SL TIGHTENED TO FIXED ADVERSE CUT\"}",
      now_ms,ticket,JsonEscape(campaign_id),seq,AccountInfoInteger(ACCOUNT_LOGIN),JsonEscape(trade_symbol),InpMagicNumber,now_ms,
      JsonEscape(side),ticket,position_id,entry,new_sl,InpFirstBulletAdverseCutPrice);
   QueueTelemetry("/api/ea/bullet-protection",json);
}

void ManageFirstBulletQuickCut(const MqlTick &tick)
{
   if(!InpUseFirstBulletQuickCut || InpFirstBulletAdverseCutPrice <= 0.0) return;
   if(basket_close_requested || campaign_started_at <= 0) return;
   if(campaign_entries != 1 || CountOurPositions() != 1) return;
   if(first_leg_position_id == 0 || first_leg_entry_price <= 0.0) return;

   int idx = FindBullet(first_leg_position_id);
   if(idx < 0 || bullet_be_active[idx]) return;
   ulong ticket = bullet_tickets[idx];
   if(ticket == 0 || !PositionSelectByTicket(ticket) || !IsOurSelectedPosition()) return;

   ENUM_POSITION_TYPE type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
   double entry = PositionGetDouble(POSITION_PRICE_OPEN);
   double point = SymbolInfoDouble(trade_symbol, SYMBOL_POINT);
   double cut = MathMax(point * 2.0, InpFirstBulletAdverseCutPrice);
   double adverse = type == POSITION_TYPE_BUY ? entry - tick.bid : tick.ask - entry;

   if(adverse + point * 0.10 >= cut)
   {
      first_bullet_quick_cut_triggered = true;
      RequestBasketClose(StringFormat("FIRST BULLET QUICK CUT %.3f ADVERSE - CLOSE FULL CAMPAIGN", cut));
      return;
   }

   if(first_bullet_quick_cut_applied) return;
   double min_distance = BrokerMinimumDistancePrice() + point * 2.0;
   double current_sl = PositionGetDouble(POSITION_SL);
   double tp = PositionGetDouble(POSITION_TP);
   double desired = type == POSITION_TYPE_BUY ? entry - cut : entry + cut;
   desired = NormalisePrice(ClampLegalStop(type, desired, tick, min_distance));
   if(!StopImprovesFixed(type, current_sl, desired)) return;
   if(!CanModifyTicket(ticket)) return;

   ResetLastError();
   bool submitted = trade.PositionModify(ticket, desired, tp);
   uint code = trade.ResultRetcode();
   RememberModify(ticket);
   if(submitted && IsAcceptedTradeRetcode(code))
   {
      first_bullet_quick_cut_applied = true;
      first_bullet_quick_cut_sl = desired;
      bullet_initial_sls[idx] = desired;
      bullet_final_sls[idx] = desired;
      string side = type == POSITION_TYPE_BUY ? "BUY" : "SELL";
      QueueFirstBulletQuickCutProtection(first_leg_position_id, ticket, side, entry, desired);
      QueueSignalReport("FIRST_BULLET_QUICK_CUT_ARMED", side, desired,
                        StringFormat("Bullet 1 risk tightened to %.3f adverse price", cut));
      last_event = StringFormat("Bullet 1 quick-cut armed: %.3f adverse at SL %.3f", cut, desired);
   }
   else
      PrintFormat("EVE Fixed Ladder v2.61 first-bullet quick-cut modify %I64u rejected %u %s MQL=%d",
                  ticket, code, trade.ResultRetcodeDescription(), GetLastError());
}

void ManageIndividualProtection(const MqlTick &tick)
{
   if(!InpMoveEveryBulletToBreakEven) return;
   double min_distance = BrokerMinimumDistancePrice() + SymbolInfoDouble(trade_symbol, SYMBOL_POINT) * 2.0;
   double trigger = MathMax(SymbolInfoDouble(trade_symbol, SYMBOL_POINT) * 2.0, InpBreakEvenTriggerPrice);
   double buffer = MathMax(SymbolInfoDouble(trade_symbol, SYMBOL_POINT) * 2.0, InpBreakEvenBufferPrice);

   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket) || !IsOurSelectedPosition()) continue;
      ulong position_id = (ulong)PositionGetInteger(POSITION_IDENTIFIER);
      int idx = FindBullet(position_id);
      ENUM_POSITION_TYPE type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = PositionGetDouble(POSITION_SL);
      double tp = PositionGetDouble(POSITION_TP);
      double progress = type == POSITION_TYPE_BUY ? tick.bid - open : open - tick.ask;
      if(progress + SymbolInfoDouble(trade_symbol, SYMBOL_POINT) * 0.1 < trigger) continue;
      if(idx >= 0 && bullet_be_active[idx]) continue;

      double desired = type == POSITION_TYPE_BUY ? open + buffer : open - buffer;
      desired = ClampLegalStop(type, desired, tick, min_distance);
      if(!StopImprovesFixed(type, sl, desired)) continue;
      if(!CanModifyTicket(ticket)) continue;

      ResetLastError();
      bool submitted = trade.PositionModify(ticket, NormalisePrice(desired), tp);
      uint code = trade.ResultRetcode();
      RememberModify(ticket);
      if(submitted && IsAcceptedTradeRetcode(code))
      {
         if(idx >= 0)
         {
            bullet_be_active[idx] = true;
            bullet_be_times[idx] = TimeCurrent();
            bullet_final_sls[idx] = NormalisePrice(desired);
         }
         QueueBulletProtection(position_id, ticket, idx >= 0 ? bullet_numbers[idx] : 0,
                               type == POSITION_TYPE_BUY ? "BUY" : "SELL", open, desired, progress);
         last_event = StringFormat("Bullet %d reached halfway %.3f; SL moved to BE + costs at %.3f", idx >= 0 ? bullet_numbers[idx] : 0, trigger, desired);
      }
      else
         PrintFormat("EVE Fixed Ladder v2.61 BE modify %I64u rejected %u %s MQL=%d", ticket, code, trade.ResultRetcodeDescription(), GetLastError());
   }
}

double BetterStop(ENUM_POSITION_TYPE type, double current_stop, double candidate)
{
   if(current_stop <= 0.0) return candidate;
   if(type == POSITION_TYPE_BUY) return MathMax(current_stop, candidate);
   return MathMin(current_stop, candidate);
}

bool StopImprovesFixed(ENUM_POSITION_TYPE type, double old_sl, double new_sl)
{
   double point = SymbolInfoDouble(trade_symbol, SYMBOL_POINT);
   if(new_sl <= 0.0) return false;
   if(old_sl <= 0.0) return true;
   if(type == POSITION_TYPE_BUY) return new_sl > old_sl + point;
   return new_sl < old_sl - point;
}

double ClampLegalStop(ENUM_POSITION_TYPE type, double desired, const MqlTick &tick, double min_distance)
{
   if(type == POSITION_TYPE_BUY) return MathMin(desired, tick.bid - min_distance);
   return MathMax(desired, tick.ask + min_distance);
}

bool StopImprovesEnough(ENUM_POSITION_TYPE type, double old_sl, double new_sl, double atr)
{
   if(new_sl <= 0.0) return false;
   double step = MathMax(SymbolInfoDouble(trade_symbol, SYMBOL_POINT) * 2.0, atr * InpMinimumTrailStepATR);
   if(old_sl <= 0.0) return true;
   if(type == POSITION_TYPE_BUY) return new_sl >= old_sl + step;
   return new_sl <= old_sl - step;
}

bool CanModifyTicket(ulong ticket)
{
   ulong now = GetTickCount64();
   for(int i=0; i<modified_count; i++)
      if(modified_tickets[i] == ticket) return now - modified_times[i] >= 750;
   return true;
}

void RememberModify(ulong ticket)
{
   ulong now = GetTickCount64();
   for(int i=0; i<modified_count; i++)
   {
      if(modified_tickets[i] == ticket)
      {
         modified_times[i] = now;
         return;
      }
   }
   if(modified_count < MODIFY_MEMORY_SIZE)
   {
      modified_tickets[modified_count] = ticket;
      modified_times[modified_count] = now;
      modified_count++;
   }
}

void UpdateNewestLegStats()
{
   ulong latest_ticket = 0;
   ulong latest_identifier = 0;
   long latest_open_msc = -1;
   datetime latest_open_time = 0;
   double latest_profit = 0.0;

   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket) || !IsOurSelectedPosition()) continue;
      long opened_msc = PositionGetInteger(POSITION_TIME_MSC);
      if(opened_msc > latest_open_msc || (opened_msc == latest_open_msc && ticket > latest_ticket))
      {
         latest_open_msc = opened_msc;
         latest_ticket = ticket;
         latest_identifier = (ulong)PositionGetInteger(POSITION_IDENTIFIER);
         latest_open_time = (datetime)PositionGetInteger(POSITION_TIME);
         latest_profit = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
      }
   }

   if(latest_ticket == 0)
   {
      newest_ticket = 0;
      newest_position_id = 0;
      newest_leg_open_time = 0;
      newest_leg_current_profit = 0.0;
      newest_leg_peak_profit = 0.0;
      return;
   }

   if(latest_identifier != newest_position_id || latest_ticket != newest_ticket)
   {
      newest_ticket = latest_ticket;
      newest_position_id = latest_identifier;
      newest_leg_open_time = latest_open_time;
      newest_leg_current_profit = latest_profit;
      newest_leg_peak_profit = latest_profit;
      return;
   }

   newest_leg_current_profit = latest_profit;
   newest_leg_peak_profit = MathMax(newest_leg_peak_profit, latest_profit);
}

double EstimatedOneLegRiskMoney()
{
   double atr = momentum.atr > 0.0 ? momentum.atr : CurrentATR();
   if(atr <= 0.0) return 0.0;
   double price_risk = MathMax(FallbackDistance(), BrokerMinimumDistancePrice());
   double tick_size = SymbolInfoDouble(trade_symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(trade_symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(tick_value <= 0.0) tick_value = SymbolInfoDouble(trade_symbol, SYMBOL_TRADE_TICK_VALUE);
   if(tick_size <= 0.0 || tick_value <= 0.0) return 0.0;
   return (price_risk / tick_size) * tick_value * EffectiveLot();
}

double EstimatedBasketCommissionReserve()
{
   double lot_units = EffectiveLot() > 0.0 ? EffectiveLot() / 0.01 : 1.0;
   return CountOurPositions() * MathMax(0.0, InpCommissionReservePer001Lot) * lot_units;
}

double BasketLockTriggerMoney()
{
   double risk_based = EstimatedOneLegRiskMoney() * MathMax(0.0, InpBasketLockTriggerRiskFraction);
   double cost_based = EstimatedBasketCommissionReserve() + 0.10;
   return MathMax(MathMax(MathMax(0.01, InpBasketLockMinimumMoney), risk_based), cost_based);
}

bool FirstLegFailureTriggered(const MqlTick &tick, double &adverse_price, double &threshold_price)
{
   adverse_price = 0.0;
   threshold_price = 0.0;
   if(!InpUseFirstLegFailureExit || basket_close_requested) return false;
   if(campaign_started_at <= 0 || campaign_entries != 1 || CountOurPositions() != 1) return false;
   if(first_leg_entry_price <= 0.0 || first_leg_position_id == 0) return false;

   double atr = first_leg_entry_atr > 0.0 ? first_leg_entry_atr : (momentum.atr > 0.0 ? momentum.atr : CurrentATR());
   if(atr <= 0.0) return false;

   double point = SymbolInfoDouble(trade_symbol, SYMBOL_POINT);
   threshold_price = MathMax(point * 2.0, atr * MathMax(0.01, InpFirstLegFailureATR));
   if(campaign_side == "BUY")
      adverse_price = first_leg_entry_price - tick.bid;
   else if(campaign_side == "SELL")
      adverse_price = tick.ask - first_leg_entry_price;
   else
      return false;

   return adverse_price + point * 0.10 >= threshold_price;
}

void ManageBasketProtection(const MqlTick &tick)
{
   if(CountOurPositions() <= 0 || basket_close_requested) return;
   UpdateCampaignStats();

   double current = BasketFloatingProfit();
   if(campaign_profit_target_enabled && campaign_profit_target_money > 0.0 && current + 0.0001 >= campaign_profit_target_money)
   {
      RequestBasketClose(StringFormat("CAMPAIGN PROFIT TARGET %.2f REACHED", campaign_profit_target_money));
      return;
   }

   // v2.61: one new rule only. Once the campaign peak proves itself,
   // protect the basket with a moving dollar floor = highest peak - allowed giveback.
   // Values are snapshotted in StartCampaign, so dashboard edits do not alter a live campaign.
   if(campaign_peak_protection_enabled && campaign_peak_activation_money > 0.0 && campaign_peak_giveback_money > 0.0)
   {
      if(!campaign_peak_protection_armed && campaign_peak_floating + 0.0001 >= campaign_peak_activation_money)
      {
         campaign_peak_protection_armed = true;
         campaign_peak_protection_floor = MathMax(0.01, campaign_peak_floating - campaign_peak_giveback_money);
         QueueSignalReport("BASKET_PEAK_PROTECTION_ARMED", RecordedCampaignSide(), campaign_peak_protection_floor,
                           StringFormat("Peak %.2f activated protection; floor %.2f with %.2f giveback",
                                        campaign_peak_floating, campaign_peak_protection_floor, campaign_peak_giveback_money));
         last_event = StringFormat("Basket peak protection armed at %.2f; floor %.2f",
                                   campaign_peak_floating, campaign_peak_protection_floor);
      }

      if(campaign_peak_protection_armed)
      {
         campaign_peak_protection_floor = MathMax(0.01, campaign_peak_floating - campaign_peak_giveback_money);
         if(current <= campaign_peak_protection_floor + 0.0001)
         {
            RequestBasketClose(StringFormat("BASKET PEAK PROTECTION FLOOR %.2f AFTER %.2f PEAK",
                                            campaign_peak_protection_floor, campaign_peak_floating));
            return;
         }
      }
   }

   if(newest_leg_sl_exit_detected)
   {
      newest_leg_sl_exit_detected = false;
      RequestBasketClose(basket_close_reason == "" ? "NEWEST BULLET SL - CLOSE FULL CAMPAIGN" : basket_close_reason);
      return;
   }

   // Existing optional natural-mode lock remains unchanged and OFF by default.
   if(InpUseBasketProfitLock && CountOurPositions() >= MathMax(2, InpProfitLockMinimumLegs))
   {
      double trigger = BasketLockTriggerMoney();
      if(campaign_peak_floating + 0.0001 >= trigger)
      {
         double retain = MathMax(5.0, MathMin(95.0, InpBasketLockRetainPercent)) / 100.0;
         double protected_floor = MathMax(EstimatedBasketCommissionReserve() + 0.05, campaign_peak_floating * retain);
         if(current <= protected_floor)
         {
            RequestBasketClose(StringFormat("NATURAL MODE PROFIT FLOOR %.2f AFTER %.2f PEAK", protected_floor, campaign_peak_floating));
            return;
         }
      }
   }
}


void RequestBasketClose(string reason)
{
   if(basket_close_requested) return;
   if(CountOurPositions() <= 0 && campaign_started_at <= 0)
   {
      CancelAllPending(reason);
      last_event = reason + ": no open basket";
      return;
   }
   basket_close_requested = true;
   basket_close_reason = reason;
   campaign_exit_reason = reason;
   adding_stopped = true;
   QueueBankDecision(reason, BasketFloatingProfit());
   CancelAllPending(reason);
   if(CountOurPositions() > 0)
   {
      basket_close_attempts++;
      CloseAllPositions(reason);
   }
   last_event = reason;
}

string DealReasonText(ENUM_DEAL_REASON reason)
{
   switch(reason)
   {
      case DEAL_REASON_CLIENT: return "CLIENT";
      case DEAL_REASON_MOBILE: return "MOBILE";
      case DEAL_REASON_WEB: return "WEB";
      case DEAL_REASON_EXPERT: return "EXPERT";
      case DEAL_REASON_SL: return "STOP LOSS";
      case DEAL_REASON_TP: return "TAKE PROFIT";
      case DEAL_REASON_SO: return "STOP OUT";
   }
   return "OTHER";
}

void EnforceCapitalProtection()
{
   if(BasketEmergencyReached())
      RequestBasketClose("HARD BASKET LOSS LIMIT");
}

bool BasketEmergencyReached()
{
   if(CountOurPositions() == 0) return false;
   double loss_limit = 0.0;
   if(InpEmergencyBasketLossMoney > 0.0) loss_limit = InpEmergencyBasketLossMoney;
   if(InpEmergencyBasketLossPercent > 0.0)
   {
      double pct_limit = AccountInfoDouble(ACCOUNT_BALANCE) * InpEmergencyBasketLossPercent / 100.0;
      loss_limit = loss_limit > 0.0 ? MathMin(loss_limit, pct_limit) : pct_limit;
   }
   return loss_limit > 0.0 && BasketFloatingProfit() <= -loss_limit;
}

bool DailyLossBlocked()
{
   if(!runtime_daily_loss_enabled || runtime_daily_loss_money <= 0.0) return false;
   return DailyRealisedProfit() <= -runtime_daily_loss_money;
}

double DailyLossRemaining()
{
   if(!runtime_daily_loss_enabled || runtime_daily_loss_money <= 0.0) return runtime_daily_loss_money;
   return MathMax(0.0, runtime_daily_loss_money + DailyRealisedProfit());
}

double DailyRealisedProfit()
{
   ulong now_ms = GetTickCount64();
   if(cached_daily_pnl_ms > 0 && now_ms - cached_daily_pnl_ms < 1000) return cached_daily_pnl;
   MqlDateTime parts;
   TimeToStruct(TimeCurrent(), parts);
   parts.hour = 0; parts.min = 0; parts.sec = 0;
   datetime start = StructToTime(parts);
   if(runtime_daily_loss_reset_at > start && runtime_daily_loss_reset_at <= TimeCurrent() + 60)
      start = runtime_daily_loss_reset_at;
   if(!HistorySelect(start, TimeCurrent() + 60)) return cached_daily_pnl;
   double total = 0.0;
   for(int i=0; i<HistoryDealsTotal(); i++)
   {
      ulong deal = HistoryDealGetTicket(i);
      if(deal == 0) continue;
      if(HistoryDealGetString(deal, DEAL_SYMBOL) != trade_symbol) continue;
      if((ulong)HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagicNumber) continue;
      ENUM_DEAL_ENTRY entry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal, DEAL_ENTRY);
      if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_OUT_BY && entry != DEAL_ENTRY_INOUT) continue;
      total += HistoryDealGetDouble(deal, DEAL_PROFIT) +
               HistoryDealGetDouble(deal, DEAL_COMMISSION) +
               HistoryDealGetDouble(deal, DEAL_SWAP) +
               HistoryDealGetDouble(deal, DEAL_FEE);
   }
   cached_daily_pnl = total;
   cached_daily_pnl_ms = now_ms;
   return total;
}

double CampaignRealisedProfit()
{
   if(campaign_started_at <= 0) return AccountInfoDouble(ACCOUNT_BALANCE) - campaign_start_balance;
   if(!HistorySelect(campaign_started_at - 2, TimeCurrent() + 60)) return 0.0;
   double total = 0.0;
   for(int i=0; i<HistoryDealsTotal(); i++)
   {
      ulong deal = HistoryDealGetTicket(i);
      if(deal == 0) continue;
      if(HistoryDealGetString(deal, DEAL_SYMBOL) != trade_symbol) continue;
      if((ulong)HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagicNumber) continue;
      total += HistoryDealGetDouble(deal, DEAL_PROFIT) +
               HistoryDealGetDouble(deal, DEAL_COMMISSION) +
               HistoryDealGetDouble(deal, DEAL_SWAP) +
               HistoryDealGetDouble(deal, DEAL_FEE);
   }
   return total;
}

bool CloseAllPositions(string reason)
{
   bool all_closed = true;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket) || !IsOurSelectedPosition()) continue;
      ResetLastError();
      bool submitted = trade.PositionClose(ticket, InpSlippagePoints);
      uint code = trade.ResultRetcode();
      if(!submitted || !IsAcceptedTradeRetcode(code))
      {
         all_closed = false;
         PrintFormat("EVE Fixed Ladder v2.61 close %I64u failed %u %s MQL=%d", ticket, code, trade.ResultRetcodeDescription(), GetLastError());
      }
   }
   last_event = reason + (all_closed ? ": close requests accepted" : ": some close requests require retry");
   return all_closed;
}

int CountOurPositions()
{
   int count = 0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0 && PositionSelectByTicket(ticket) && IsOurSelectedPosition()) count++;
   }
   return count;
}

int CountOurPending()
{
   int count = 0;
   for(int i=OrdersTotal()-1; i>=0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket > 0 && OrderSelect(ticket) && IsOurSelectedOrder()) count++;
   }
   return count;
}

bool IsOurSelectedPosition()
{
   return PositionGetString(POSITION_SYMBOL) == trade_symbol &&
          (ulong)PositionGetInteger(POSITION_MAGIC) == InpMagicNumber;
}

bool IsOurSelectedOrder()
{
   if(OrderGetString(ORDER_SYMBOL) != trade_symbol) return false;
   if((ulong)OrderGetInteger(ORDER_MAGIC) != InpMagicNumber) return false;
   ENUM_ORDER_TYPE type = (ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
   return type == ORDER_TYPE_BUY_STOP || type == ORDER_TYPE_SELL_STOP;
}

string OurPositionSide()
{
   int buys = 0, sells = 0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket) || !IsOurSelectedPosition()) continue;
      ENUM_POSITION_TYPE type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      if(type == POSITION_TYPE_BUY) buys++; else if(type == POSITION_TYPE_SELL) sells++;
   }
   if(buys > 0 && sells > 0) return "MIXED";
   if(buys > 0) return "BUY";
   if(sells > 0) return "SELL";
   return "NONE";
}

string OurPendingSide()
{
   bool buy = false, sell = false;
   for(int i=OrdersTotal()-1; i>=0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0 || !OrderSelect(ticket) || !IsOurSelectedOrder()) continue;
      ENUM_ORDER_TYPE type = (ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
      if(type == ORDER_TYPE_BUY_STOP) buy = true;
      if(type == ORDER_TYPE_SELL_STOP) sell = true;
   }
   if(buy && sell) return "BOTH";
   if(buy) return "BUY";
   if(sell) return "SELL";
   return "NONE";
}

double BasketFloatingProfit()
{
   double total = 0.0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket) || !IsOurSelectedPosition()) continue;
      total += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
   }
   return total;
}

double OurTotalLots()
{
   double total = 0.0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket) || !IsOurSelectedPosition()) continue;
      total += PositionGetDouble(POSITION_VOLUME);
   }
   return total;
}

double HighestOurEntry()
{
   double highest = 0.0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket) || !IsOurSelectedPosition()) continue;
      highest = MathMax(highest, PositionGetDouble(POSITION_PRICE_OPEN));
   }
   return highest;
}

double LowestOurEntry()
{
   double lowest = 0.0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket) || !IsOurSelectedPosition()) continue;
      double price = PositionGetDouble(POSITION_PRICE_OPEN);
      if(lowest <= 0.0 || price < lowest) lowest = price;
   }
   return lowest;
}

double BrokerMinimumDistancePrice()
{
   double point = SymbolInfoDouble(trade_symbol, SYMBOL_POINT);
   long stops = SymbolInfoInteger(trade_symbol, SYMBOL_TRADE_STOPS_LEVEL);
   long freeze = SymbolInfoInteger(trade_symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   return MathMax((double)stops, (double)freeze) * point;
}

double NormalisePrice(double price)
{
   int digits = (int)SymbolInfoInteger(trade_symbol, SYMBOL_DIGITS);
   return NormalizeDouble(price, digits);
}

double EffectiveLot()
{
   double lot = runtime_fixed_lot;
   if(runtime_use_equity_scaling && runtime_equity_per_001 > 0.0)
   {
      double units = MathFloor(AccountInfoDouble(ACCOUNT_EQUITY) / runtime_equity_per_001);
      if(units < 1.0) units = 1.0;
      lot = units * 0.01;
   }
   return NormaliseVolume(lot);
}

double NormaliseVolume(double volume)
{
   double minimum = SymbolInfoDouble(trade_symbol, SYMBOL_VOLUME_MIN);
   double maximum = SymbolInfoDouble(trade_symbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(trade_symbol, SYMBOL_VOLUME_STEP);
   if(step <= 0.0) step = minimum > 0.0 ? minimum : 0.01;
   volume = MathMax(minimum, MathMin(maximum, volume));
   volume = MathFloor(volume / step + 0.0000001) * step;
   return NormalizeDouble(volume, 2);
}

string EngineStateText()
{
   switch(engine_state)
   {
      case STATE_WARMING: return "WARMING TELEMETRY";
      case STATE_IDLE: return "IMMEDIATE REARM";
      case STATE_ARMED: return "FIXED TWO-SIDED LADDER ARMED";
      case STATE_RUNNING: return "FIXED LADDER CAMPAIGN - BOTH ORIGINAL SIDES REMAIN";
      case STATE_CANCELLING: return "CLOSING / REBUILDING";
      case STATE_PAUSED: return "PAUSED";
      case STATE_EMERGENCY: return "EMERGENCY STOP";
   }
   return "UNKNOWN";
}

void QueueTelemetry(string endpoint, string payload)
{
   if(endpoint == "" || payload == "") return;
   if(telemetry_count >= TELEMETRY_QUEUE_SIZE)
   {
      telemetry_tail = (telemetry_tail + 1) % TELEMETRY_QUEUE_SIZE;
      telemetry_count--;
   }
   telemetry_endpoints[telemetry_head] = endpoint;
   telemetry_payloads[telemetry_head] = payload;
   telemetry_head = (telemetry_head + 1) % TELEMETRY_QUEUE_SIZE;
   telemetry_count++;
}

bool FlushOneTelemetry()
{
   if(telemetry_count <= 0) return true;
   string endpoint = telemetry_endpoints[telemetry_tail];
   string payload = telemetry_payloads[telemetry_tail];
   if(!PostJson(endpoint, payload)) return false;
   telemetry_endpoints[telemetry_tail] = "";
   telemetry_payloads[telemetry_tail] = "";
   telemetry_tail = (telemetry_tail + 1) % TELEMETRY_QUEUE_SIZE;
   telemetry_count--;
   return true;
}

string BuildCampaignId(string seed)
{
   return StringFormat("%I64d-%I64d-%I64u-%s", AccountInfoInteger(ACCOUNT_LOGIN), (long)TimeCurrent() * 1000, GetTickCount64(), seed);
}

long NextCampaignEventSequence()
{
   campaign_event_sequence++;
   return campaign_event_sequence;
}

string RecordedCampaignSide()
{
   if(campaign_buy_bullets_fired > 0 && campaign_sell_bullets_fired > 0) return "MIXED";
   if(campaign_buy_bullets_fired > 0) return "BUY";
   if(campaign_sell_bullets_fired > 0) return "SELL";
   return campaign_side;
}

void SyncCampaignCountersFromBulletMemory()
{
   if(campaign_started_at <= 0) return;
   int buys = 0;
   int sells = 0;
   int unique = 0;
   for(int i=0; i<bullet_memory_count; i++)
   {
      if(bullet_position_ids[i] == 0) continue;
      unique++;
      if(bullet_sides[i] == "BUY") buys++;
      else if(bullet_sides[i] == "SELL") sells++;
   }
   if(unique > campaign_entries) campaign_entries = unique;
   if(buys > campaign_buy_bullets_fired) campaign_buy_bullets_fired = buys;
   if(sells > campaign_sell_bullets_fired) campaign_sell_bullets_fired = sells;
}

void ReconcileCampaignCountersFromHistory()
{
   if(campaign_started_at <= 0) return;
   if(!HistorySelect(campaign_started_at - 2, TimeCurrent() + 60)) return;
   ulong seen[128];
   string sides[128];
   int seen_count = 0;
   for(int i=0; i<HistoryDealsTotal(); i++)
   {
      ulong deal = HistoryDealGetTicket(i);
      if(deal == 0) continue;
      if(HistoryDealGetString(deal, DEAL_SYMBOL) != trade_symbol) continue;
      if((ulong)HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagicNumber) continue;
      ENUM_DEAL_ENTRY entry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal, DEAL_ENTRY);
      if(entry != DEAL_ENTRY_IN && entry != DEAL_ENTRY_INOUT) continue;
      ulong pid = (ulong)HistoryDealGetInteger(deal, DEAL_POSITION_ID);
      if(pid == 0) continue;
      bool exists = false;
      for(int j=0; j<seen_count; j++) if(seen[j] == pid) { exists = true; break; }
      if(exists || seen_count >= 128) continue;
      seen[seen_count] = pid;
      ENUM_DEAL_TYPE type = (ENUM_DEAL_TYPE)HistoryDealGetInteger(deal, DEAL_TYPE);
      sides[seen_count] = type == DEAL_TYPE_BUY ? "BUY" : "SELL";
      seen_count++;
   }
   int buys = 0;
   int sells = 0;
   for(int i=0; i<seen_count; i++)
   {
      if(sides[i] == "BUY") buys++;
      else if(sides[i] == "SELL") sells++;
   }
   if(seen_count > campaign_entries) campaign_entries = seen_count;
   if(buys > campaign_buy_bullets_fired) campaign_buy_bullets_fired = buys;
   if(sells > campaign_sell_bullets_fired) campaign_sell_bullets_fired = sells;
}

void ResetBulletTracking()
{
   bullet_memory_count = 0;
   for(int i=0; i<BULLET_MEMORY_SIZE; i++)
   {
      bullet_position_ids[i]=0; bullet_tickets[i]=0; bullet_sides[i]=""; bullet_campaign_ids[i]=""; bullet_numbers[i]=0;
      bullet_entries[i]=0.0; bullet_initial_sls[i]=0.0; bullet_final_sls[i]=0.0;
      bullet_mfe_price[i]=0.0; bullet_mae_price[i]=0.0; bullet_be_active[i]=false;
      bullet_open_times[i]=0; bullet_be_times[i]=0;
   }
}

int FindBullet(ulong position_id)
{
   for(int i=0; i<bullet_memory_count; i++) if(bullet_position_ids[i] == position_id) return i;
   return -1;
}

void RegisterBullet(ulong position_id, ulong ticket, string side, int bullet_number, double entry, double initial_sl)
{
   int idx = FindBullet(position_id);
   if(idx < 0)
   {
      if(bullet_memory_count >= BULLET_MEMORY_SIZE) return;
      idx = bullet_memory_count++;
   }
   bullet_position_ids[idx]=position_id; bullet_tickets[idx]=ticket; bullet_sides[idx]=side; bullet_campaign_ids[idx]=campaign_id; bullet_numbers[idx]=bullet_number;
   bullet_entries[idx]=entry; bullet_initial_sls[idx]=initial_sl; bullet_final_sls[idx]=initial_sl;
   bullet_mfe_price[idx]=0.0; bullet_mae_price[idx]=0.0; bullet_be_active[idx]=false;
   bullet_open_times[idx]=TimeCurrent(); bullet_be_times[idx]=0;
}

void RebuildBulletMemoryFromLivePositions()
{
   ResetBulletTracking();
   int buy_no=0, sell_no=0;
   for(int i=0; i<PositionsTotal(); i++)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0 || !PositionSelectByTicket(ticket) || !IsOurSelectedPosition()) continue;
      ENUM_POSITION_TYPE type=(ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      string side=type==POSITION_TYPE_BUY ? "BUY" : "SELL";
      int number=side=="BUY" ? ++buy_no : ++sell_no;
      RegisterBullet((ulong)PositionGetInteger(POSITION_IDENTIFIER), ticket, side, number,
                     PositionGetDouble(POSITION_PRICE_OPEN), PositionGetDouble(POSITION_SL));
   }
}

void UpdateBulletMetrics(const MqlTick &tick)
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0 || !PositionSelectByTicket(ticket) || !IsOurSelectedPosition()) continue;
      ulong position_id=(ulong)PositionGetInteger(POSITION_IDENTIFIER);
      int idx=FindBullet(position_id);
      if(idx<0)
      {
         ENUM_POSITION_TYPE t=(ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
         RegisterBullet(position_id, ticket, t==POSITION_TYPE_BUY ? "BUY" : "SELL", 0,
                        PositionGetDouble(POSITION_PRICE_OPEN), PositionGetDouble(POSITION_SL));
         idx=FindBullet(position_id);
      }
      if(idx<0) continue;
      ENUM_POSITION_TYPE type=(ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      double open=PositionGetDouble(POSITION_PRICE_OPEN);
      double favorable=type==POSITION_TYPE_BUY ? tick.bid-open : open-tick.ask;
      double adverse=type==POSITION_TYPE_BUY ? open-tick.bid : tick.ask-open;
      bullet_mfe_price[idx]=MathMax(bullet_mfe_price[idx], favorable);
      bullet_mae_price[idx]=MathMax(bullet_mae_price[idx], adverse);
      bullet_final_sls[idx]=PositionGetDouble(POSITION_SL);
   }
}

bool IsBulletProtected(ulong position_id)
{
   int idx=FindBullet(position_id);
   return idx>=0 && bullet_be_active[idx];
}

void QueueBulletProtection(ulong position_id, ulong ticket, int bullet_number, string side, double entry, double new_sl, double progress)
{
   long now_ms=(long)TimeCurrent()*1000;
   long seq=NextCampaignEventSequence();
   string json=StringFormat("{\"id\":\"%I64d-%I64u-BE\",\"campaignId\":\"%s\",\"eventSequence\":%I64d,\"account\":\"%I64d\",\"symbol\":\"%s\",\"version\":\"2.61\",\"strategy\":\"FIXED_LADDER_FLIGHT_RECORDER\",\"magic\":\"%I64u\",\"at\":%I64d,\"action\":\"BE_ACTIVATED\",\"side\":\"%s\",\"bulletNumber\":%d,\"ticket\":\"%I64u\",\"positionId\":\"%I64u\",\"entryPrice\":%.5f,\"newSl\":%.5f,\"progressPrice\":%.5f,\"triggerPrice\":%.5f,\"bufferPrice\":%.5f,\"reason\":\"HALFWAY REACHED - SL MOVED TO BE PLUS COSTS\"}",
      now_ms,ticket,JsonEscape(campaign_id),seq,AccountInfoInteger(ACCOUNT_LOGIN),JsonEscape(trade_symbol),InpMagicNumber,now_ms,
      JsonEscape(side),bullet_number,ticket,position_id,entry,new_sl,progress,InpBreakEvenTriggerPrice,InpBreakEvenBufferPrice);
   QueueTelemetry("/api/ea/bullet-protection",json);
}


string PositionReplayJson()
{
   string out="["; bool first=true;
   for(int i=0;i<PositionsTotal();i++)
   {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0 || !PositionSelectByTicket(ticket) || !IsOurSelectedPosition()) continue;
      ulong pid=(ulong)PositionGetInteger(POSITION_IDENTIFIER); int idx=FindBullet(pid);
      ENUM_POSITION_TYPE type=(ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      if(!first) out+=","; first=false;
      out+=StringFormat("{\"ticket\":\"%I64u\",\"positionId\":\"%I64u\",\"side\":\"%s\",\"bullet\":%d,\"entry\":%.5f,\"sl\":%.5f,\"profit\":%.2f,\"be\":%s,\"mfe\":%.5f,\"mae\":%.5f}",
         ticket,pid,type==POSITION_TYPE_BUY?"BUY":"SELL",idx>=0?bullet_numbers[idx]:0,PositionGetDouble(POSITION_PRICE_OPEN),
         PositionGetDouble(POSITION_SL),PositionGetDouble(POSITION_PROFIT)+PositionGetDouble(POSITION_SWAP),idx>=0&&bullet_be_active[idx]?"true":"false",
         idx>=0?bullet_mfe_price[idx]:0.0,idx>=0?bullet_mae_price[idx]:0.0);
   }
   return out+"]";
}

string PendingReplayJson()
{
   string out="["; bool first=true;
   for(int i=0;i<OrdersTotal();i++)
   {
      ulong ticket=OrderGetTicket(i);
      if(ticket==0 || !OrderSelect(ticket) || !IsOurSelectedOrder()) continue;
      ENUM_ORDER_TYPE type=(ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
      if(!first) out+=","; first=false;
      out+=StringFormat("{\"ticket\":\"%I64u\",\"type\":\"%s\",\"price\":%.5f,\"volume\":%.2f}",ticket,
         type==ORDER_TYPE_BUY_STOP?"BUY_STOP":"SELL_STOP",OrderGetDouble(ORDER_PRICE_OPEN),OrderGetDouble(ORDER_VOLUME_CURRENT));
   }
   return out+"]";
}

void MaybeQueueReplaySnapshot()
{
   if(InpReplayLogSeconds<=0) return;
   ulong now=GetTickCount64();
   ulong interval=(ulong)MathMax(1,InpReplayLogSeconds)*1000;
   if(last_replay_log_ms>0 && now-last_replay_log_ms<interval) return;
   last_replay_log_ms=now;
   if(campaign_id=="" && CountOurPositions()==0 && CountOurPending()==0) return;

   long now_ms=(long)TimeCurrent()*1000;
   long seq=NextCampaignEventSequence();
   MqlTick tick;
   if(!SymbolInfoTick(trade_symbol,tick)) return;
   string json=StringFormat(
      "{\"id\":\"%I64d-%I64u\",\"campaignId\":\"%s\",\"eventSequence\":%I64d,\"account\":\"%I64d\",\"symbol\":\"%s\",\"version\":\"2.61\",\"at\":%I64d,\"bid\":%.5f,\"ask\":%.5f,\"spreadPoints\":%.1f,\"floatingProfit\":%.2f,\"peakProfit\":%.2f,\"positions\":%d,\"pending\":%d,\"buyPositions\":%d,\"sellPositions\":%d,\"uniqueBulletsFired\":%d,\"buyBulletsFired\":%d,\"sellBulletsFired\":%d,\"newestTicket\":\"%I64u\",\"profitTargetEnabled\":%s,\"profitTargetMoney\":%.2f,\"basketPeakProtectionEnabled\":%s,\"basketPeakActivationMoney\":%.2f,\"basketPeakGivebackMoney\":%.2f,\"basketPeakProtectionArmed\":%s,\"basketPeakProtectionFloor\":%.2f,\"lastEvent\":\"%s\",\"positionState\":%s,\"pendingState\":%s}",
      now_ms,newest_ticket,JsonEscape(campaign_id),seq,AccountInfoInteger(ACCOUNT_LOGIN),JsonEscape(trade_symbol),now_ms,
      tick.bid,tick.ask,CurrentSpreadPoints(),BasketFloatingProfit(),campaign_peak_floating,CountOurPositions(),CountOurPending(),CountPositionsSide("BUY"),CountPositionsSide("SELL"),
      campaign_entries,campaign_buy_bullets_fired,campaign_sell_bullets_fired,newest_ticket,
      campaign_profit_target_enabled?"true":"false",campaign_profit_target_money,
      campaign_peak_protection_enabled?"true":"false",campaign_peak_activation_money,campaign_peak_giveback_money,
      campaign_peak_protection_armed?"true":"false",campaign_peak_protection_floor,
      JsonEscape(last_event),PositionReplayJson(),PendingReplayJson());
   QueueTelemetry("/api/ea/replay",json);
}



void QueueLadderReport(string reason)
{
   int levels=(int)MathMax(1,MathMin(50,InpLevelsPerSide)); string buys="[",sells="[";
   for(int i=1;i<=levels;i++)
   {
      if(i>1){buys+=",";sells+=",";}
      buys+=DoubleToString(NormalisePrice(ladder_anchor_price+BulletSpacing()*i),(int)SymbolInfoInteger(trade_symbol,SYMBOL_DIGITS));
      sells+=DoubleToString(NormalisePrice(ladder_anchor_price-BulletSpacing()*i),(int)SymbolInfoInteger(trade_symbol,SYMBOL_DIGITS));
   }
   buys+="]"; sells+="]";
   long now_ms=(long)TimeCurrent()*1000;
   long seq=NextCampaignEventSequence();
   string json=StringFormat("{\"id\":\"%s\",\"campaignId\":\"%s\",\"eventSequence\":%I64d,\"account\":\"%I64d\",\"symbol\":\"%s\",\"version\":\"2.61\",\"at\":%I64d,\"anchorPrice\":%.5f,\"levelsPerSide\":%d,\"spacing\":%.5f,\"lot\":%.2f,\"fallback\":%.5f,\"beTrigger\":%.5f,\"beBuffer\":%.5f,\"buyPrices\":%s,\"sellPrices\":%s,\"reason\":\"%s\"}",
      JsonEscape(campaign_id),JsonEscape(campaign_id),seq,AccountInfoInteger(ACCOUNT_LOGIN),JsonEscape(trade_symbol),now_ms,ladder_anchor_price,levels,
      BulletSpacing(),EffectiveLot(),FallbackDistance(),InpBreakEvenTriggerPrice,InpBreakEvenBufferPrice,buys,sells,JsonEscape(reason));
   QueueTelemetry("/api/ea/ladder",json);
}


void QueueSignalReport(string action, string side, double price, string reason)
{
   long now_ms=(long)TimeCurrent()*1000;
   long seq=NextCampaignEventSequence();
   string json=StringFormat("{\"id\":\"%I64d-%s-%d\",\"campaignId\":\"%s\",\"eventSequence\":%I64d,\"account\":\"%I64d\",\"symbol\":\"%s\",\"version\":\"2.61\",\"strategy\":\"FIXED_LADDER_FLIGHT_RECORDER\",\"magic\":\"%I64u\",\"at\":%I64d,\"action\":\"%s\",\"side\":\"%s\",\"campaignEntry\":%d,\"price\":%.5f,\"fallbackDistance\":%.5f,\"bulletSpacing\":%.5f,\"beTrigger\":%.5f,\"reason\":\"%s\"}",
      now_ms,JsonEscape(action),campaign_entries,JsonEscape(campaign_id),seq,AccountInfoInteger(ACCOUNT_LOGIN),JsonEscape(trade_symbol),InpMagicNumber,
      now_ms,JsonEscape(action),JsonEscape(side),campaign_entries,price,FallbackDistance(),BulletSpacing(),InpBreakEvenTriggerPrice,JsonEscape(reason));
   QueueTelemetry("/api/ea/signal",json);
}


string ReportingCampaignId(ulong position_id)
{
   int idx = FindBullet(position_id);
   if(idx >= 0 && bullet_campaign_ids[idx] != "") return bullet_campaign_ids[idx];
   if(campaign_id != "") return campaign_id;
   return last_reporting_campaign_id;
}

void QueueLegReport(string action, string side, ulong ticket, ulong position_id, double volume, double price, double net_profit, string reason)
{
   QueueLegReportDetailed(action, side, ticket, position_id, 0, volume, price, 0.0, 0.0, false, 0, 0.0, 0.0, net_profit, reason);
}

void QueueLegReportDetailed(string action, string side, ulong ticket, ulong position_id, int bullet_number,
                            double volume, double price, double initial_sl, double final_sl, bool be_active,
                            int time_to_be_seconds, double mfe_price, double mae_price, double net_profit, string reason)
{
   long now_ms = (long)TimeCurrent() * 1000;
   long seq = NextCampaignEventSequence();
   string report_campaign_id = ReportingCampaignId(position_id);
   string campaign_context = basket_close_reason != "" ? basket_close_reason : (campaign_exit_reason != "CAMPAIGN COMPLETE" ? campaign_exit_reason : "");
   string protection_state = be_active ? "BE_PROTECTED" : "INITIAL_RISK";
   string json = StringFormat(
      "{\"id\":\"%I64d-%I64u-%s\",\"campaignId\":\"%s\",\"eventSequence\":%I64d,\"account\":\"%I64d\",\"symbol\":\"%s\",\"version\":\"2.61\",\"strategy\":\"FIXED_LADDER_FLIGHT_RECORDER\",\"magic\":\"%I64u\",\"dealTime\":%I64d,\"action\":\"%s\",\"side\":\"%s\",\"bulletNumber\":%d,\"ticket\":\"%I64u\",\"positionId\":\"%I64u\",\"volume\":%.2f,\"price\":%.5f,\"initialSl\":%.5f,\"finalSl\":%.5f,\"beActivated\":%s,\"protectionState\":\"%s\",\"timeToBeSeconds\":%d,\"mfePrice\":%.5f,\"maePrice\":%.5f,\"netProfit\":%.2f,\"reason\":\"%s\",\"campaignExitReason\":\"%s\"}",
      now_ms, ticket, JsonEscape(action), JsonEscape(report_campaign_id), seq, AccountInfoInteger(ACCOUNT_LOGIN), JsonEscape(trade_symbol), InpMagicNumber,
      now_ms, JsonEscape(action), JsonEscape(side), bullet_number, ticket, position_id, volume, price, initial_sl, final_sl,
      be_active ? "true" : "false", JsonEscape(protection_state), time_to_be_seconds, mfe_price, mae_price, net_profit, JsonEscape(reason), JsonEscape(campaign_context));
   QueueTelemetry("/api/ea/leg", json);
}


void QueueOrderReport(string action, string role, string order_type, int ladder_level, ulong ticket, double volume, double price, string reason)
{
   long now_ms = (long)TimeCurrent() * 1000;
   long seq = NextCampaignEventSequence();
   string event_id = (action == "PLACED" && ladder_level > 0 && campaign_id != "")
      ? StringFormat("%s-%s-%02d-PLACED", campaign_id, order_type, ladder_level)
      : StringFormat("%I64d-%I64u-%s", now_ms, ticket, action);
   string json = StringFormat(
      "{\"id\":\"%s\",\"campaignId\":\"%s\",\"eventSequence\":%I64d,\"account\":\"%I64d\",\"symbol\":\"%s\",\"version\":\"2.61\",\"strategy\":\"FIXED_LADDER_FLIGHT_RECORDER\",\"magic\":\"%I64u\",\"at\":%I64d,\"action\":\"%s\",\"role\":\"%s\",\"orderType\":\"%s\",\"ladderLevel\":%d,\"ticket\":\"%I64u\",\"volume\":%.2f,\"price\":%.5f,\"reason\":\"%s\"}",
      JsonEscape(event_id), JsonEscape(campaign_id), seq, AccountInfoInteger(ACCOUNT_LOGIN), JsonEscape(trade_symbol), InpMagicNumber,
      now_ms, JsonEscape(action), JsonEscape(role), JsonEscape(order_type), ladder_level, ticket, volume, price, JsonEscape(reason));
   QueueTelemetry("/api/ea/order", json);
}


void QueueBankDecision(string reason, double basket_profit)
{
   long now_ms=(long)TimeCurrent()*1000;
   long seq=NextCampaignEventSequence();
   string json=StringFormat("{\"id\":\"%I64d-%I64u\",\"campaignId\":\"%s\",\"eventSequence\":%I64d,\"account\":\"%I64d\",\"symbol\":\"%s\",\"version\":\"2.61\",\"strategy\":\"FIXED_LADDER_FLIGHT_RECORDER\",\"magic\":\"%I64u\",\"side\":\"%s\",\"basketProfit\":%.2f,\"peakBasketProfit\":%.2f,\"uniqueBulletsFired\":%d,\"newestTicket\":\"%I64u\",\"newestProfit\":%.2f,\"newestPeak\":%.2f,\"profitTargetEnabled\":%s,\"profitTargetMoney\":%.2f,\"reason\":\"%s\",\"at\":%I64d}",
      now_ms,newest_ticket,JsonEscape(campaign_id),seq,AccountInfoInteger(ACCOUNT_LOGIN),JsonEscape(trade_symbol),InpMagicNumber,JsonEscape(RecordedCampaignSide()),
      basket_profit,campaign_peak_floating,campaign_entries,newest_ticket,newest_leg_current_profit,newest_leg_peak_profit,
      campaign_profit_target_enabled?"true":"false",campaign_profit_target_money,JsonEscape(reason),now_ms);
   QueueTelemetry("/api/ea/bank",json);
}


void MaybeQueueScanReport()
{
   if(InpScanLogSeconds <= 0 || !momentum.ready) return;
   if(telemetry_count > (TELEMETRY_QUEUE_SIZE * 3) / 4) return;
   ulong now = GetTickCount64();
   ulong interval = (ulong)MathMax(1, InpScanLogSeconds) * 1000;
   if(last_scan_log_ms > 0 && now - last_scan_log_ms < interval) return;
   last_scan_log_ms = now;

   string block_reason = EntryBlockReason();
   if(block_reason == "" && CountOurPositions() > 0)
      block_reason = "FIXED ORIGINAL BUY AND SELL LADDERS BOTH REMAIN";
   else if(block_reason == "")
      block_reason = StringFormat("FIXED 8x8 LADDER ARMED | SPACING %.3f | FALLBACK %.3f | LOT %.2f | BE %.3f", BulletSpacing(), FallbackDistance(), EffectiveLot(), InpBreakEvenTriggerPrice);

   long now_ms = (long)TimeCurrent() * 1000;
   string json = StringFormat(
      "{\"id\":\"%I64d\",\"account\":\"%I64d\",\"symbol\":\"%s\",\"version\":\"2.61\",\"strategy\":\"FIXED_LADDER_FLIGHT_RECORDER\",\"magic\":\"%I64u\",\"momentumState\":\"%s\",\"watchDirection\":\"%s\",\"buyScore\":%d,\"sellScore\":%d,\"velocity1s\":%.5f,\"velocity3s\":%.5f,\"velocity10s\":%.5f,\"tickRateRatio\":%.3f,\"acceleration\":%.3f,\"bodyAtr\":%.3f,\"blockReason\":\"%s\",\"engineState\":\"%s\",\"buyPositions\":%d,\"sellPositions\":%d,\"pendingOrders\":%d,\"activeBullets\":%d}",
      now_ms, AccountInfoInteger(ACCOUNT_LOGIN), JsonEscape(trade_symbol), InpMagicNumber, JsonEscape(momentum.reason),
      JsonEscape(momentum.direction), momentum.buyScore, momentum.sellScore, momentum.velocity1, momentum.velocity3,
      momentum.velocity10, momentum.tickRatio, momentum.acceleration, momentum.bodyATR, JsonEscape(block_reason),
      JsonEscape(EngineStateText()), CountPositionsSide("BUY"), CountPositionsSide("SELL"), CountOurPending(), direction_leg_count);
   QueueTelemetry("/api/ea/scan", json);
}

void ProcessRailway()
{
   string base = TrimTrailingSlash(InpRailwayBaseUrl);
   if(base == "" || StringFind(base, "YOUR-SERVICE") >= 0 || InpBotToken == "CHANGE-ME") return;
   ulong now = GetTickCount64();
   ulong heartbeat_interval = (ulong)MathMax(3, InpHeartbeatSeconds) * 1000;
   ulong poll_interval = (ulong)MathMax(3, InpCommandPollSeconds) * 1000;

   // Heartbeat always has priority. A failed replay/order upload must never make the dashboard think MT5 is offline.
   if(last_heartbeat_ms == 0 || now - last_heartbeat_ms >= heartbeat_interval)
   {
      last_heartbeat_ms = now;
      SendHeartbeat();
      return;
   }

   if(now < next_http_allowed_ms) return;

   if(last_poll_ms == 0 || now - last_poll_ms >= poll_interval)
   {
      last_poll_ms = now;
      PollRailway();
      return;
   }
   if(queued_basket_json != "")
   {
      if(PostJson("/api/ea/basket", queued_basket_json)) queued_basket_json = "";
      return;
   }
   if(telemetry_count > 0)
      FlushOneTelemetry();
}


void SendHeartbeat()
{
   SyncCampaignCountersFromBulletMemory();
   MqlTick tick;
   SymbolInfoTick(trade_symbol, tick);
   int positions = CountOurPositions();
   int newest_age = newest_leg_open_time > 0 ? (int)(TimeCurrent() - newest_leg_open_time) : 0;
   heartbeat_sequence++;
   long now_ms=(long)TimeCurrent()*1000;
   long last_success_age = last_successful_http_ms > 0 ? (long)(GetTickCount64() - last_successful_http_ms) : -1;
   double daily_pnl = DailyRealisedProfit();
   double daily_remaining = DailyLossRemaining();
   bool daily_blocked = DailyLossBlocked();
   string json = StringFormat(
      "{\"account\":\"%I64d\",\"symbol\":\"%s\",\"version\":\"2.61\",\"magic\":\"%I64u\",\"strategy\":\"FIXED_LADDER_FLIGHT_RECORDER\",\"heartbeatSequence\":\"%I64u\",\"heartbeatSentAt\":%I64d,\"bid\":%.5f,\"ask\":%.5f,\"spreadPoints\":%.1f,\"terminalConnected\":%s,\"algoAllowed\":%s,\"autonomous\":%s,\"emergency\":%s,\"engineState\":\"%s\",\"campaignId\":\"%s\",\"campaignCurrentSide\":\"%s\",\"campaignBuyLegs\":%d,\"campaignSellLegs\":%d,\"campaignBuyBulletsFired\":%d,\"campaignSellBulletsFired\":%d,\"positionCount\":%d,\"pendingCount\":%d,\"totalLots\":%.2f,\"floatingProfit\":%.2f,\"peakBasketProfit\":%.2f,\"basketMae\":%.2f,\"positionsOpened\":%d,\"uniqueBulletsFired\":%d,\"newestTicket\":\"%I64u\",\"newestLegProfit\":%.2f,\"newestLegPeak\":%.2f,\"newestLegAgeSeconds\":%d,\"settingsVersion\":%d,\"profitTargetEnabled\":%s,\"profitTargetMoney\":%.2f,\"campaignSettingsVersion\":%d,\"campaignProfitTargetEnabled\":%s,\"campaignProfitTargetMoney\":%.2f,\"dailyLossEnabled\":%s,\"dailyLossMoney\":%.2f,\"dailyLossPnl\":%.2f,\"dailyLossRemaining\":%.2f,\"dailyLossBlocked\":%s,\"dailyLossResetAt\":%I64d,\"basketPeakProtectionEnabled\":%s,\"basketPeakActivationMoney\":%.2f,\"basketPeakGivebackMoney\":%.2f,\"basketPeakProtectionArmed\":%s,\"basketPeakProtectionFloor\":%.2f,\"beTriggerPrice\":%.3f,\"beBufferPrice\":%.3f,\"ladderAnchor\":%.5f,\"gridSpacing\":%.3f,\"fallbackDistance\":%.3f,\"telemetryQueueDepth\":%d,\"lastSuccessfulHttpAgeMs\":%I64d,\"lastHttpStatus\":\"%s\",\"lastEvent\":\"%s\",\"consumedCommandId\":\"%I64d\",\"lastCommandResult\":\"%s\"}",
      AccountInfoInteger(ACCOUNT_LOGIN), JsonEscape(trade_symbol), InpMagicNumber,heartbeat_sequence,now_ms,
      tick.bid, tick.ask, CurrentSpreadPoints(),
      TerminalInfoInteger(TERMINAL_CONNECTED) ? "true" : "false", MQLInfoInteger(MQL_TRADE_ALLOWED) ? "true" : "false",
      (remote_autonomous && !local_paused) ? "true" : "false", emergency_stopped ? "true" : "false",
      JsonEscape(EngineStateText()), JsonEscape(campaign_id), JsonEscape(RecordedCampaignSide()), buy_leg_count, sell_leg_count,
      campaign_buy_bullets_fired,campaign_sell_bullets_fired,positions, CountOurPending(), OurTotalLots(), BasketFloatingProfit(), campaign_peak_floating, campaign_worst_floating,
      campaign_entries,campaign_entries,newest_ticket, newest_leg_current_profit, newest_leg_peak_profit, newest_age,
      runtime_settings_version, runtime_profit_target_enabled ? "true" : "false", runtime_profit_target_money,
      campaign_settings_version, campaign_profit_target_enabled ? "true" : "false", campaign_profit_target_money,
      runtime_daily_loss_enabled ? "true" : "false", runtime_daily_loss_money, daily_pnl, daily_remaining, daily_blocked ? "true" : "false", runtime_daily_loss_reset_server_ms,
      campaign_peak_protection_enabled ? "true" : "false", campaign_peak_activation_money, campaign_peak_giveback_money,
      campaign_peak_protection_armed ? "true" : "false", campaign_peak_protection_floor,
      InpBreakEvenTriggerPrice, InpBreakEvenBufferPrice, ladder_anchor_price, BulletSpacing(), FallbackDistance(), telemetry_count,last_success_age,
      JsonEscape(last_http_status), JsonEscape(last_event), last_command_id, JsonEscape(last_command_result));
   PostJson("/api/ea/heartbeat", json);
}



void PollRailway()
{
   string base = TrimTrailingSlash(InpRailwayBaseUrl);
   string url = base + "/api/ea/control";
   char request_data[];
   ArrayResize(request_data, 0);
   char result[];
   string response_headers;
   string headers = "Accept: text/plain\r\nX-Bot-Token: " + InpBotToken + "\r\nConnection: close\r\n";
   ResetLastError();
   int status = WebRequest("GET", url, headers, InpWebTimeoutMilliseconds, request_data, result, response_headers);
   if(status != 200)
   {
      RegisterHttpFailure("control", status, CharArrayToString(result));
      return;
   }
   RegisterHttpSuccess("control");
   string body = CharArrayToString(result);
   remote_autonomous = ParseLineValue(body, "autonomous") == "true";
   bool remote_emergency = ParseLineValue(body, "emergency") == "true";
   int incoming_settings_version = (int)StringToInteger(ParseLineValue(body, "settings_version"));
   if(incoming_settings_version > runtime_settings_version)
   {
      double incoming_lot = StringToDouble(ParseLineValue(body, "fixed_lot"));
      if(incoming_lot > 0.0) runtime_fixed_lot = incoming_lot;
      runtime_use_equity_scaling = false;

      double incoming_target = StringToDouble(ParseLineValue(body, "profit_target_money"));
      runtime_profit_target_enabled = ParseLineValue(body, "profit_target_enabled") == "true";
      if(incoming_target > 0.0) runtime_profit_target_money = incoming_target;

      double incoming_peak_activation = StringToDouble(ParseLineValue(body, "basket_peak_activation_money"));
      double incoming_peak_giveback = StringToDouble(ParseLineValue(body, "basket_peak_giveback_money"));
      runtime_basket_peak_protection_enabled = ParseLineValue(body, "basket_peak_protection_enabled") == "true";
      if(incoming_peak_activation > 0.0) runtime_basket_peak_activation_money = incoming_peak_activation;
      if(incoming_peak_giveback > 0.0) runtime_basket_peak_giveback_money = incoming_peak_giveback;

      bool previous_daily_enabled = runtime_daily_loss_enabled;
      double previous_daily_money = runtime_daily_loss_money;
      long previous_reset_server_ms = runtime_daily_loss_reset_server_ms;
      double incoming_daily_money = StringToDouble(ParseLineValue(body, "daily_loss_money"));
      long incoming_reset_server_ms = StringToInteger(ParseLineValue(body, "daily_loss_reset_at_ms"));
      long server_now_ms = StringToInteger(ParseLineValue(body, "server_now_ms"));
      runtime_daily_loss_enabled = ParseLineValue(body, "daily_loss_enabled") == "true";
      if(incoming_daily_money > 0.0) runtime_daily_loss_money = incoming_daily_money;
      if(incoming_reset_server_ms >= 0)
      {
         runtime_daily_loss_reset_server_ms = incoming_reset_server_ms;
         if(incoming_reset_server_ms > 0 && server_now_ms > 0)
         {
            long broker_offset_seconds = (long)TimeCurrent() - server_now_ms / 1000;
            runtime_daily_loss_reset_at = (datetime)(incoming_reset_server_ms / 1000 + broker_offset_seconds);
         }
         else runtime_daily_loss_reset_at = 0;
      }
      cached_daily_pnl_ms = 0;
      runtime_settings_version = incoming_settings_version;
      SaveLocalSettings();

      bool daily_changed = previous_daily_enabled != runtime_daily_loss_enabled ||
                           MathAbs(previous_daily_money - runtime_daily_loss_money) > 0.0001 ||
                           previous_reset_server_ms != runtime_daily_loss_reset_server_ms;
      if(daily_changed && CountOurPositions() == 0 && CountOurPending() == 0)
      {
         immediate_rearm_pending = true;
         next_ladder_reason = "DAILY LOSS CONTROL UPDATED - IMMEDIATE REARM";
      }
      string target_text = runtime_profit_target_enabled ? StringFormat("target %.2f", runtime_profit_target_money) : "target OFF";
      string daily_text = runtime_daily_loss_enabled ? StringFormat("daily loss %.2f", runtime_daily_loss_money) : "daily loss OFF";
      string peak_text = runtime_basket_peak_protection_enabled
         ? StringFormat("peak protect %.2f / giveback %.2f (next campaign)", runtime_basket_peak_activation_money, runtime_basket_peak_giveback_money)
         : "peak protection OFF";
      last_event = "Dashboard settings applied: " + target_text + " | " + daily_text + " | " + peak_text;
   }
   long command_id = StringToInteger(ParseLineValue(body, "command_id"));
   string action = ParseLineValue(body, "action");
   if(remote_emergency) emergency_stopped = true;
   if(command_id > last_command_id && action != "NONE")
   {
      ExecuteRemoteCommand(action);
      last_command_id = command_id;
      last_command_result = last_event;
   }
}


void ExecuteRemoteCommand(string action)
{
   if(action == "PAUSE_EA" || action == "PAUSE_ADDING")
   {
      local_paused = true;
      CancelAllPending("dashboard pause");
      last_event = "Dashboard paused new entries";
   }
   else if(action == "RESUME_EA" || action == "RESUME_ADDING")
   {
      if(!emergency_stopped) local_paused = false;
      last_event = emergency_stopped ? "Reset emergency before resuming" : "Dashboard resumed EA";
   }
   else if(action == "CLOSE_BASKET" || action == "CLOSE_POSITION")
   {
      RequestBasketClose("DASHBOARD CLOSE");
   }
   else if(action == "EMERGENCY_STOP")
   {
      emergency_stopped = true;
      local_paused = true;
      RequestBasketClose("DASHBOARD EMERGENCY STOP");
   }
   else if(action == "RESET_EMERGENCY")
   {
      emergency_stopped = false;
      local_paused = false;
      last_event = "Emergency stop reset";
   }
   else if(action == "REBUILD_BRACKET")
   {
      CancelAllPending("dashboard rebuild bracket");
      immediate_rearm_pending = true;
      next_ladder_reason = "DASHBOARD REBUILD REQUEST";
      last_event = "Fixed two-sided ladder rebuild requested";
   }
   else last_event = "Unsupported dashboard command: " + action;
}

bool PostJson(string endpoint, string json)
{
   string base = TrimTrailingSlash(InpRailwayBaseUrl);
   string url = base + endpoint;
   char post[];
   char result[];
   string response_headers;
   StringToCharArray(json, post, 0, WHOLE_ARRAY, CP_UTF8);
   int size = ArraySize(post);
   if(size > 0 && post[size-1] == 0) ArrayResize(post, size - 1);
   string headers = "Content-Type: application/json\r\nAccept: application/json\r\nX-Bot-Token: " + InpBotToken + "\r\nConnection: close\r\n";
   ResetLastError();
   int status = WebRequest("POST", url, headers, InpWebTimeoutMilliseconds, post, result, response_headers);
   if(status < 200 || status >= 300)
   {
      RegisterHttpFailure(endpoint, status, CharArrayToString(result));
      return false;
   }
   RegisterHttpSuccess(endpoint);
   return true;
}


void RegisterHttpFailure(string endpoint, int status, string response)
{
   int mql_error=GetLastError();
   http_failure_count++;
   int exponent = http_failure_count < 5 ? http_failure_count : 5;
   int backoff_seconds = 2 * (1 << exponent);
   if(backoff_seconds > 60) backoff_seconds = 60;
   next_http_allowed_ms = GetTickCount64() + (ulong)backoff_seconds * 1000;
   string status_text=status<0 ? "WEBREQUEST FAILED" : StringFormat("HTTP %d",status);
   last_http_status = StringFormat("%s %s MQL %d; telemetry retry in %ds", endpoint, status_text, mql_error, backoff_seconds);
   Print("EVE Fixed Ladder v2.61 Railway ", last_http_status, " response=", response);
}


void RegisterHttpSuccess(string endpoint)
{
   http_failure_count = 0;
   next_http_allowed_ms = 0;
   last_successful_http_ms = GetTickCount64();
   last_http_status = endpoint + " OK";
}


void QueueBasketReport(string side, double realised)
{
   SyncCampaignCountersFromBulletMemory();
   ReconcileCampaignCountersFromHistory();
   UpdateCampaignStats();
   double reported_peak = MathMax(campaign_peak_floating, realised);
   double reported_giveback = MathMax(0.0, reported_peak - realised);
   long started_ms=(long)campaign_started_at*1000;
   long ended_ms=(long)TimeCurrent()*1000;
   long seq=NextCampaignEventSequence();
   queued_basket_json=StringFormat(
      "{\"id\":\"%s\",\"campaignId\":\"%s\",\"eventSequence\":%I64d,\"account\":\"%I64d\",\"symbol\":\"%s\",\"version\":\"2.61\",\"strategy\":\"FIXED_LADDER_FLIGHT_RECORDER\",\"magic\":\"%I64u\",\"settingsVersion\":%d,\"status\":\"CLOSED\",\"side\":\"%s\",\"entryTime\":%I64d,\"exitTime\":%I64d,\"durationSeconds\":%d,\"positionsOpened\":%d,\"uniqueBulletsFired\":%d,\"buyBullets\":%d,\"sellBullets\":%d,\"maximumSimultaneousPositions\":%d,\"lotPerLeg\":%.2f,\"anchorPrice\":%.5f,\"gridSpacing\":%.5f,\"fallbackDistance\":%.5f,\"beTriggerPrice\":%.5f,\"beBufferPrice\":%.5f,\"profitTargetEnabled\":%s,\"profitTargetMoney\":%.2f,\"basketPeakProtectionEnabled\":%s,\"basketPeakActivationMoney\":%.2f,\"basketPeakGivebackMoney\":%.2f,\"basketPeakProtectionArmed\":%s,\"basketPeakProtectionFloor\":%.2f,\"netProfit\":%.2f,\"peakBasketProfit\":%.2f,\"mae\":%.2f,\"profitGiveback\":%.2f,\"exitReason\":\"%s\",\"countingMethod\":\"UNIQUE_POSITION_IDENTIFIER\"}",
      JsonEscape(campaign_id),JsonEscape(campaign_id),seq,AccountInfoInteger(ACCOUNT_LOGIN),JsonEscape(trade_symbol),InpMagicNumber,campaign_settings_version,JsonEscape(side),
      started_ms,ended_ms,campaign_started_at>0?(int)(TimeCurrent()-campaign_started_at):0,campaign_entries,campaign_entries,
      campaign_buy_bullets_fired,campaign_sell_bullets_fired,campaign_max_positions,EffectiveLot(),ladder_anchor_price,BulletSpacing(),FallbackDistance(),
      InpBreakEvenTriggerPrice,InpBreakEvenBufferPrice,campaign_profit_target_enabled?"true":"false",campaign_profit_target_money,
      campaign_peak_protection_enabled?"true":"false",campaign_peak_activation_money,campaign_peak_giveback_money,
      campaign_peak_protection_armed?"true":"false",campaign_peak_protection_floor,realised,
      reported_peak,campaign_worst_floating,reported_giveback,JsonEscape(campaign_exit_reason));
}



double PendingPrice(string side)
{
   for(int i=OrdersTotal()-1; i>=0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0 || !OrderSelect(ticket) || !IsOurSelectedOrder()) continue;
      ENUM_ORDER_TYPE type = (ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
      if((side == "BUY" && type == ORDER_TYPE_BUY_STOP) || (side == "SELL" && type == ORDER_TYPE_SELL_STOP))
         return OrderGetDouble(ORDER_PRICE_OPEN);
   }
   return 0.0;
}

double AverageEntry()
{
   double weighted = 0.0, volume = 0.0;
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket) || !IsOurSelectedPosition()) continue;
      double lot = PositionGetDouble(POSITION_VOLUME);
      weighted += PositionGetDouble(POSITION_PRICE_OPEN) * lot;
      volume += lot;
   }
   return volume > 0.0 ? weighted / volume : 0.0;
}

string ParseLineValue(string body, string key)
{
   string marker = key + "=";
   int start = StringFind(body, marker);
   if(start < 0) return "";
   start += StringLen(marker);
   int end = StringFind(body, "\n", start);
   if(end < 0) end = StringLen(body);
   string value = StringSubstr(body, start, end - start);
   StringTrimLeft(value);
   StringTrimRight(value);
   return value;
}

string TrimTrailingSlash(string value)
{
   StringTrimLeft(value);
   StringTrimRight(value);
   while(StringLen(value) > 0 && StringSubstr(value, StringLen(value)-1, 1) == "/")
      value = StringSubstr(value, 0, StringLen(value)-1);
   return value;
}

string JsonEscape(string value)
{
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   StringReplace(value, "\r", " ");
   StringReplace(value, "\n", " ");
   return value;
}

void CreatePanel()
{
   CreateLabel(PANEL_PREFIX + "TITLE", 12, 18, "EVE FIXED LADDER v2.61", 12);
   CreateLabel(PANEL_PREFIX + "STATE", 12, 42, "STATE", 10);
   CreateLabel(PANEL_PREFIX + "MOMENTUM", 12, 62, "MOMENTUM", 9);
   CreateLabel(PANEL_PREFIX + "CAMPAIGN", 12, 82, "CAMPAIGN", 9);
   CreateLabel(PANEL_PREFIX + "HTTP", 12, 102, "RAILWAY", 8);
   CreateButton(PANEL_PREFIX + "PAUSE", 12, 126, 120, 28, "PAUSE EA", clrDarkOrange);
   CreateButton(PANEL_PREFIX + "CLOSE", 142, 126, 120, 28, "CLOSE ALL", clrSlateGray);
   CreateButton(PANEL_PREFIX + "STOP", 272, 126, 120, 28, "EMERGENCY", clrCrimson);
}

void UpdatePanel()
{
   if(!InpShowPanel) return;
   SetLabel(PANEL_PREFIX + "STATE", "STATE: " + EngineStateText());
   SetLabel(PANEL_PREFIX + "MOMENTUM", StringFormat("BUY %d/7 | SELL %d/7 | v1 %.3f | v3 %.3f | spread %.1f", momentum.buyScore, momentum.sellScore, momentum.velocity1, momentum.velocity3, CurrentSpreadPoints()));
   SetLabel(PANEL_PREFIX + "CAMPAIGN", StringFormat("%s | pos %d | P/L %.2f | Peak %.2f | floor %.2f", campaign_side, CountOurPositions(), BasketFloatingProfit(), campaign_peak_floating, campaign_peak_protection_floor));
   SetLabel(PANEL_PREFIX + "HTTP", "RAILWAY: " + last_http_status);
   SetButtonText(PANEL_PREFIX + "PAUSE", local_paused ? "RESUME EA" : "PAUSE EA");
   ChartRedraw();
}

void DeletePanel()
{
   for(int i=ObjectsTotal(0)-1; i>=0; i--)
   {
      string name = ObjectName(0, i);
      if(StringFind(name, PANEL_PREFIX) == 0) ObjectDelete(0, name);
   }
}

void CreateLabel(string name, int x, int y, string text, int size)
{
   if(ObjectFind(0, name) < 0) ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clrWhite);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, size);
   ObjectSetString(0, name, OBJPROP_FONT, "Arial");
   ObjectSetString(0, name, OBJPROP_TEXT, text);
}

void CreateButton(string name, int x, int y, int width, int height, string text, color background)
{
   if(ObjectFind(0, name) < 0) ObjectCreate(0, name, OBJ_BUTTON, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, width);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, height);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, background);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clrWhite);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 9);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
}

void SetLabel(string name, string text)
{
   if(ObjectFind(0, name) >= 0) ObjectSetString(0, name, OBJPROP_TEXT, text);
}

void SetButtonText(string name, string text)
{
   if(ObjectFind(0, name) >= 0) ObjectSetString(0, name, OBJPROP_TEXT, text);
}
