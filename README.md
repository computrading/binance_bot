# binance_bot
Trading bot for Binance API

# Binance 3 candles Trading Bot

## Overview

This project is a Python-based cryptocurrency trading bot designed to monitor a stable coin in the market in real time using data provided by Binance.

The bot implements a pattern detection strategy based on 3 o 4 candles figures to trigger a stop limit buy order. By now it only works on daily patterns detecting a rising (green) candle of a certain body size and generates buy orders after a sequence of 3 or 4 positive candles. After the stop limiy buy order is placed the bot keeps monitoring for the order to be executed and after that places a sell order according to a breakdown event using a dynamic linear regression to keep the sell order updated.

The concept of this bot is to overcome the use of classical indicators that are usually slow in generating signals.

The primary goal of this project is to provide a clear and extensible framework for studying algorithmic trading strategies using live market data.

Further implementations can work even with real time data to work with hourly or tick by tick strategies.

---

## Trading Strategy

The strategy, by now, is detecting a rising candle after a down trend. The bot waits for 3 green candles, or 3 rising hl2 if a red candle is in between, to place a stop limit buy order afterward.

If, during the waiting for the SL buy order to be executed, the price drops below a calculated level, the pattern will be considered violated and the SL buy order cancelled. 

After the SL order is confirmed as excuted, a SL sell order is placed and updated every day until breakdown occurs based on a short term linear regression trend or the previous daily candle's hl2  break.

-

## Features

- Real-time market data from Binance
- Profit and loss monitoring
- Modular architecture for future strategy enhancements
---

## Market Data

The bot operates using:

- Trading any stable coin paird with USDT pair: **BTCUSDT**
- Timeframe: Daily
- Real-time OHLC candle data
- Real-time market updates from Binance APIs
-- Not optimized for tiny decimals prices pairs
---

## Disclaimer

This software is provided for educational and research purposes only.

Cryptocurrency trading involves significant financial risk. Past performance does not guarantee future results. The author is not responsible for any financial losses resulting from the use of this software.

Always test thoroughly in a simulated environment before considering any form of live trading.

---

## Future Improvements

Possible future enhancements include:

- RSI confirmation filters
- Order book analysis
- Volume analysis
- Stop-loss and take-profit management
- Multi-asset support
- Historical backtesting engine
- Performance analytics dashboard

---
Refere to .env.example to configure required parameters such as Binance's API Key and Secret as well as the telegram bot and chat ID
---

START AND LOGGING

Execute this code from terminal with:

nohup python3 -u trade_one_3k_hl2_true_w_tg.py <CRYPTO_PAIR> > log_file 2>&1 &

This will execute the Python script in background and logging in log_file.
To receive the log in real time on a telegram bot chat:

 nohup ./telegram.sh <LOG_FILE> &

## License

This project is released under the MIT License.

Feel free to study, modify, and improve the code.
