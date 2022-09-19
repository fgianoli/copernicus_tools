# -*- coding: utf-8 -*-

"""
/***************************************************************************
 LandCoverDownload
                                 A QGIS plugin
 This plugin allows to download the Copernicus Land Cover
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2020-12-28
        copyright            : (C) 2020 by Federico Gianoli, JRC
        email                : gianoli.federico@gmail.com
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

__author__ = 'Federico Gianoli, JRC'
__date__ = '2020-12-28'
__copyright__ = '(C) 2020 by Federico Gianoli, JRC'

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = '$Format:%H$'

# -*- coding: utf-8 -*-

"""
***************************************************************************
*                                                                         *
*   This program is free software; you can redistribute it and/or modify  *
*   it under the terms of the GNU General Public License as published by  *
*   the Free Software Foundation; either version 2 of the License, or     *
*   (at your option) any later version.                                   *
*                                                                         *
***************************************************************************
"""

from qgis.PyQt.QtCore import QCoreApplication, QSettings
from qgis.core import (QgsProcessing,
                       QgsProject,
                       QgsProcessingException,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterExtent,
                       QgsProcessingParameterFile,
                       QgsProcessingParameterEnum,
                       QgsProcessingParameterString,
                       QgsApplication)
from qgis import processing
import os
import sys
import urllib.request
import boto3
import botocore
import re

SELECTION = "v3.0.1"
BUCKET = 'vito.landcover.global'

class LandCoverDownload(QgsProcessingAlgorithm):

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    # INPUT = 'INPUT'
    # OUTPUT = 'OUTPUT'

    def tr(self, string):
        """
        Returns a translatable string with the self.tr() function.
        """
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return LandCoverDownload()

    def name(self):
        """
        Returns the algorithm name, used for identifying the algorithm. This
        string should be fixed for the algorithm, and must not be localised.
        The name should be unique within each provider. Names should contain
        lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return 'copernicuslandcover'

    def displayName(self):
        """
        Returns the translated algorithm name, which should be used for any
        user-visible display of the algorithm name.
        """
        return self.tr('Copernicus Land Cover Download')

    def group(self):
        """
        Returns the name of the group this algorithm belongs to. This string
        should be localised.
        """
        return self.tr('Copernicus Products Downloader')

    def groupId(self):
        """
        Returns the unique ID of the group this algorithm belongs to. This
        string should be fixed for the algorithm, and must not be localised.
        The group id should be unique within each provider. Group id should
        contain lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return 'Copernicus Products Downloader'

    def shortHelpString(self):
        """
        Returns a localised short helper string for the algorithm. This string
        should provide a basic description about what the algorithm does and the
        parameters and outputs associated with it..
        """
        return self.tr("Copernicus Land Cover Download.")

    s3objects = []
    products = []
    tiles = []
    years = []

    def initAlgorithm(self, config=None):

        def getProxiesConf():
            s = QSettings()  # getting proxy from qgis options settings
            proxyEnabled = s.value("proxy/proxyEnabled", "")
            proxyType = s.value("proxy/proxyType", "")
            proxyHost = s.value("proxy/proxyHost", "")
            proxyPort = s.value("proxy/proxyPort", "")
            proxyUser = s.value("proxy/proxyUser", "")
            proxyPassword = s.value("proxy/proxyPassword", "")
            if proxyEnabled == "true" and proxyType == 'HttpProxy':  # test if there are proxy settings
                proxyDict = {
                    "http": "%s:%s@%s:%s" % (proxyUser, proxyPassword, proxyHost, proxyPort),
                    "https": "%s:%s@%s:%s" % (proxyUser, proxyPassword, proxyHost, proxyPort)
                }
                return proxyDict
            else:
                return None
                
        self.s3client = boto3.client('s3', region_name='eu-central-1', config=botocore.config.Config(proxies=getProxiesConf(), signature_version=botocore.UNSIGNED))
        self.s3client.meta.events.register('choose-signer.s3.*', botocore.handlers.disable_signing) 
        paginator = self.s3client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=BUCKET)
        for page in pages:
            #print(page)
            for item in page["Contents"]:
                if item["Key"].startswith(SELECTION) and item["Size"] > 0:
                    key_parts = item["Key"].split("/")
                    year = key_parts[1]
                    item["tile"] = key_parts[2]
                    item["filename"] = key_parts[3]
                    pre = SELECTION+"_" + year
                    prod = re.search(pre + r'-(.*?)_EPSG-4326.tif', item["filename"]).group(1)
                    cat = prod.split("_")[0]
                    item["product"] = "_".join(prod.split("_")[1:])
                    item["year"] = key_parts[1] + "_" + cat
                    if not item["year"] in self.years:
                        self.years.append(item["year"])
                    if not item["tile"] in self.tiles:
                        self.tiles.append(item["tile"])
                    if not item["product"] in self.products:
                        self.products.append(item["product"])

                    #print (item["filename"])
                    self.s3objects.append(item)

        self.products.sort()
        self.years.sort()
        self.tiles.sort()

        self.addParameter(QgsProcessingParameterEnum('prodotto', 'Product', options=self.products, defaultValue=None, allowMultiple=True))
        self.addParameter(QgsProcessingParameterEnum('anno', 'Year', options=self.years, defaultValue=None, allowMultiple=True))
        self.addParameter(QgsProcessingParameterExtent('estensione', 'Extent', defaultValue=None, optional=True))
        self.addParameter(QgsProcessingParameterFile('Download directory', 'Download directory',
                                                     behavior=QgsProcessingParameterFile.Folder, optional=False,
                                                     defaultValue=None))


    def search_data(self, selezione_anni, selezione_tile, selezione_prodotti):
        filtered_objects = self.s3objects
        if selezione_prodotti:
            filtered_objects = list(filter(lambda item: item['product'] in selezione_prodotti, filtered_objects))
        if selezione_anni:
            filtered_objects = list(filter(lambda item: item['year'] in selezione_anni, filtered_objects))
        if selezione_tile:
            filtered_objects = list(filter(lambda item: item['tile'] in selezione_tile, filtered_objects))
        return filtered_objects
        

    def processAlgorithm(self, parameters, context, feedback):
        anni = [self.years[id_anno] for id_anno in parameters['anno']]
        prodotti = [self.products[id_prod] for id_prod in parameters['prodotto']]
        estensione = parameters['estensione']
        tiles_selection = []
        if estensione:
            grid_params = {
                "TYPE": 2,
                "EXTENT": "-180,180,-80,80",
                "HSPACING": 20,
                "VSPACING": 20,
                "CRS": "EPSG:4326",
                "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT
            }
            output1 = processing.run('native:creategrid', grid_params, context=context, feedback=None, is_child_algorithm=True)
            grid_layer = output1["OUTPUT"]
            select_params = {
                "INPUT": grid_layer,
                "EXTENT": estensione,
                "OUTPUT": QgsProcessing.TEMPORARY_OUTPUT
            }
            output2 = processing.run('native:extractbyextent', select_params, context=context, feedback=None, is_child_algorithm=True)
            grids_selected_layer = context.takeResultLayer(output2["OUTPUT"])
            print (grid_layer, grids_selected_layer)
            for feat in grids_selected_layer.getFeatures():
                lon = int(feat["left"])
                lat = int(feat["top"])
                lon_prefix = "E" if lon >= 0 else "W"
                lat_prefix = "N" if lat >= 0 else "S"
                tile_code = lon_prefix + str(abs(lon)).zfill(3) + lat_prefix + str(abs(lat)).zfill(2)
                tiles_selection.append(tile_code)

        url_to_download_list = self.search_data(anni, tiles_selection, prodotti)

        print(url_to_download_list)

        for d in url_to_download_list:
            # output = self.parameterAsFile(parameters,'Download directory',context) + os.path.basename(d)
            output = parameters['Download directory'] + '/' + d["filename"]
            self.s3client.download_file(BUCKET, d["Key"], output)

            feedback.pushInfo(d["filename"])
            if feedback.isCanceled():
                feedback.pushInfo("Terminated by user")
                return {}

        return {}