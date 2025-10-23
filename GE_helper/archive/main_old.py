import sys
import os.path
import json
import requests
import sqlite3
import time
from PyQt6.QtSql import *
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from output import Ui_MainWindow
import webbrowser

itemListURL = "https://chisel.weirdgloop.org/gazproj/gazbot/os_dump.json"
priceHistory5mURL = url = "https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep=5m&id="
headers = {
    'User-Agent': 'GE price trend tracking wip discord @kat6541'
}
filteredItemListValues = "(id INTEGER PRIMARY KEY, itemName, buyLimit, lowPrice, highPrice, value, highAlch, lowVolume, highVolume, lowPriceChange, highPriceChange, lowVolumeChange, highVolumeChange)"
filteredItemDataFile = os.path.expanduser("~/Documents/GEHelper/filteredItemData.json")
filterConfigFile = os.path.expanduser("~/Documents/GEHelper/filterConfig.json")
itemLookupURL = "https://www.ge-tracker.com/item/"

## default item filter valuues
def_minBuyLimitValue = 2000000
def_minHourlyThroughput = 5000000
def_minHourlyVolume = 1000
def_maxPrice = 120000000

def_priceChangePercent = -10

def_volChangePercent = 400

priceHistoryUpdateRunning = False

class Worker(QRunnable):
    """Worker thread."""
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    @pyqtSlot()
    def run(self):
        """Initialise the runner function with passed args, kwargs."""
        self.fn(*self.args, **self.kwargs)

class signals(QObject):
    newPriceUpdate = pyqtSignal()
    newAlerts = pyqtSignal()

class MainWindow(QMainWindow):
    def __init__(self):
        self.threadpool = QThreadPool()
        thread_count = self.threadpool.maxThreadCount()
        print(f"Multithreading with maximum {thread_count} threads")
        database = sqlite3.connect('itemData.db')
        cursor = database.cursor()
        cursor.execute("ATTACH 'priceHistory5m.db' AS priceHistory5m")
        cursor.execute("CREATE TABLE if NOT EXISTS filteredDB" + filteredItemListValues)
        self.signals = signals()
        
        global watchCount 
        watchCount = self.updateItemList()

        worker = Worker(self.getPriceHistory)
        self.threadpool.start(worker)
        itemLoopWorker = Worker(self.itemPriceLoop)  
        self.threadpool.start(itemLoopWorker)

        super(MainWindow, self).__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.ui.changePageWidget.setCurrentIndex(0)
        self.ui.ItemTableButton.setChecked(True)
        self.ui.ItemAlertsButton.toggled['bool'].connect(self.onAlertsButtonToggled)
        self.ui.ViewGraphButton.toggled['bool'].connect(self.onGraphButtonToggled)
        self.ui.ItemTableButton.toggled['bool'].connect(self.onTableButtonToggled)
        self.ui.tableRefreshButton.pressed.connect(self.onTableRefreshButtonToggled)
        self.ui.ControlPanelButton.toggled['bool'].connect(self.onControlPanelButtonToggled)
        self.ui.AlertTable.itemDoubleClicked.connect(self.onAlertClick)
        self.updateItemTable(watchCount)


    def onTableButtonToggled(self):
        self.ui.changePageWidget.setCurrentIndex(0)
    def onGraphButtonToggled(self):
        self.ui.changePageWidget.setCurrentIndex(1)
        self.updateItemTable(watchCount)
    def onTableRefreshButtonToggled(self):
        self.updateItemTable(watchCount)
    def onAlertsButtonToggled(self):
        self.ui.changePageWidget.setCurrentIndex(2)
    def setRefreshButton(self):
        print("ya")
    def onControlPanelButtonToggled(self):
        self.ui.changePageWidget.setCurrentIndex(3)
    def onAlertClick(self, item):
        if item.column() == 0:
            itemID = item.text()
            url = itemLookupURL + itemID
            webbrowser.open(url, new=2)


    def writeConfig(self, newConfig):
        with open(filterConfigFile, "w") as f:
            json.dump(newConfig, f)
        print("config saved")

    def updateItemList(self):
        # creates the filtered item list from itemDataFile using the filtering values above
        database = sqlite3.connect('itemData.db')
        if os.path.exists(filterConfigFile):
            with open(filterConfigFile, "r") as f:
                filterConfig = json.load(f)
            minBuyLimitValue = filterConfig.get('minBuyLimitValue')
            minHourlyThroughput = filterConfig.get('minHourlyThroughput')
            minHourlyVolume = filterConfig.get('minHourlyVolume')
            maxPrice = filterConfig.get('maxPrice')
        else:
            minBuyLimitValue = def_minBuyLimitValue
            minHourlyThroughput = def_minHourlyThroughput
            minHourlyVolume = def_minHourlyVolume
            maxPrice = def_maxPrice
            filterConfig = {"minBuyLimitValue": minBuyLimitValue, "minHourlyThroughput": minHourlyThroughput, "minHourlyVolume": minHourlyVolume, "maxPrice": maxPrice}
            self.writeConfig(filterConfig)

        itemList = json.loads(requests.get(itemListURL, headers = headers).text)
        tempItemList = {}
        watchCount = 0
        for item in itemList.keys():
            if isinstance(itemList[item], int) or isinstance(itemList[item], float):
                print("invalid item")
            else:
                try:
                    limitValue = itemList[item].get("limit") * itemList[item].get("price")
                except:
                    limitValue = 0
                try:
                    hourlyThroughput = itemList[item].get("volume") * itemList[item].get("price")
                except:
                    hourlyThroughput = 0
                try:
                    itemPrice = itemList[item].get("price")
                except:
                    itemPrice = 0
                if (hourlyThroughput > minHourlyThroughput and limitValue > minBuyLimitValue and itemPrice < maxPrice and itemList[item].get("volume") > minHourlyVolume):
                    tempItemList[item] = itemList[item]
                    watchCount = watchCount + 1
        ## trimming database to remove items that are no longer being tracked
        cursor = database.cursor()
        cursor.execute("ATTACH 'priceHistory5m.db' AS priceHistory5m")
        response = cursor.execute('select id from filteredDB')
        rows = response.fetchall()
        for row in rows:
            if not str(row[0]) in tempItemList.keys():
                cursor.execute("DELETE from filteredDB where id = ?", row)
                database.commit()
                print("deleted ID: ?", row[0])

        for item in tempItemList:
            id = tempItemList[item].get('id')
            name = tempItemList[item].get('name').replace(" ", "_")
            limit = tempItemList[item].get('limit')
            value = tempItemList[item].get('value')
            highAlch = tempItemList[item].get('highalch')

            cursor.execute("SELECT itemName FROM filteredDB WHERE id = ?", (id,))
            data=cursor.fetchone()
            if data is None:
                cursor.execute("INSERT INTO filteredDB (id, itemName, buyLimit, value, highAlch) VALUES(?, ?, ?, ?, ?);", (id, name, limit, value, highAlch))
            else:
                cursor.execute("UPDATE filteredDB SET value = ?", (value,))
        database.commit()
        return watchCount

    def updateItemTable(self, itemCount):
        database = sqlite3.connect('itemData.db')
        cursor = database.cursor()
        cursor.execute("ATTACH 'priceHistory5m.db' AS priceHistory5m")
        tableRow = 0
        self.ui.itemTable.clearContents()
        self.ui.itemTable.setRowCount(itemCount)
        for row in cursor.execute("SELECT * FROM filteredDB"):
            item_id = QTableWidgetItem()
            item_id.setData(2, row[0])
            item_name = QTableWidgetItem(row[1].replace("_", " "))
            item_limit = QTableWidgetItem()
            item_limit.setData(2, row[2])

            item_low = QTableWidgetItem()
            item_low.setData(2, row[3])
            item_high = QTableWidgetItem()
            item_high.setData(2, row[4])
            
            item_value = QTableWidgetItem()
            item_value.setData(2, row[5])
            item_highAlch = QTableWidgetItem()
            item_highAlch.setData(2, row[6])

            item_lv = QTableWidgetItem()
            item_lv.setData(2, row[7])
            item_hv = QTableWidgetItem()
            item_hv.setData(2, row[8])

            item_lpc = QTableWidgetItem()
            item_lpc.setData(2, row[9])
            item_hpc = QTableWidgetItem()
            item_hpc.setData(2, row[10])

            item_lvc = QTableWidgetItem()
            item_lvc.setData(2, row[11])
            item_hvc = QTableWidgetItem()
            item_hvc.setData(2, row[12])

            self.ui.itemTable.setItem(tableRow, 0, item_id)
            self.ui.itemTable.setItem(tableRow, 1, item_name)
            self.ui.itemTable.setItem(tableRow, 2, item_limit)
            self.ui.itemTable.setItem(tableRow, 3, item_low)
            self.ui.itemTable.setItem(tableRow, 4, item_high)
            self.ui.itemTable.setItem(tableRow, 5, item_value)
            self.ui.itemTable.setItem(tableRow, 6, item_highAlch)
            self.ui.itemTable.setItem(tableRow, 7, item_lv)
            self.ui.itemTable.setItem(tableRow, 8, item_hv)
            self.ui.itemTable.setItem(tableRow, 9, item_lpc)
            self.ui.itemTable.setItem(tableRow, 10, item_hpc)
            self.ui.itemTable.setItem(tableRow, 11, item_lvc)
            self.ui.itemTable.setItem(tableRow, 12, item_hvc)
            tableRow = tableRow + 1

    def getPriceHistory(self):
        global priceHistoryUpdateRunning
        priceHistoryUpdateRunning = True
        database = sqlite3.connect('itemData.db')
        cursor = database.cursor()
        cursor.execute("ATTACH 'priceHistory5m.db' AS priceHistory5m")
        idList = cursor.execute("SELECT id FROM filteredDB").fetchall()
        for id in idList:
            tableName = "priceHistory5m.itemID" + ''.join(str(value) for value in id)
            command = "SELECT name FROM priceHistory5m.sqlite_master WHERE type='table' AND name='itemID" + ''.join(str(value) for value in id) + "';"
            query = cursor.execute(command)
            if query.fetchone() == None:
                command = "CREATE TABLE " + tableName + "(timeStamp, avgLowPrice, avgHighPrice, lowPriceVolume, highPriceVolume)"
                cursor.execute(command)
                response = json.loads(requests.get(priceHistory5mURL + ''.join(str(value) for value in id), headers=headers).text).get('data')
                for item in response:
                    timestamp = item.get('timestamp')
                    avgHighPrice = item.get('avgHighPrice')
                    avgLowPrice = item.get('avgLowPrice')
                    highPriceVolume = item.get('highPriceVolume')
                    lowPriceVolume = item.get('highPriceVolume')
                    cursor.execute("INSERT INTO " + tableName + "(timeStamp, avgLowPrice, avgHighPrice, lowPriceVolume, highPriceVolume) VALUES(?, ?, ?, ?, ?);", (timestamp, avgLowPrice, avgHighPrice, lowPriceVolume, highPriceVolume))
                database.commit()
                time.sleep(1)
        
        priceHistoryUpdateRunning = False
    
    def getOneDayAvg(self, database, tableName, lastUpdate):
        startTime = lastUpdate - 60*60*24
        cursor = database.cursor()

        command = "SELECT avgLowPrice FROM " + tableName + " WHERE timeStamp > ? AND avgLowPrice is NOT NULL;"
        lowPrices = cursor.execute(command, (startTime,)).fetchall()
        avgLowPrice = 0
        if len(lowPrices) > 0:
            for price in lowPrices:
                avgLowPrice = avgLowPrice + price[0]
            avgLowPrice = avgLowPrice / len(lowPrices)
        
        command = "SELECT avgHighPrice FROM " + tableName + " WHERE timeStamp > ? AND avgHighPrice is NOT NULL;"
        highPrices = cursor.execute(command, (startTime,)).fetchall()
        avgHighPrice = 0
        if len(highPrices) > 0:
            for price in highPrices:
                avgHighPrice = avgHighPrice + price[0]
            avgHighPrice = avgHighPrice / len(highPrices)

        command = "SELECT lowPriceVolume FROM " + tableName + " WHERE timeStamp > ? AND lowPriceVolume is NOT NULL;"
        lowVolumes = cursor.execute(command, (startTime,)).fetchall()
        avgLowVol = 0
        if len(lowVolumes) > 0:
            for vol in lowVolumes:
                avgLowVol = avgLowVol + vol[0]
            avgLowVol = avgLowVol / len(lowVolumes)

        command = "SELECT highPriceVolume FROM " + tableName + " WHERE timeStamp > ? AND highPriceVolume is NOT NULL;"
        highVolumes = cursor.execute(command, (startTime,)).fetchall()
        avgHighVol = 0
        if len(highVolumes) > 0:
            for vol in lowVolumes:
                avgHighVol = avgHighVol + vol[0]
            avgHighVol = avgHighVol / len(highVolumes)
        return {"avgLowPrice": avgLowPrice, "avgHighPrice": avgHighPrice, "avgLowVol": avgLowVol, "avgHighVol": avgHighVol}
    def updateAlerts(self, alerts):
        self.ui.AlertTable.clearContents()
        self.ui.AlertTable.setRowCount(len(alerts))
        tableRow = 0
        for entry in alerts:
            item_id = QTableWidgetItem()
            item_id.setData(2, entry.get("id"))
            print(entry.get("id"))
            item_name = QTableWidgetItem(entry.get("name").replace("_", " "))

            item_lowPriceChange = QTableWidgetItem()
            item_lowPriceChange.setData(2, entry.get("lowPriceChange"))
            item_highPriceChange = QTableWidgetItem()
            item_highPriceChange.setData(2, entry.get("highPriceChange"))

            item_lowVolChange = QTableWidgetItem()
            item_lowVolChange.setData(2, entry.get("lowVolChange"))
            item_highVolChange = QTableWidgetItem()
            item_highVolChange.setData(2, entry.get("highVolChange"))

            self.ui.AlertTable.setItem(tableRow, 0, item_id)
            self.ui.AlertTable.setItem(tableRow, 1, item_name)

            self.ui.AlertTable.setItem(tableRow, 2, item_lowPriceChange)
            self.ui.AlertTable.setItem(tableRow, 3, item_highPriceChange)
            self.ui.AlertTable.setItem(tableRow, 4, item_lowVolChange)
            self.ui.AlertTable.setItem(tableRow, 5, item_highVolChange)
            tableRow = tableRow + 1


    def itemPriceLoop(self):
        database = sqlite3.connect('itemData.db')
        cursor = database.cursor()
        cursor.execute("ATTACH 'priceHistory5m.db' AS priceHistory5m")
        time.sleep(1)
        lastUpdate = -1
        while True:
            if (int(time.time()) - int(lastUpdate)) > 510 or lastUpdate == -1:
                alerts = []
                url = "https://prices.runescape.wiki/api/v1/osrs/5m"
                response = json.loads(requests.get(url, headers = headers).text)
                lastUpdate = response.get('timestamp')
                print(response.get('timestamp'))
                print(time.time())
                trackedIDs = cursor.execute('select id from filteredDB').fetchall()
                for id in trackedIDs:
                    id_str = ''.join(str(value) for value in id)
                    command = "SELECT name FROM priceHistory5m.sqlite_master WHERE type='table' AND name='itemID" + id_str + "';"
                    query = cursor.execute(command)
                    if not query.fetchone() == None:
                        if (not response.get('data').get(id_str) == None):
                            tableName = "priceHistory5m.itemID" + id_str
                            command = "SELECT timeStamp from " + tableName + " ORDER BY timeStamp DESC LIMIT 1"
                            try:
                                lastEntryTime = int(cursor.execute(command).fetchone()[0])
                            except:
                                lastEntryTime = 0
                            if not lastEntryTime == lastUpdate:
                                avgLowPrice = response.get('data').get(id_str).get('avgLowPrice')
                                avgHighPrice = response.get('data').get(id_str).get('avgHighPrice')
                                lowPriceVolume = response.get('data').get(id_str).get('lowPriceVolume')
                                highPriceVolume = response.get('data').get(id_str).get('highPriceVolume')
                                command = "INSERT INTO " + tableName + "(timeStamp, avgLowPrice, avgHighPrice, lowPriceVolume, highPriceVolume) VALUES(?, ?, ?, ?, ?);"
                                cursor.execute(command, (lastUpdate, avgLowPrice, avgHighPrice, lowPriceVolume, highPriceVolume))
                                
                                 ##  price and volume change metrics, alerts.
                                oneDayAvg = self.getOneDayAvg(database, tableName, lastUpdate)
                                try:
                                    lowPriceChange = (avgLowPrice / oneDayAvg.get("avgLowPrice"))*100 - 100
                                except:
                                    lowPriceChange = 0
                                try:
                                    highPriceChange = (avgHighPrice / oneDayAvg.get("avgHighPrice"))*100 - 100
                                except:
                                    highPriceChange = 0
                                try:
                                    lowVolChange = (lowPriceVolume / oneDayAvg.get("avgLowVol"))*100 - 100
                                except:
                                    lowVolChange = 0
                                try:
                                    highVolChange = (highPriceVolume / oneDayAvg.get("avgHighVol"))*100 - 100
                                except:
                                    highVolChange = 0
                                command = "UPDATE filteredDB set lowPrice = ?, highPrice = ?, lowVolume = ?, highVolume = ?, lowPriceChange = ?, highPriceChange = ?, lowVolumeChange = ?, highVolumeChange = ? WHERE id = ?"
                                cursor.execute(command, (avgLowPrice, avgHighPrice, lowPriceVolume, highPriceVolume, lowPriceChange, highPriceChange, lowVolChange, highVolChange, id[0]))
                                if (lowPriceChange < def_priceChangePercent or highPriceChange < def_priceChangePercent) and (lowVolChange > def_volChangePercent or highVolChange > def_volChangePercent):
                                    command = "SELECT itemName FROM filteredDB WHERE id = ?"
                                    name = cursor.execute(command, id).fetchone()[0]
                                    alerts.append({"id": id[0], "name": name, "lowPriceChange": lowPriceChange, "highPriceChange": highPriceChange, "lowVolChange": lowVolChange, "highVolChange": highVolChange})
                                    print("?: low price ?%, high price ?%, low volume ?%, high volume ?%", (name, lowPriceChange, highPriceChange, lowVolChange, highVolChange))
                self.updateAlerts(alerts) 
                database.commit()
                time.sleep(60)
                
if __name__ == "__main__":
    app = QApplication(sys.argv)
    ## load style
    with open("theme.qss") as theme:
        theme_str = theme.read()
    
    app.setStyleSheet(theme_str)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())

    