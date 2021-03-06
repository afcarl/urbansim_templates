from __future__ import print_function

import numpy as np
import pandas as pd
from datetime import datetime as dt

import orca
from urbansim.models import RegressionModel
from urbansim.utils import yamlio

from .shared import TemplateStep
from .. import modelmanager as mm


TEMPLATE_VERSION = '0.1dev1'

class OLSRegressionStep(TemplateStep):
    """
    A class for building OLS (ordinary least squares) regression model steps. This extends 
    TemplateStep, where some common functionality is defined. Estimation and simulation
    are handled by `urbansim.models.RegressionModel()`.
    
    Expected usage:
    - create a model object
    - specify some parameters
    - run the `fit()` method
    - iterate as needed
    
    Then, for simulation:
    - specify some simulation parameters
    - use the `run()` method for interactive testing
    - use the `register()` method to save the model to Orca and disk
    - registered steps can be accessed via ModelManager and Orca
    
    All parameters listed in the constructor can be set directly on the class object,
    at any time.

    Parameters
    ----------
    tables : str or list of str, optional
        Name(s) of Orca tables to draw data from. The first table is the primary one. 
        Any additional tables need to have merge relationships ("broadcasts") specified
        so that they can be merged unambiguously onto the first table. Among them, the 
        tables must contain all variables used in the model expression and filters. The
        left-hand-side variable should be in the primary table. The `tables` parameter is 
        required for fitting a model, but it does not have to be provided when the object 
        is created.

    model_expression : str, optional
        Patsy formula containing both the left- and right-hand sides of the model
        expression: http://patsy.readthedocs.io/en/latest/formulas.html
        This parameter is required for fitting a model, but it does not have to be 
        provided when the object is created.

    filters : str or list of str, optional
        Filters to apply to the data before fitting the model. These are passed to 
        `pd.DataFrame.query()`. Filters are applied after any additional tables are merged 
        onto the primary one. Replaces the `fit_filters` argument in UrbanSim.
    
    out_tables : str or list of str, optional
        Name(s) of Orca tables to use for simulation. If not provided, the `tables` 
        parameter will be used. Same guidance applies: the tables must be able to be 
        merged unambiguously, and must include all columns used in the right-hand-side
        of the model expression and in the `out_filters`.
    
    out_column : str, optional
        Name of the column to write predicted values to. If it does not already exist
        in the primary output table, it will be created. If not provided, the left-hand-
        side variable from the model expression will be used. Replaces the `out_fname` 
        argument in UrbanSim.
        
        # TO DO - auto-generation not yet working; column must exist in the primary table
    
    out_transform : callable, optional
        Transformation to apply to the predicted values, for example to reverse a 
        transformation of the left-hand-side variable in the model expression. Replaces
        the `ytransform` argument in UrbanSim.
    
    out_filters : str or list of str, optional
        Filters to apply to the data before simulation. If not provided, no filters will
        be applied. Replaces the `predict_filters` argument in UrbanSim.
        
    name : str, optional
        Name of the model step, passed to ModelManager. If none is provided, a name is
        generated each time the `fit()` method runs.
    
    tags : list of str, optional
        Tags, passed to ModelManager.
    
    """
    def __init__(self, tables=None, model_expression=None, filters=None, out_tables=None,
            out_column=None, out_transform=None, out_filters=None, name=None, tags=[]):
        
        # Parent class can initialize the standard parameters
        TemplateStep.__init__(self, tables=tables, model_expression=model_expression, 
                filters=filters, out_tables=out_tables, out_column=out_column, 
                out_transform=out_transform, out_filters=out_filters, name=name, 
                tags=tags)
        
        self.version = TEMPLATE_VERSION
        
        # Placeholders for model fit data, filled in by fit() or from_dict()
        self.summary_table = None 
        self.fitted_parameters = None
        self.model = None

    
    @classmethod
    def from_dict(cls, d):
        """
        Create an object instance from a saved dictionary representation.
        
        Parameters
        ----------
        d : dict
        
        Returns
        -------
        OLSRegressionStep
        
        """
        # Pass values from the dictionary to the __init__() method
        obj = cls(tables=d['tables'], model_expression=d['model_expression'], 
                filters=d['filters'], out_tables=d['out_tables'], 
                out_column=d['out_column'], out_transform=d['out_transform'],
                out_filters=d['out_filters'], name=d['name'], tags=d['tags'])

        obj.summary_table = d['summary_table']
        obj.fitted_parameters = d['fitted_parameters']
        
        # Unpack the urbansim.models.RegressionModel() sub-object and resuscitate it
        model_config = yamlio.convert_to_yaml(d['model'], None)
        obj.model = RegressionModel.from_yaml(model_config)
        
        return obj
        
    
    def to_dict(self):
        """
        Create a dictionary representation of the object.
        
        Returns
        -------
        dict
        
        """
        d = TemplateStep.to_dict(self)
        
        # Add parameters not in parent class
        d.update({
            'summary_table': self.summary_table,
            'fitted_parameters': self.fitted_parameters,
            'model': self.model.to_dict()  # urbansim.models.RegressionModel() sub-object
        })
        return d
        
        
    def fit(self):
        """
        Fit the model; save and report results.
        
        """
        self.model = RegressionModel(model_expression=self.model_expression,
                fit_filters=self.filters, predict_filters=self.out_filters,
                ytransform=self.out_transform, name=self.name)

        results = self.model.fit(self._get_data())
        
        self.name = self._generate_name()
        self.summary_table = str(results.summary())
        print(self.summary_table)
        
        # We don't strictly need to save the fitted parameters, because they are also
        # contained in the urbansim.models.RegressionModel() sub-object. But maintaining
        # a parallel data structure to other templates will make it easier to refactor the
        # code later on to not rely on RegressionModel any more. 
        
        self.fitted_parameters = results.params.tolist()
        
        
    def run(self):
        """
        Run the model step: calculate predicted values and use them to update a column.
        
        The predicted values are written to Orca and also saved to the class object for 
        interactive use (`predicted_values`, with type pd.Series). But they are not saved 
        in the dictionary representation of the model step.
        
        """
        # TO DO - figure out what we can infer about requirements for the underlying data
        # and write an 'orca_test' assertion to confirm compliance.

        values = self.model.predict(self._get_data('predict'))
        self.predicted_values = values
        
        colname = self._get_out_column()
        tabname = self._get_out_table()

        orca.get_table(tabname).update_col_from_series(colname, values, cast=True)
        

    def register(self):
        """
        Register the model step with Orca and the ModelManager. This includes saving it
        to disk so it can be automatically loaded in the future. 
        
        Registering a step will rewrite any previously saved step with the same name. 
        (If a custom name has not been provided, one is generated each time the `fit()` 
        method runs.)
                
        """
        d = self.to_dict()
        mm.add_step(d)
            
        