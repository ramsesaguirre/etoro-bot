import settings
import etoro
from interfaces.advisor import ABCAdvisor
from strategy import StrategyManager
from my_logging import logger as logging
import datetime
from collections import deque


DEMO = True

class StrategyAdvisor(ABCAdvisor):

    def __init__(self, loop, **kwargs):
        super().__init__(loop, **kwargs)
        self.objloop = loop
        self.swop_buy = 0.0003
        self.total_marg = 0
        self.account_type = settings.account_type
        self.user_portfolio = {}
        self.instruments = {}
        self.instruments_rate = {}
        self.instruments_instrument = {}
        self.object_strategy = StrategyManager(0, '', buy=self.buy, sell=self.sell)
        self.object_strategy.start()
        self.ask = 0
        self.bid = 0
        self.exit_orders = []
        self.close_orders = {}
        self.fine_orders = {}
        self.fast_deals = {}
        self.watch_instuments_id = {}

    async def loop(self):
        datetime_obj = datetime.datetime.now()
        week_day = datetime_obj.weekday()
        if week_day == 6 and week_day == 5:
            return False
        await self.build_data()

    async def build_data(self):
        history_items = await etoro.get_history(count=2)
        self.close_orders = etoro.helpers.get_cache('close_orders', 0)
        self.fine_orders = etoro.helpers.get_cache('fine_orders', 0)
        if not self.close_orders:
            self.close_orders = {}
        if not self.fine_orders:
            self.fine_orders = {}
        if 'Candles' in history_items and history_items['Candles'] is not None:
            self.ask = history_items['Candles'][0]['Candles'][0]['Close']
            self.bid = self.ask + self.swop_buy
            self.object_strategy.tick(self.ask, self.bid, history_items['Candles'][0]['Candles'][0]['FromDate'])
        content = await etoro.login(self.session, only_info=True)
        if "AggregatedResult" not in content:
            content = await etoro.login(self.session, account_type=self.account_type)

        try:
            self.user_portfolio = content["AggregatedResult"]["ApiResponses"]["PrivatePortfolio"]["Content"][
                "ClientPortfolio"]
        except KeyError:
            logging.warning('Key Error')
            return False

        self.instruments_rate = etoro.helpers.get_cache('instruments_rate', (1/4))
        if not self.instruments_rate:
            self.instruments_rate = await etoro.instruments_rate(self.session)
            if not self.instruments_rate:
                return False
            etoro.helpers.set_cache('instruments_rate', self.instruments_rate)
        self.instruments_instrument = {instrument['InstrumentID']: instrument for instrument in
                                       self.instruments_rate['Instruments']}
        self.instruments_rate = {instrument['InstrumentID']: instrument for instrument in
                                 self.instruments_rate['Rates']}
        self.instruments = etoro.helpers.get_cache('instruments', 20)
        if not self.instruments:
            self.instruments = await etoro.instruments(self.session)
            if not self.instruments:
                return False
            etoro.helpers.set_cache('instruments', self.instruments)
        self.instruments = {instrument['InstrumentID']: instrument for instrument in
                            self.instruments['InstrumentDisplayDatas']}
        self.exit_orders = [order['InstrumentID'] for order in self.user_portfolio['ExitOrders']]
        await self.check_position()

    async def check_position(self):
        for position in self.user_portfolio['Positions']:
            if position['InstrumentID'] in self.instruments and position['InstrumentID'] in self.instruments_rate:
                position_id = position['PositionID']
                instrument_name = self.instruments[position['InstrumentID']]['SymbolFull']
                instrument_current_price = self.instruments_rate[position['InstrumentID']]['LastExecution']
                instrument_my_price = position['OpenRate']
                instrument_is_buy = position["IsBuy"]
                if instrument_name in self.close_orders:
                    try:
                        if (self.close_orders[instrument_name]['price'] > instrument_current_price and
                                    self.close_orders[instrument_name]['is_buy'] == True) or \
                            (self.close_orders[instrument_name]['price'] < instrument_current_price and
                                     self.close_orders[instrument_name]['is_buy'] == True):
                            self.message = 'Insrument {} now is fine'.format(instrument_name)
                            logging.debug('Insrument {} now is fine'.format(instrument_name))
                            del self.close_orders[instrument_name]
                            etoro.helpers.set_cache('close_orders', self.close_orders)
                    except KeyError:
                        logging.error('Key error {}'.format(instrument_name))
                if not instrument_is_buy:
                    fee_relative = (instrument_my_price*100/instrument_current_price) - 100
                    fee_absolute = instrument_my_price-instrument_current_price
                else:
                    fee_relative = (instrument_current_price*100/instrument_my_price) - 100
                    fee_absolute = instrument_current_price-instrument_my_price
                logging.debug('{}: {}'.format(instrument_name, fee_relative))
                if fee_relative < (-1*settings.fee_relative['first_case']) and position['InstrumentID'] not in self.exit_orders:
                    self.message = 'Firs case. I have tried your order. {}'.format(instrument_name)
                    await self.close_order(position_id, instrument_name=instrument_name,
                                     instrument_current_price=instrument_current_price)
                if fee_relative > settings.fee_relative['second_case'] and instrument_name not in self.fine_orders:
                    self.fine_orders[instrument_name] = fee_relative
                if instrument_name in self.fine_orders:
                    if fee_relative > self.fine_orders[instrument_name]:
                        self.fine_orders[instrument_name] = fee_relative
                    if (self.fine_orders[instrument_name] - fee_relative) >= settings.fee_relative['second_case']:
                        self.message = 'Second case. I have tried your order. {}'.format(instrument_name)
                        await self.close_order(position_id, instrument_name=instrument_name,
                                     instrument_current_price=instrument_current_price)
                        del self.fine_orders[instrument_name]


    async def fast_change_detect(self):
        if not self.instruments:
            return False
        lists = etoro.helpers.get_cache('watch_list', 10)
        if not lists:
            lists = await etoro.watch_list(self.session)
            if 'Watchlists' in lists:
                etoro.helpers.set_cache('watch_list', lists)
            else:
                return False
        for watch_list in lists['Watchlists']:
            for item_list in watch_list['Items']:
                if item_list['ItemType'] == 'Instrument' and item_list['ItemId'] not in self.watch_instuments_id:
                    self.watch_instuments_id[item_list['ItemId']] = deque([])
        if not self.instruments_rate:
            self.instruments_rate = await etoro.instruments_rate(self.session)
            if not self.instruments_rate:
                return False
            self.instruments_rate = {instrument['InstrumentID']: instrument for instrument in
                                     self.instruments_rate['Rates']}
        for key in self.instruments_rate:
            if key in self.watch_instuments_id:
                self.watch_instuments_id[key].append(self.instruments_rate[key]['LastExecution'])
                if len(self.watch_instuments_id[key]) > 10:
                    changing = self.watch_instuments_id[key][0]/self.watch_instuments_id[key][-1]
                    if changing > 1:
                        changing = (1.0 - 1/changing)*-1
                    else:
                        changing = 1.0 - changing
                    if changing > settings.fast_grow_points or changing < (-1*settings.fast_grow_points):
                        logging.info('Changing for {} is {}'.format(self.instruments[key]['SymbolFull'], str(changing)))
                        await self.fast_deal(changing, key)
                        # self.message = 'Changing {} is {}'.format(self.instruments[key]['SymbolFull'],
                        #                                       str(changing))
                    self.watch_instuments_id[key].popleft()

    async def fast_deal(self, changing, key):
        if not self.fast_deals:
            self.fast_deals = etoro.helpers.get_cache('fast_deals')
        if not self.fast_deals:
            self.fast_deals = {}
        if key in self.fast_deals:
            return False
        min_amount = self.instruments_instrument[key]['MinPositionAmount']
        min_leverage = self.instruments_instrument[key]['Leverages'][0]
        if changing > 0:
            await self.buy(key, self.instruments_rate[key]['LastExecution'], min_amount, min_leverage)
        else:
            await self.sell(key, self.instruments_rate[key]['LastExecution'], min_amount, min_leverage)


    async def check_fast_orders(self):
        if 'Positions' in self.user_portfolio:
            for position in self.user_portfolio['Positions']:
                if position['InstrumentID'] in self.fast_deals:
                    date_time_current = self.fast_deals[position['InstrumentID']]['date']
                    dif_time = datetime.datetime.now() - date_time_current
                    if dif_time.seconds > 5:
                        await etoro.close_order(self.session, position['PositionID'], demo=DEMO)
                        del self.fast_deals[position['InstrumentID']]


    async def make_business(self, key, last_execution, is_buy, min_amount, min_leverage):
        response = await etoro.order(self.session, key, last_execution, IsBuy=is_buy,
                                     Amount=min_amount, Leverage=min_leverage)
        if 'Token' in response:
            self.fast_deals[key] = {
                'id': key,
                'date': datetime.datetime.now().strftime("%s")
            }
            etoro.helpers.set_cache('fast_deals', self.fast_deals)
        else:
            await etoro.login(self.session, account_type=self.account_type)
            await self.make_business(key, last_execution, is_buy, min_amount, min_leverage)
        return response

    async def buy(self, key, last_execution, min_amount, min_leverage):
        await self.make_business(key, last_execution, True, min_amount, min_leverage)

    async def sell(self, key, last_execution, min_amount, min_leverage):
        await self.make_business(key, last_execution, False, min_amount, min_leverage)

    async def close_order(self, position_id, instrument_name='', instrument_current_price=0.0):
        await etoro.close_order(self.session, position_id, demo=DEMO)
        for position in self.user_portfolio['Positions']:
            if position['InstrumentID'] in self.instruments and position['InstrumentID'] in self.instruments_rate:
                if instrument_name == self.instruments[position['InstrumentID']]['SymbolFull']:
                    self.close_orders[instrument_name] = {'price': instrument_current_price,
                                                          'is_buy': position["IsBuy"]}
                    etoro.helpers.set_cache('close_orders', self.close_orders)