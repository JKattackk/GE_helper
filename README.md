# GE_helper
Work in progress tool for monitoring item prices on the old school runescape grand exchange.
Uses the osrs wiki's real-time prices api to retrieve item prices.
Price history is stored locally in an SQLite db (there is currently no deletion of old data).
Uses pyqt6 for a basic GUI and uses plotly to display item price history.

Has adjustable settings for which items are trackced accessible in the config page:
Minumum by limit value (price * buy limit)
Minimum value per  hour (price * hourly volume)
Minimum hourly volume
Maximum price

Also has an alert system looking for localised price drops combined with volume spikes
Some settings for the alerts are also adjustable in the config page:
Minimum low price change
Minimum low volume change
Minimum high price change
Minimum high volume change
Only high price (Only drops in high price are considered for alerts)


