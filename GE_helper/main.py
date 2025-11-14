import sys
import os.path
import json
import sqlite3
import time
import requests
from plotly.subplots import make_subplots
import plotly.graph_objects as go
import pandas as pd
import traceback
from PyQt6.QtSql import *
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineWidgets import QWebEngineView
from output import Ui_MainWindow
from PyQt6.QtGui import QColor
from PyQt6.QtGui import QFontDatabase
#pyuic6 -o .\GE_helper\output.py .\GE_helper\newUI.ui
script_dir = os.path.dirname(os.path.abspath(__file__))

itemListURL = "https://chisel.weirdgloop.org/gazproj/gazbot/os_dump.json"
priceHistory5mURL = url = "https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep=5m&id="
itemLookupURL = "https://www.ge-tracker.com/item/"

headers = {
    'User-Agent': 'GE price trend tracking wip discord @kat6541'
}

filteredItemListValues = "(id INTEGER PRIMARY KEY, itemName, buyLimit, lowPrice, highPrice, value, highAlch, lowVolume, highVolume, lowPriceChange, highPriceChange, lowVolumeChange, highVolumeChange, timestamp, tracked)"
alertConfigFile = "cfg/alertConfig.json"
filterConfigFile = "cfg/filterConfig.json"

## default item filter valuues
def_minBuyLimitValue = 2000000
def_minHourlyThroughput = 5000000
def_minHourlyVolume = 1000
def_maxPrice = 10000000

def_priceChangePercent = 100
def_volChangePercent = 100
alertColumnWidths = [256, 64, 64, 50, 64, 64, 128]


def textToInt(string):
    try:
        return int(string)
    except:
        endChar = string[-1].casefold()
        string = string[:-1]
        num = int(string)
        match endChar:
            case 'm':
                num = num * 10^6
            case 'k':
                num = num * 10^3
            case 'b':
                num = num * 10^9
            case default:
                raise ValueError

class alert:
    def __init__(self, id, name, lowPriceChange, highPriceChange, lowVolChange, highVolChange, timestamp):
        self.id = id
        self.name = name
        self.lowPriceChange = lowPriceChange
        self.highPriceChange = highPriceChange
        self.lowVolChange = lowVolChange
        self.highVolChange = highVolChange
        self.timestamp = timestamp
    
class signals(QObject):
    #indicates new price update. Includes unix timestamp of last update
    newUpdate = pyqtSignal(int)
    #indicates new alerts.  
    newAlerts = pyqtSignal(list)
    newItem = pyqtSignal(str)
    graphReady = pyqtSignal(object)
    #GUI updating requests
    progBarChange = pyqtSignal(int)
    loadTextChange = pyqtSignal(str)
    buildDBComplete = pyqtSignal()
    priceHistoryComplete = pyqtSignal()
    killPriceLoop = pyqtSignal()

class Worker(QRunnable):
    """Worker thread."""
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.is_killed = False

    @pyqtSlot()
    def run(self):
        """Initialise the runner function with passed args, kwargs."""
        try:
            print(f"Worker starting: {self.fn.__name__}")
            self.is_killed = False
            self.fn(*self.args, **self.kwargs)
            print(f"Worker completed: {self.fn.__name__}")
        except Exception as e:
            print(f"Error in worker thread: {e}")
            traceback.print_exc()

    def kill(self):
        self.is_killed = True

class MainWindow(QMainWindow):
    def __init__(self):
        print("starting __init__...")
        try:
            print("Constructing MainWindow instance", id(self))
            self.threadpool = QThreadPool()
            thread_count = self.threadpool.maxThreadCount()
            print(f"Multithreading with maximum {thread_count} threads")

            super(MainWindow, self).__init__()
            self.ui = Ui_MainWindow()
            self.ui.setupUi(self)

            #graph setup
            try:
                #prevents window flicker during startup
                self.ui.mainGraph.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
                # calling winId() forces creation of the native window handle
                _ = self.ui.mainGraph.winId()
                try:
                    self.ui.mainGraph.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
                    self.ui.mainGraph.setStyleSheet("background: transparent;")
                    self.ui.mainGraph.page().setBackgroundColor(QColor(0,0,0,0))
                except Exception as e:
                    print("Warning: couldn't set webengine transparency:", e)
            except Exception:
                pass


            self.signals = signals()
            self.loopWorker = Worker(self.itemPriceLoop)
            self.ui.history_list.setVisible(False)

            #alert setup
            for i in range(len(alertColumnWidths)):
                self.ui.alert_list.setColumnWidth(i, alertColumnWidths[i])
            
            #config page setup
            self.ui.rebuild_db_button.clicked.connect(self.rebuildDBPressed)
            self.signals.progBarChange.connect(self.updateBar)
            self.signals.loadTextChange.connect(self.updateLoadingText)
            self.signals.buildDBComplete.connect(self.startPriceLoop)
            self.signals.priceHistoryComplete.connect(self.priceHistoryComplete)
            self.signals.killPriceLoop.connect(self.loopWorker.kill)
            self.signals.newItem.connect(self.newItem)
            self.signals.graphReady.connect(self.updatePlot)
            self.ui.history_button.toggled['bool'].connect(self.onHistoryButtonToggle)
            self.signals.newAlerts.connect(self.updateAlerts)

            #graph page setup
            self.ui.graph_button.clicked.connect(self.onGraphButtonToggle)
            self.ui.config_button.clicked.connect(self.onConfigButtonToggle)
            self.updateConfigBoxes()
            self.ui.main_stack_widget.setCurrentIndex(0)
            #confirm that database exists and build has been finished
            if os.path.isfile("database.db"):
                try:
                    database = sqlite3.connect('database.db')
                    cursor = database.cursor()
                    cursor.execute("SELECT id FROM filteredDB WHERE tracked=FALSE")
                    result = cursor.fetchall()
                    database.close()
                    if len(result) == 0:
                        self.startPriceLoop()
                        self.activateMainWindow()
                        #self.updateGraphPage("2")
                        self.ui.main_stack_widget.setCurrentIndex(1)
                        self.ui.graph_button.setChecked(True)
                    else:
                        worker = Worker(self.buildPriceHistoryDB)
                        self.threadpool.start(worker)
                except Exception as e:
                    print(e)
                else:
                    print("no DB exists")
                print("MainWindow.__init__ complete")
            print("__init__ ended...")
        except Exception as e:
            print(f"Critical error in MainWindow.__init__: {e}")
            import traceback
            traceback.print_exc()
            raise

    def newItem(self, itemID):
        print("new item received:", itemID)
        self.updateGraphPage(itemID)
    def updatePlot(self, fig):
        html = fig.to_html(include_plotlyjs='cdn')
        try:
            self.ui.mainGraph.setHtml(html, QUrl())
        except Exception as e:
            print(f"Error updating plot: {e}")

    def startPriceLoop(self):
        #self.threadpool.start(self.loopWorker)
        print("Starting price loop")
    def activateMainWindow(self):
        print("Setting up main window")
        self.ui.graph_button.setEnabled(True)
        self.ui.search_bar.setEnabled(True)
        alerts = []
        alerts.append(alert(2, "cobonal", "-50", "-20", "-40", "2000", "123992"))
        self.signals.newAlerts.emit(alerts)
        print("main window setup complete")
    
    def updateGraphPage(self, itemID):
        print(f"updating graph with {itemID}")
        try:
            database = sqlite3.connect('database.db')
            cursor = database.cursor()
            command = f"SELECT id, itemName, buyLimit, lowPrice, highPrice, value, highAlch, lowVolume, highVolume FROM filteredDB WHERE id={itemID}"
            result = cursor.execute(command).fetchall()
            database.close()
            values = {}
            for i in range(len(result[0])):
                values[i] = str(result[0][i])
            self.ui.id_label.setText(values[0])
            self.ui.name_label.setText(values[1])
            self.ui.limit_label.setText(values[2])
            self.ui.avgSell_label.setText(values[3])
            self.ui.avgBuy_label.setText(values[4])
            self.ui.highAlch_label.setText(values[6])
            self.ui.sellVol_label.setText(values[7])
            self.ui.buyVol_label.setText(values[8])
            worker = Worker(self.plotPrep, itemID)
            self.threadpool.start(worker)
        except Exception as e:
            print(e)

    def updateBar(self, progress):
        self.ui.progressBar.setValue(progress)
    def updateLoadingText(self, text):
        self.ui.loading_label.setText(text)
    def onGraphButtonToggle(self):
        self.ui.main_stack_widget.setCurrentIndex(1)
        print("test")
    def onConfigButtonToggle(self):
        worker = Worker(self.updateConfigBoxes)
        self.threadpool.start(worker)
        self.ui.main_stack_widget.setCurrentIndex(0)
    def onHistoryButtonToggle(self, state):
        if state:
            self.ui.historyList.setVisible(True)
        else:
            self.ui.historyList.setVisible(False)
    
    def updateAlerts(self, alerts):
        for alert in alerts:
            self.ui.alert_list.insertRow(0)
            self.ui.alert_list.setItem(0, 0, QTableWidgetItem(f"{alert.id}: {alert.name} "))
            self.ui.alert_list.setItem(0, 1, QTableWidgetItem(alert.highPriceChange))
            self.ui.alert_list.setItem(0, 2, QTableWidgetItem(alert.lowPriceChange))
            self.ui.alert_list.setItem(0, 4, QTableWidgetItem(alert.highVolChange))
            self.ui.alert_list.setItem(0, 5, QTableWidgetItem(alert.lowVolChange))
            self.ui.alert_list.setItem(0, 7, QTableWidgetItem(alert.timestamp))

    def rebuildDBPressed(self):
        worker = Worker(self.buildDB)
        self.threadpool.start(worker)

    def updateConfigBoxes(self):
        try:
            with open(filterConfigFile, "r") as f:
                    filterConfig = json.load(f)
                    minBuyLimitValue = filterConfig.get('minBuyLimitValue')
                    minHourlyThroughput = filterConfig.get('minHourlyThroughput')
                    minHourlyVolume = filterConfig.get('minHourlyVolume')
                    maxPrice = filterConfig.get('maxPrice')
        except:
            print("no filter config exists.  Using default values")
            minBuyLimitValue = def_minBuyLimitValue
            minHourlyThroughput = def_minHourlyThroughput
            minHourlyVolume = def_minHourlyVolume
            maxPrice = def_maxPrice
        
        self.ui.mblv_line.setPlaceholderText(str(minBuyLimitValue))
        self.ui.mhvt_line.setPlaceholderText(str(minHourlyThroughput))
        self.ui.mhv_line.setPlaceholderText(str(minHourlyVolume))
        self.ui.mp_line.setPlaceholderText(str(maxPrice))

        try:
            with open(alertConfigFile, "r") as f:
                    alertConfig = json.load(f)
                    minLowPriceChange = alertConfig.get("minLowPriceChange")
                    minHighPriceChange = alertConfig.get("minHighPriceChange")
                    minLowVolChange = alertConfig.get("minLowVolChange")
                    minHighVolChange = alertConfig.get("minHighVolChange")
        except:
            print("no alert config exists.  Using default values")
            minLowPriceChange = def_priceChangePercent
            minHighPriceChange = def_priceChangePercent
            minLowVolChange = def_volChangePercent
            minHighVolChange = def_volChangePercent
        
        self.ui.mlpc_line.setPlaceholderText(str(minLowPriceChange))
        self.ui.mhpc_line.setPlaceholderText(str(minHighPriceChange))
        self.ui.mlvc_line.setPlaceholderText(str(minLowVolChange))
        self.ui.mhvc_line.setPlaceholderText(str(minHighVolChange))  

    def buildPriceHistoryDB(self):
        print("price history build starting...")
        self.ui.splash_stacked.setCurrentIndex(1)
        self.signals.progBarChange.emit(0)
        self.signals.loadTextChange.emit("Building price history")
        #self.ui.loading_label.setText()

        database = sqlite3.connect("database.db")
        cursor = database.cursor()
        cursor.execute("ATTACH 'priceHistory5m.db' AS priceHistory5m")
        cursor.execute("SELECT id FROM filteredDB WHERE tracked=FALSE")
        itemList = cursor.fetchall()
        totalCount = len(itemList)
        count = 0
        for id in itemList:
            count = count + 1
            self.signals.progBarChange.emit(int((count/totalCount)*100))
            self.signals.loadTextChange.emit(f"Getting price history for item {count}/{totalCount}")
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
                    lowPriceVolume = item.get('lowPriceVolume')
                    cursor.execute("INSERT INTO " + tableName + "(timeStamp, avgLowPrice, avgHighPrice, lowPriceVolume, highPriceVolume) VALUES(?, ?, ?, ?, ?);", (timestamp, avgLowPrice, avgHighPrice, lowPriceVolume, highPriceVolume))
                
                oneDayAvg = self.getOneDayAvg(database, tableName, timestamp)
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
                cursor.execute("UPDATE filteredDB set lowPrice=?, highPrice=?, lowVolume=?, highVolume=?, lowPriceChange=?, highPriceChange=?, lowVolumeChange=?, highVolumeChange=?, timestamp=?, tracked=? WHERE id=?", 
                    (avgLowPrice, avgHighPrice, lowPriceVolume, highPriceVolume, lowPriceChange, highPriceChange, lowVolChange, highVolChange, timestamp, True, id[0]))
                database.commit()
                time.sleep(1)
        database.close()
        print("price history build complete...")
        self.signals.priceHistoryComplete.emit()

    def itemPriceLoop(self):
        lastUpdate = -1
        while True:
            if self.is_killed:
                break
            if (int(time.time()) - int(lastUpdate)) > 510:
                database = sqlite3.connect('itemData.db')
                cursor = database.cursor()
                cursor.execute("ATTACH 'priceHistory5m.db' AS priceHistory5m")
                alerts = []
                url = "https://prices.runescape.wiki/api/v1/osrs/5m"
                response = json.loads(requests.get(url, headers = headers).text)
                lastUpdate = response.get('timestamp')
                print(response.get('timestamp'))
                print(time.time())
                trackedIDs = cursor.execute('SELECT id from filteredDB WHERE tracked=TRUE').fetchall()
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
                                    alerts.append({"id": id[0], "name": name, "lowPriceChange": lowPriceChange, "highPriceChange": highPriceChange, "lowVolChange": lowVolChange, "highVolChange": highVolChange, "timestamp": lastUpdate})
                                    print("?: low price ?%, high price ?%, low volume ?%, high volume ?%", (name, lowPriceChange, highPriceChange, lowVolChange, highVolChange))
                self.updateAlerts(alerts)
                database.commit()
                database.close()
                time.sleep(60)

    def buildDB(self):
        print("buildDB starting...")
        try:
            #set page to splash screen
            self.signals.killPriceLoop.emit()
            self.ui.splash_stacked.setCurrentIndex(1)
            self.signals.progBarChange.emit(0)
            self.signals.loadTextChange.emit("Building filtered list")
            #determine filter values
            if self.ui.mblv_line.text() == '':
                minBuyLimitValue = self.ui.mblv_line.placeholderText()
            else:
                minBuyLimitValue = self.ui.mblv_line.text()
            if self.ui.mp_line.text() == '':
                maxPrice = self.ui.mp_line.placeholderText()
            else:
                maxPrice = self.ui.mp_line.text()
            if self.ui.mhvt_line.text() == '':
                minHourlyThroughput = self.ui.mhvt_line.placeholderText()
            else:
                minHourlyThroughput = self.ui.mhvt_line.text()
            if self.ui.mhv_line.text() == '':
                minHourlyVolume = self.ui.mhv_line.placeholderText()
            else:
                minHourlyVolume = self.ui.mhv_line.text()
            
            try:
                minBuyLimitValue = textToInt(minBuyLimitValue)
                maxPrice = textToInt(maxPrice)
                minHourlyThroughput = textToInt(minHourlyThroughput)
                minHourlyVolume = textToInt(minHourlyVolume)
            except Exception as e:
                print("invalid input: ")
                print(e)
                return False
            
            filterConfig = {"minBuyLimitValue": minBuyLimitValue, "minHourlyThroughput": minHourlyThroughput, "minHourlyVolume": minHourlyVolume, "maxPrice": maxPrice}
            with open(filterConfigFile, "w") as f:
                json.dump(filterConfig, f)
            print("filter config saved")
            try:
                minBuyLimitValue = filterConfig.get('minBuyLimitValue')
                minHourlyThroughput = filterConfig.get('minHourlyThroughput')
                minHourlyVolume = filterConfig.get('minHourlyVolume')
                maxPrice = filterConfig.get('maxPrice')
            except Exception as e:
                print("invalid filter config")
                raise e
            #delete prior DB if exists
            while os.path.isfile("database.db"):
                try:
                    os.remove("database.db")
                    print("deleted database.db")
                except Exception as e:
                    print(e)
                    time.sleep(1)
            while os.path.isfile("priceHistory5m.db"):
                try:
                    os.remove("priceHistory5m.db")
                    print("deleted priceHistory5m.db")
                except Exception as e:
                    print(e)
                    time.sleep(1)

            #build filtered item list
            itemList = json.loads(requests.get(itemListURL, headers = headers).text)
            tempItemList = {}
            watchCount = 0
            for item in itemList.keys():
                if isinstance(itemList[item], int) or isinstance(itemList[item], float):
                    print("invalid item")
                else:
                    try:
                        limitValue = itemList[item].get("limit") * itemList[item].get("price")
                        hourlyThroughput = itemList[item].get("volume") * itemList[item].get("price")
                        itemPrice = itemList[item].get("price")
                        if (hourlyThroughput > minHourlyThroughput and limitValue > minBuyLimitValue and itemPrice < maxPrice and itemList[item].get("volume") > minHourlyVolume):
                            tempItemList[item] = itemList[item]
                            watchCount = watchCount + 1
                    except:
                        print("error in entry for item {item}", item)

            
            database = sqlite3.connect("database.db")
            cursor = database.cursor()
            cursor.execute("CREATE TABLE if NOT EXISTS filteredDB" + filteredItemListValues)
            for item in tempItemList:
                id = tempItemList[item].get('id')
                name = tempItemList[item].get('name').replace(" ", "_")
                limit = tempItemList[item].get('limit')
                value = tempItemList[item].get('value')
                highAlch = tempItemList[item].get('highalch')
                cursor.execute("INSERT INTO filteredDB (id, itemName, buyLimit, value, highAlch, tracked) VALUES(?, ?, ?, ?, ?, ?);", (id, name, limit, value, highAlch, False))
            database.commit()
            database.close()
            ### placeholder for updating watchcount in gui
            self.signals.buildDBComplete.emit()
            self.buildPriceHistoryDB()
        except Exception as e:
            print(f"Error in buildDB: {e}")
            import traceback
            traceback.print_exc()

    def priceHistoryComplete(self):
        self.signals.progBarChange.emit(100)
        self.signals.loadTextChange.emit("you shouldn't be here")
        self.updateConfigBoxes()
        self.ui.splash_stacked.setCurrentIndex(0)
        self.activateMainWindow()

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
    
    def plotPrep(self, itemID):
        database = sqlite3.connect('database.db')
        cursor = database.cursor()
        cursor.execute("ATTACH 'priceHistory5m.db' AS priceHistory5m")
        command = "SELECT name FROM priceHistory5m.sqlite_master WHERE type='table' AND name='itemID" + itemID + "';"
        query = cursor.execute(command)
        if not query.fetchone() == None:
            tableName = "priceHistory5m.itemID" + itemID
            command = "SELECT timestamp, avgHighPrice, avgLowPrice FROM " + tableName
            query = cursor.execute(command)
            dat = query.fetchall()
            fig = make_subplots(rows=2, cols=1, row_heights=[0.8, 0.2], shared_xaxes=True, vertical_spacing=0.05)
            time = [point[0] for point in dat]
            high = [point[1] for point in dat]
            low = [point[2] for point in dat]

            fig.add_trace(go.Scatter(x=time, y=high, mode='lines+markers',marker_color="orange"), row=1, col=1)
            fig.add_trace(go.Scatter(x=time, y=low, mode='lines+markers',marker_color="dodgerblue"), row=1, col=1)
            

            command = "SELECT lowPriceVolume, highPriceVolume FROM " + tableName
            query = cursor.execute(command)
            dat = query.fetchall()
            database.close()
            high = [point[0] for point in dat]
            low = [point[1] for point in dat]
            fig.add_trace(go.Histogram(histfunc="sum", x=time, y=high, marker_color="orange", xbins=dict(size=1000)), row=2, col=1)
            fig.add_trace(go.Histogram(histfunc="sum", x=time, y=low, marker_color="dodgerblue", xbins=dict(size=1000)), row=2, col=1)

            fig.update_layout(bargap=0.1, bargroupgap=0.05, showlegend = False, margin=dict(l=8, r=8, t=8, b=8),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', autosize=True)

            self.signals.graphReady.emit(fig)
        else:
            print(f"no table for {itemID}")
            database.close()

    def closeEvent(self, event):
        print("Window close event triggered!")
        super().closeEvent(event)
        print(event)

    def showEvent(self, event):
        print("MainWindow.showEvent()")
        traceback.print_stack(limit=10)
        super().showEvent(event)

    def hideEvent(self, event):
        print("MainWindow.hideEvent()")
        traceback.print_stack(limit=10)
        super().hideEvent(event)

    def changeEvent(self, event):
        # captures minimize/restore and other state changes
        if event.type() == QEvent.Type.WindowStateChange:
            print(f"MainWindow.changeEvent: state={self.windowState()}")
        super().changeEvent(event)

if __name__ == "__main__":
    try:
        if QApplication.instance() is None:
            app = QApplication(sys.argv)
        else:
            app = QApplication.instance()
        
        ## load style
        with open("theme.qss") as theme:
            theme_str = theme.read()
        app.setStyleSheet(theme_str)

        if not hasattr(app, "main_window"):
            app.main_window = MainWindow()
        window = app.main_window

        print("About to show window")
        window.show()
        
        
        # debug: print top-level widgets now and in 1s
        def dump_toplevels():
            tops = QApplication.topLevelWidgets()
            print("Top-level widgets:", [type(w).__name__ for w in tops])
            print("QApplication.instance():", QApplication.instance())
        dump_toplevels()
        QTimer.singleShot(1000, dump_toplevels)
        print("Window shown, about to exec()")
        app.exec()
    except Exception as e:
            print(f"Error in startup: {e}")
            import traceback
            traceback.print_exc()

