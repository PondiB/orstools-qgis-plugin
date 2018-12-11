# -*- coding: utf-8 -*-
"""
/***************************************************************************
 ORStools
                                 A QGIS plugin
 falk
                              -------------------
        begin                : 2017-02-01
        git sha              : $Format:%H$
        copyright            : (C) 2017 by Nils Nolde
        email                : nils.nolde@gmail.com
 ***************************************************************************/

 This plugin provides access to the various APIs from OpenRouteService
 (https://openrouteservice.org), developed and
 maintained by GIScience team at University of Heidelberg, Germany. By using
 this plugin you agree to the ORS terms of service
 (https://openrouteservice.org/terms-of-service/).

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import os.path
import webbrowser

from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QVariant

from qgis.core import (QgsWkbTypes,
                       QgsFeature,
                       QgsProcessing,
                       QgsFields,
                       QgsField,
                       QgsProcessingException,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterField,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterEnum,
                       QgsProcessingParameterFeatureSink,
                       )
from . import HELP_DIR
from ORStools import ENDPOINTS, ICON_DIR, __help__
from ORStools.core import client, PROFILES
from ORStools.utils import transform, exceptions


class ORSmatrixAlgo(QgsProcessingAlgorithm):
    # TODO: create base algorithm class common to all modules

    ALGO_NAME = 'matrix'

    IN_START = "INPUT_START_LAYER"
    IN_START_FIELD = "INPUT_START_FIELD"
    IN_END = "INPUT_END_LAYER"
    IN_END_FIELD = "INPUT_END_FIELD"
    IN_PROFILE = "INPUT_PROFILE"
    OUT = 'OUTPUT'
    # Save reference to output layer
    # isochrones = isochrones_core.Isochrones()
    # dest_id = None

    def initAlgorithm(self, configuration, p_str=None, Any=None, *args, **kwargs):

        self.addParameter(
            QgsProcessingParameterEnum(
                self.IN_PROFILE,
                "Travel mode",
                PROFILES
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSource(
                name=self.IN_START,
                description="Input Start Point layer",
                types=[QgsProcessing.TypeVectorPoint],
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
                name=self.IN_START_FIELD,
                description="Start ID Field (can be used for joining)",
                parentLayerParameterName=self.IN_START,
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSource(
                name=self.IN_END,
                description="Input End Point layer",
                types=[QgsProcessing.TypeVectorPoint],
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
                name=self.IN_END_FIELD,
                description="End ID Field (can be used for joining)",
                parentLayerParameterName=self.IN_END,
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                name=self.OUT,
                description="Matrix",
            )
        )

    def name(self):
        return self.ALGO_NAME

    def shortHelpString(self):
        """Displays the sidebar help in the algorithm window"""

        file = os.path.join(
            HELP_DIR,
            'algorithm_matrix.help'
        )
        with open(file) as helpf:
            msg = helpf.read()

        return msg

    def helpUrl(self):
        """will be connected to the Help button in the Algorithm window"""
        return __help__

    def displayName(self):
        return 'Generate ' + self.ALGO_NAME.capitalize()

    def icon(self):
        return QIcon(os.path.join(ICON_DIR, 'icon_matrix.png'))

    def createInstance(self):
        return ORSmatrixAlgo()

    def processAlgorithm(self, parameters, context, feedback):

        # Init ORS client
        clnt = client.Client()

        params = dict()
        get_params = dict()
        get_params['profile'] = params['profile'] = PROFILES[self.parameterAsEnum(
                                                                    parameters,
                                                                    self.IN_PROFILE,
                                                                    context
                                                             )]

        # Get parameter values
        source = self.parameterAsSource(
            parameters,
            self.IN_START,
            context
        )
        source_field_name = self.parameterAsString(
            parameters,
            self.IN_START_FIELD,
            context
        )
        destination = self.parameterAsSource(
            parameters,
            self.IN_END,
            context
        )
        destination_field_name = self.parameterAsString(
            parameters,
            self.IN_END_FIELD,
            context
        )

        # Get fields from field name
        source_field_id = source.fields().lookupField(source_field_name)
        source_field = source.fields().field(source_field_id)

        destination_field_id = source.fields().lookupField(destination_field_name)
        destination_field = source.fields().field(destination_field_id)

        # Abort when MultiPoint type
        if (source.wkbType() or destination.wkbType()) == 4:
            raise QgsProcessingException("TypeError: Multipoint Layers are not accepted. Please convert to single geometry layer.")

        # Get source and destination features
        sources_features = list(source.getFeatures())
        destination_features = list(destination.getFeatures())
        # Get feature amounts/counts
        sources_amount = source.featureCount()
        destinations_amount = destination.featureCount()

        # Allow for 50 features in source if source == destination
        source_equals_destination = parameters['INPUT_START_LAYER'] == parameters['INPUT_END_LAYER']
        if source_equals_destination:
            features = sources_features
        else:
            features = sources_features + destination_features

        # Abort when too many features
        if len(features) > 100:
            raise QgsProcessingException("The cumulative feature count is > 100!")

        # Get feature points after transformation
        xformer = transform.transformToWGS(source.sourceCrs())
        features_points = [xformer.transform(feat.geometry().asPoint()) for feat in features]

        # Get IDs
        sources_ids = list(range(sources_amount)) if source_equals_destination else list(range(sources_amount))
        destination_ids = list(range(sources_amount)) if source_equals_destination else list(range(sources_amount, sources_amount + destinations_amount))

        feedback.pushInfo("Amount of features: {}".format(len(features_points)))

        # Populate parameters further
        params.update({
            'locations': [[point.x(), point.y()] for point in features_points],
            'sources': sources_ids,
            'destinations': destination_ids,
            'metrics': 'distance|duration',
            'id': 'Matrix'
        })

        # Make request and catch ApiError
        try:
            response = clnt.request(ENDPOINTS[self.ALGO_NAME], get_params, post_json=params)
        except exceptions.ApiError as e:
            feedback.reportError("{}:\n{}".format(
                e.__class__.__name__,
                str(e))
            )
            raise

        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUT,
            context,
            self.get_fields(
                source_field.type(),
                destination_field.type()
            ),
            QgsWkbTypes.NoGeometry
        )

        sources_attributes = [feat.attribute(source_field_name) for feat in sources_features]
        destinations_attributes = [feat.attribute(destination_field_name) for feat in destination_features]

        for s, source in enumerate(sources_attributes):
            for d, destination in enumerate(destinations_attributes):
                feat = QgsFeature()
                feat.setAttributes([
                    source,
                    destination,
                    response['durations'][s][d] / 3600,
                    response['distances'][s][d] / 1000
                ])

                sink.addFeature(feat)

        return {self.OUT: dest_id}

    @staticmethod
    def get_fields(source_type, destination_type):

        fields = QgsFields()
        fields.append(QgsField("FROM_ID", source_type))
        fields.append(QgsField("TO_ID", destination_type))
        fields.append(QgsField("DURATION_HOURS", QVariant.Double))
        fields.append(QgsField("DISTANCE_KM", QVariant.Double))

        return fields