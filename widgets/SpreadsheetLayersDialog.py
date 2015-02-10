# -*- coding: utf-8 -*-
"""
/***************************************************************************
 SpreadsheetLayersPluginDialog
                                 A QGIS plugin
 Load layers from MS Excel and OpenOffice spreadsheets
                             -------------------
        begin                : 2014-10-30
        git sha              : $Format:%H$
        copyright            : (C) 2014 by Camptocamp
        email                : info@camptocamp.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import os
from exceptions import NotImplementedError
from collections import OrderedDict
from osgeo import ogr
from qgis.core import QgsVectorDataProvider
from qgis.gui import QgsMessageBar, QgsGenericProjectionSelector
from PyQt4 import QtCore, QtGui
from SpreadsheetLayers.util.gdal_util import GDAL_COMPAT
from ..ui.ui_SpreadsheetLayersDialog import Ui_SpreadsheetLayersDialog


class QOgrFieldModel(QtGui.QStandardItemModel):
    '''QOgrFieldModel provide a ListModel class
    for displaying OGR layers fields.
    
    OGR layer fields are read at creation or by setLayer().
    All data are stored in parent QtCore.QStandardItemModel object.
    No reference to any OGR related object is kept.
    '''

    def __init__(self, layer=None, parent=None):
        super(QOgrFieldModel, self).__init__(parent)
        self.setLayer(layer)

    def setLayer(self, layer):
        self.clear()
        if layer is None:
            return

        layerDefn = layer.GetLayerDefn()
        rows = layerDefn.GetFieldCount()
        for row in xrange(0, rows):
            fieldDefn = layerDefn.GetFieldDefn(row)
            fieldName = fieldDefn.GetNameRef().decode('UTF-8')
            item = QtGui.QStandardItem(fieldName)
            self.appendRow(item)


class QOgrTableModel(QtGui.QStandardItemModel):
    '''QOgrTableModel provide a TableModel class
    for displaying OGR layers data.
    
    OGR layer is read at creation or by setLayer().
    All data are stored in parent QtCore.QStandardItemModel object.
    No reference to any OGR related object is kept.
    '''
    def __init__(self, layer=None, parent=None, maxRowCount=None):
        super(QOgrTableModel, self).__init__(parent)
        self.maxRowCount = maxRowCount
        self.setLayer(layer)

    def setLayer(self, layer):
        self.clear()
        if layer is None:
            return

        layerDefn = layer.GetLayerDefn()

        rows = min(layer.GetFeatureCount(), self.maxRowCount)
        columns = layerDefn.GetFieldCount()

        for column in xrange(0, columns):
            fieldDefn = layerDefn.GetFieldDefn(column)
            fieldName = fieldDefn.GetNameRef().decode('UTF-8')
            if fieldDefn.GetType() == ogr.OFTInteger:
                fieldType = 'Integer'
            if fieldDefn.GetType() == ogr.OFTReal:
                fieldType = 'Real'
            if fieldDefn.GetType() == ogr.OFTString:
                fieldType = 'String'
            item = QtGui.QStandardItem(u"{}\n({})".format(fieldName, fieldType))
            self.setHorizontalHeaderItem(column, item)

        self.setRowCount(rows)
        self.setColumnCount(columns)
        for row in xrange(0, rows):
            for column in xrange(0, columns):
                layer.SetNextByIndex(row)
                feature = layer.GetNextFeature()
                item = self.createItem(layerDefn, feature, column)
                self.setItem(row, column, item)

    def createItem(self, layerDefn, feature, iField):
        fieldDefn = layerDefn.GetFieldDefn(iField)
        if fieldDefn.GetType() == ogr.OFTInteger:
            value = feature.GetFieldAsInteger(iField)
            hAlign = QtCore.Qt.AlignRight

        elif fieldDefn.GetType() == ogr.OFTReal:
            value = feature.GetFieldAsDouble(iField)
            hAlign = QtCore.Qt.AlignRight

        elif fieldDefn.GetType() == ogr.OFTString:
            value = feature.GetFieldAsString(iField).decode('UTF-8')
            hAlign = QtCore.Qt.AlignLeft

        else:
            value = feature.GetFieldAsString(iField).decode('UTF-8')
            hAlign = QtCore.Qt.AlignLeft

        item = QtGui.QStandardItem(unicode(value))
        item.setTextAlignment(hAlign | QtCore.Qt.AlignVCenter)
        return item


class SpreadsheetLayersDialog(QtGui.QDialog, Ui_SpreadsheetLayersDialog):

    pluginKey = 'SpreadsheetLayers'
    sampleRowCount = 20

    def __init__(self, parent=None):
        """Constructor."""
        super(SpreadsheetLayersDialog, self).__init__(parent)
        self.setupUi(self)

        self.dataSource = None
        self.layer = None
        self.sampleDatasource = None

        self.messageBar = QgsMessageBar(self)
        self.layout().insertWidget(0, self.messageBar)

        self.geometryBox.setChecked(False)
        self.sampleRefreshDisabled = False

    def info(self, msg):
        self.messageBar.pushMessage(msg, QgsMessageBar.INFO, 5)

    def warning(self, msg):
        self.messageBar.pushMessage(msg, QgsMessageBar.WARNING, 5)

    def filePath(self):
        return self.filePathEdit.text()

    def setFilePath(self, path):
        self.filePathEdit.setText(path)

    @QtCore.pyqtSlot(name='on_filePathEdit_editingFinished')
    def on_filePathEdit_editingFinished(self):
        self.afterOpenFile()

    @QtCore.pyqtSlot(name='on_filePathButton_clicked')
    def on_filePathButton_clicked(self):
        settings = QtCore.QSettings()
        s = QtGui.QFileDialog.getOpenFileName(
            self,
            self.tr("Choose a spreadsheet file to open"),
            settings.value(self.pluginKey + "/directory", "./"),
            self.tr("Spreadsheet files") + " (*.ods *.xls *.xlsx);;"
                + self.tr("GDAL Virtual Format") + " (*.vrt);;"
                + self.tr("All files") + " (* *.*)".format())
        if s == '':
            return
        settings.setValue(self.pluginKey + "/directory", os.path.dirname(s))
        self.filePathEdit.setText(s)

        self.afterOpenFile()

    def afterOpenFile(self):
        self.sampleRefreshDisabled = True

        self.openDataSource()
        self.updateSheetBox()
        self.readVrt()
        if self.dataSourceHeaders():
            self.headerBox.setChecked(True)
            self.headerBox.setEnabled(False)
            self.headerBox.setToolTip(self.tr(""))
        else:
            self.headerBox.setEnabled(True)

        self.sampleRefreshDisabled = False
        self.updateSampleView()

    def layerName(self):
        return self.layerNameEdit.text()

    def setLayerName(self, name):
        self.layerNameEdit.setText(name)

    def closeDataSource(self):
        if self.dataSource is not None:
            self.dataSource = None
            self.updateSheetBox()

    def openDataSource(self):
        self.closeDataSource()

        filePath = self.filePath()
        finfo = QtCore.QFileInfo(filePath)
        if not finfo.exists():
            return

        self.layerNameEdit.setText(finfo.completeBaseName())

        dataSource = ogr.Open(filePath, 0)
        if dataSource is None:
            self.messageBar.pushMessage('Could not open {}'.format(filePath),
                                        QgsMessageBar.WARNING, 5)
        self.dataSource = dataSource

    def dataSourceHeaders(self):
        if self.dataSource is None:
            return False
        driverName = self.dataSource.GetDriver().GetName()
        varName = 'OGR_{}_HEADERS'.format(driverName)
        value = os.environ.get(varName)
        self.ogrHeadersLabel.setText('{} = {}'.format(varName, value or ''))

        if value == 'FORCE':
            headers = True
        elif value == 'DISABLE':
            headers = False
        elif value is None or value == 'AUTO':
            if driverName in ['ODS']:
                headers = True
            elif driverName in ['XLS', 'XLSX']:
                headers = False
            else:
                raise NotImplementedError('OGR {} driver not yet implemented'.format(driverName))
        else:
            raise NotImplementedError('{} value {} not recognized'.format(varName, value))

        if headers == True:
            msg = self.tr("To enable this checkbox, set environment variable {} to {}"
                          .format(varName, 'DISABLE'))
            self.headerBox.setToolTip(msg)
            # self.ogrHeadersLabel.setStyleSheet("color: rgb(255, 0, 0)")
        else:
            self.headerBox.setToolTip('')
            # self.ogrHeadersLabel.setStyleSheet("color: rgb(0, 0, 0)")

        return headers

    def closeSampleDatasource(self):
        if self.sampleDatasource is not None:
            self.sampleDatasource = None

    def openSampleDatasource(self):
        self.closeSampleDatasource()

        filePath = self.samplePath()
        finfo = QtCore.QFileInfo(filePath)
        if not finfo.exists():
            return False
        dataSource = ogr.Open(filePath, 0)
        if dataSource is None:
            self.messageBar.pushMessage('Could not open {}'.format(filePath),
                                        QgsMessageBar.WARNING, 5)
        self.sampleDatasource = dataSource

    def sheet(self):
        return self.sheetBox.currentText()

    def setSheet(self, sheetName):
        self.sheetBox.setCurrentIndex(self.sheetBox.findText(sheetName))

    def updateSheetBox(self):
        self.sheetBox.clear()
        dataSource = self.dataSource
        if dataSource is None:
            return

        for i in xrange(0, dataSource.GetLayerCount()):
            layer = dataSource.GetLayer(i)
            self.sheetBox.addItem(layer.GetName(), layer)

    @QtCore.pyqtSlot(int)
    def on_sheetBox_currentIndexChanged(self, index):
        if index is None:
            self.layer = None
        else:
            self.layer = self.sheetBox.itemData(index)
        self.updateSampleView()

    def linesToIgnore(self):
        return self.linesToIgnoreBox.value()

    def setLinesToIgnore(self, value):
        self.linesToIgnoreBox.setValue(value)

    @QtCore.pyqtSlot(int)
    def on_linesToIgnoreBox_valueChanged(self, value):
        self.updateSampleView()

    def header(self):
        return self.headerBox.checkState() == QtCore.Qt.Checked

    @QtCore.pyqtSlot(int)
    def on_headerBox_stateChanged(self, state):
        self.updateSampleView()

    def offset(self):
        offset = self.linesToIgnore()
        if self.header() and not self.dataSourceHeaders():
            offset += 1
        return offset

    def setOffset(self, value):
        try:
            value = int(value)
        except:
            return False
        if self.header() and not self.dataSourceHeaders():
            value -= 1
        self.setLinesToIgnore(value)

    def limit(self):
        driverName = self.dataSource.GetDriver().GetName()
        if driverName in ['XLS']:
            return self._non_empty_rows
        return self.layer.GetFeatureCount() - self.offset()

    def sql(self):
        sql = ("SELECT * FROM {}"
               " LIMIT {} OFFSET {}"
               ).format(self.sheet(),
                        self.limit(),
                        self.offset())
        return sql

    def updateGeometry(self):
        if GDAL_COMPAT or self.offset() == 0:
            self.geometryBox.setEnabled(True)
            self.geometryBox.setToolTip('')
        else:
            self.geometryBox.setEnabled(False)
            msg = self.tr(u"Used GDAL version doesn't support VRT layers with sqlite dialect"
                          u" mixed with PointFromColumn functionality.\n"
                          u"For more informations, consult the plugin documentation.")
            self.geometryBox.setToolTip(msg)

    def geometry(self):
        return (self.geometryBox.isEnabled()
                and self.geometryBox.isChecked())

    def xField(self):
        return self.xFieldBox.currentText()

    def setXField(self, fieldName):
        self.xFieldBox.setCurrentIndex(self.xFieldBox.findText(fieldName))

    def yField(self):
        return self.yFieldBox.currentText()

    def setYField(self, fieldName):
        self.yFieldBox.setCurrentIndex(self.yFieldBox.findText(fieldName))

    def updateFieldBoxes(self, layer):
        if self.offset() > 0:
            # return
            pass

        if layer is None:
            self.xFieldBox.clear()
            return

        model = QOgrFieldModel(layer)

        xField = self.xField()
        yField = self.xField()

        self.xFieldBox.setModel(model)
        self.yFieldBox.setModel(model)

        self.xFieldBox.setCurrentIndex(self.xFieldBox.findText(xField))
        self.yFieldBox.setCurrentIndex(self.yFieldBox.findText(yField))

        if self.xField() != '' and self.yField() != '':
            return

        self.tryFields("longitude", "latitude")
        self.tryFields("lon", "lat")
        self.tryFields("x", "y")

    def tryFields(self, xName, yName):
        if self.xField() == '':
            for i in xrange(0, self.xFieldBox.count()):
                xField = self.xFieldBox.itemText(i)
                if xField.lower().find(xName.lower()) != -1:
                    self.xFieldBox.setCurrentIndex(i)
                    break;

        if self.yField() == '':
            for i in xrange(0, self.yFieldBox.count()):
                yField = self.yFieldBox.itemText(i)
                if yField.lower().find(yName.lower()) != -1:
                    self.yFieldBox.setCurrentIndex(i)
                    break;

    def crs(self):
        return self.crsEdit.text()

    def setCrs(self, crs):
        self.crsEdit.setText(crs)

    @QtCore.pyqtSlot(name='on_crsButton_clicked')
    def on_crsButton_clicked(self):
        dlg = QgsGenericProjectionSelector(self)
        dlg.setMessage('Select CRS')
        dlg.setSelectedAuthId(self.crsEdit.text())
        if dlg.exec_():
            self.crsEdit.setText(dlg.selectedAuthId())

    def updateSampleView(self):
        if self.sampleRefreshDisabled:
            return

        self.updateGeometry()

        if self.layer is not None:
            self.writeSampleVrt()
            self.openSampleDatasource()

        layer = None
        dataSource = self.sampleDatasource
        if dataSource is not None:
            for i in xrange(0, dataSource.GetLayerCount()):
                layer = dataSource.GetLayer(i)

        if layer is None:
            self.sampleView.setModel(None)
            return

        model = QOgrTableModel(layer, parent=self,
                               maxRowCount=self.sampleRowCount)
        self.sampleView.setModel(model)

        self.updateFieldBoxes(layer)

    def validate(self):
        try:
            if self.dataSource is None:
                raise ValueError(self.tr("Please select an input file"))

            if self.layer is None:
                raise ValueError(self.tr("Please select a sheet"))

            if self.xField == '':
                raise ValueError(self.tr("Please select an x field"))

            if self.yField == '':
                raise ValueError(self.tr("Please select an y field"))

        except ValueError as e:
            self.messageBar.pushMessage(unicode(e), QgsMessageBar.WARNING, 5)
            return False

        return True

    def vrtPath(self):
        return '{}.vrt'.format(self.filePath())

    def samplePath(self):
        return '{}.tmp.vrt'.format(self.filePath())

    def readVrt(self):
        if self.dataSource is None:
            return False

        vrtPath = self.vrtPath()
        if not os.path.exists(vrtPath):
            return False

        file = QtCore.QFile(vrtPath)
        if not file.open(QtCore.QIODevice.ReadOnly | QtCore. QIODevice.Text):
            self.warning("Impossible to open VRT file {}".format(vrtPath))
            return False

        self.geometryBox.setChecked(False)

        try:
            self.readVrtStream(file)
        except Exception:
            self.warning("An error occurs during existing VRT file loading")
            return False

        finally:
            file.close()

        # self.info("Existing VRT file has been loaded")
        return True

    def readVrtStream(self, file):
        stream = QtCore.QXmlStreamReader(file)

        stream.readNextStartElement()
        if stream.name() == "OGRVRTDataSource":

            stream.readNextStartElement()
            if stream.name() == "OGRVRTLayer":
                self.setLayerName(stream.attributes().value("name"))

                while stream.readNextStartElement():
                    if stream.name() == "SrcDataSource":
                        # do nothing : datasource should be already set
                        pass

                    elif stream.name() == "SrcLayer":
                        text = stream.readElementText()
                        self.setSheet(text)
                        self.setOffset(0)

                    elif stream.name() == "SrcSql":
                        text = stream.readElementText()
                        terms = text.split(" ")
                        previous = ''
                        for term in terms:
                            if previous.lower() == 'from':
                                self.setSheet(term)
                            if previous.lower() == 'offset':
                                self.setOffset(term)
                            previous = term

                    elif stream.name() == "GeometryType":
                        self.geometryBox.setChecked(True)

                    elif stream.name() == "LayerSRS":
                        text = stream.readElementText()
                        self.setCrs(text)

                    elif stream.name() == "GeometryField":
                        self.setXField(stream.attributes().value("x"))
                        self.setYField(stream.attributes().value("y"))

                    if not stream.isEndElement():
                        stream.skipCurrentElement()

            stream.skipCurrentElement()

        stream.skipCurrentElement()

    def getFields(self):
        fields = OrderedDict()
        rows = []

        self.layerDefn = self.layer.GetLayerDefn()

        # Load all values to detect types later
        self.layer.SetNextByIndex(self.offset())
        feature = self.layer.GetNextFeature()
        self._non_empty_rows = 0
        while feature is not None:
            values = []
            for iField in xrange(0, self.layerDefn.GetFieldCount()):
                values.append(feature.GetFieldAsString(iField).decode('UTF-8'))
            rows.append(values)

            # Manual detect end of xls files
            for value in values:
                if value != u'':
                    self._non_empty_rows = len(rows)
                    break

            feature = self.layer.GetNextFeature()

        # Select header line
        if self.header() and self.offset() >= 1:
            self.layer.SetNextByIndex(self.offset() - 1)
            feature = self.layer.GetNextFeature()

        for iField in xrange(0, self.layerDefn.GetFieldCount()):
            fieldDefn = self.layerDefn.GetFieldDefn(iField)
            src = fieldDefn.GetNameRef().decode('UTF-8')
            if self.header():
                if self.offset() == 0:
                    name = src
                else:
                    name = feature.GetFieldAsString(iField).decode('UTF-8')
            else:
                name = ''
            if name == '':
                name = 'Field{}'.format(iField + 1)

            fieldType = 'Integer'
            for iRow in xrange(0, len(rows)):
                value = rows[iRow][iField]
                try:
                    int(value)
                except:
                    fieldType = None
                    break

            if fieldType is None:
                fieldType = 'Real'
                for iRow in xrange(0, len(rows)):
                    value = rows[iRow][iField]
                    try:
                        float(value)
                    except:
                        fieldType = 'String'
                        break

            if fieldType is None:
                fieldType = 'String'

            fields[name] = {'src': src, 'name': name, 'type': fieldType}

        return fields

    def prepareVrt(self, sample=False):
        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QBuffer.ReadWrite)

        stream = QtCore.QXmlStreamWriter(buffer)
        stream.setAutoFormatting(True)
        stream.writeStartDocument()
        stream.writeStartElement("OGRVRTDataSource")

        stream.writeStartElement("OGRVRTLayer")
        stream.writeAttribute("name", self.layerName())

        stream.writeStartElement("SrcDataSource")
        stream.writeAttribute("relativeToVRT", "1")
        stream.writeCharacters(os.path.basename(self.filePath()))
        stream.writeEndElement()

        fields = self.getFields()

        if self.offset() > 0:
            stream.writeStartElement("SrcSql")
            stream.writeAttribute("dialect", "sqlite")
            stream.writeCharacters(self.sql())
            stream.writeEndElement()
        else:
            stream.writeStartElement("SrcLayer")
            stream.writeCharacters(self.sheet())
            stream.writeEndElement()

        for field in fields.itervalues():
            stream.writeStartElement("Field")
            stream.writeAttribute("name", field['name'])
            stream.writeAttribute("src", field['src'])
            stream.writeAttribute("type", field['type'])
            stream.writeEndElement()

        if (self.geometry() and not sample):
            stream.writeStartElement("GeometryType")
            stream.writeCharacters("wkbPoint")
            stream.writeEndElement()

            if self.crs():
                stream.writeStartElement("LayerSRS")
                stream.writeCharacters(self.crs())
                stream.writeEndElement()

            stream.writeStartElement("GeometryField")
            stream.writeAttribute("encoding", "PointFromColumns")
            stream.writeAttribute("x", fields[self.xField()]['src'])
            stream.writeAttribute("y", fields[self.yField()]['src'])
            stream.writeEndElement()

        stream.writeEndElement() # OGRVRTLayer
        stream.writeEndElement() # OGRVRTDataSource
        stream.writeEndDocument()

        buffer.reset()
        content = buffer.readAll()
        buffer.close

        return content

    def writeVrt(self):
        content = self.prepareVrt()

        vrtPath = self.vrtPath()
        file = QtCore.QFile(vrtPath)
        if file.exists():
            if file.open(QtCore.QIODevice.ReadOnly | QtCore. QIODevice.Text):
                oldContent = file.readAll()
                file.close()
                if content == oldContent:
                    return True

            msgBox = QtGui.QMessageBox()
            msgBox.setText("The file {} already exist.".format(vrtPath))
            msgBox.setInformativeText("Do you want to overwrite ?");
            msgBox.setStandardButtons(QtGui.QMessageBox.Ok | QtGui.QMessageBox.Cancel)
            msgBox.setDefaultButton(QtGui.QMessageBox.Cancel)
            ret = msgBox.exec_()
            if ret == QtGui.QMessageBox.Cancel:
                return False
            QtCore.QFile.remove(vrtPath)

        if not file.open(QtCore.QIODevice.ReadWrite | QtCore. QIODevice.Text):
            self.warning("Impossible to open VRT file {}".format(vrtPath))
            return False

        file.write(content)
        file.close()
        return True

    def writeSampleVrt(self):
        content = self.prepareVrt(True)

        vrtPath = self.samplePath()
        file = QtCore.QFile(vrtPath)
        if file.exists():
            QtCore.QFile.remove(vrtPath)

        if not file.open(QtCore.QIODevice.ReadWrite | QtCore. QIODevice.Text):
            self.warning("Impossible to open VRT file {}".format(vrtPath))
            return False

        file.write(content)
        file.close()
        return True

    def accept(self, *args, **kwargs):
        if not self.validate():
            return False

        if not self.writeVrt():
            return False

        return super(SpreadsheetLayersDialog, self).accept(*args, **kwargs)
