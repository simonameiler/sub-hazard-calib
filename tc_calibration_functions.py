# -*- coding: utf-8 -*-
"""
This file is part of the CLIMADA papers repository:
    https://github.com/CLIMADA-project/climada_papers

Copyright (C) 2017 ETH Zurich, CLIMADA contributors listed in AUTHORS.

CLIMADA is free software: you can redistribute it and/or modify it under the
terms of the GNU Lesser General Public License as published by the Free
Software Foundation, version 3.

CLIMADA is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License along
with CLIMADA. If not, see <https://www.gnu.org/licenses/>.

---
Created on Monday, June 29 2020
    
description: Functions for tropical cyclone (TC) impact function calibration.
    Please refer to the paper (submitted) and README for more information.

@author: Samuel Eberenz, samuel.eberenz@usys.ethz.ch
"""

import os
import numpy as np
from numpy import isinf
import pandas as pd
from scipy import stats

import sys
sys.path.append("/Users/simonameiler/Documents/WCR/Scripts/sub-hazard_calib")
#from iso3166 import countries as iso_cntry
# from cartopy.io import shapereader
import matplotlib.pyplot as plt
import climada.util.plot as u_plot
import climada.util.coordinates as u_coord

from climada.engine import ImpactCalc, Impact
from climada.entity.exposures.litpop import LitPop
from climada.entity import IFTropCyclone, ImpactFuncSet
from climada.hazard import Centroids, Hazard
from climada.util.constants import SYSTEM_DIR

from climada.entity.exposures.base import INDICATOR_CENTR
from climada.util.finance import gdp # , world_bank 
from climada.util.coordinates import pts_to_raster_meta, get_resolution

from if_trop_cyclone_stable_202006 import IFTropCyclone # stable version
#from climada.engine.impact_data import emdat_countries_by_hazard, \
#    emdat_impact_event, emdat_to_impact, emdat_df_load
from impact_data_stable_202006 import emdat_countries_by_hazard, \
    emdat_impact_event, emdat_to_impact, emdat_df_load # stable version

from tc_calibration_config import REF_YEAR, RES_ARCSEC, \
    YEAR_RANGE, HAZ, EMDAT_CSV, \
    dist_cst_lim, regions_short


# -----------------------------
def prepare_calib_data(sub_haz='wind'):

    print("----------------------Loading Exposure----------------------")
    exposure = LitPop.from_hdf5(SYSTEM_DIR/"litpop_0300as_2014_calib_global.hdf5") 

    # init TC hazard:
    print("----------------------Loading Hazard------------------------")
    hazard = Hazard.from_hdf5(SYSTEM_DIR/"hazard"/f"TC_IBTrACS_1980-2020_{sub_haz}.hdf5")
    # add event name (wasn't stored as hdf5)
    RAIN_DIR = SYSTEM_DIR/"output"/"1980-2020_80S-80N_180W-180E_360as"
    track_files = np.unique(os.listdir(RAIN_DIR)).tolist()
    tracks = []
    for track in track_files:
        track, csv = track.split('.')
        tracks.append(track)
        hazard.event_name = tracks
    
    # correct a few IBTrACS IDs
    hazard.event_name = [s.replace('1995241N11333', '1995240N11337') for s in hazard.event_name]
    hazard.event_name = [s.replace('2013210N13122', '2013210N13123') for s in hazard.event_name]
    hazard.event_name = [s.replace('2015047S12140', '2015045S12145') for s in hazard.event_name]
    hazard.event_name = [s.replace('2017061S11063', '2017061S11061') for s in hazard.event_name]
    hazard.event_name = [s.replace('2017082S14152', '2017081S13152') for s in hazard.event_name]    
    #hazard.event_name = [s.replace('1992338S04173', '1992338S04173') for s in hazard.event_name]
    hazard.event_name = [s.replace('2003196N05150', '2003196N04150') for s in hazard.event_name]
    #hazard.event_name = [s.replace('2003240N15329', '2003240N15329') for s in hazard.event_name]  

    return hazard, exposure

def update_regions(df, new_regions_dict, save_path=None, \
                   country_column_name='country', region_column_name='cal_region2'):
    df[region_column_name] = 'None'
    fail_list = list()
    for country in df[country_column_name].unique():
        assigned = False
        for reg in new_regions_dict.keys():
            if country in new_regions_dict[reg]:
                df.loc[df[country_column_name]==country, region_column_name] = reg
                assigned = True
        if not assigned:
            fail_list.append(country)
    if 'None' in df[region_column_name]:
        print('warning: some countries not assigned to region: ')
        print(fail_list)
    if save_path:
        df.to_csv(save_path, index=False)
    return df, fail_list
        

def calc_aggregates(results, parameter_space, region_ids, yearly_impact=True):
    param_lengths = np.zeros(len(parameter_space), dtype='int')
    for param in np.arange(len(parameter_space)):
        param_lengths[param]=len(parameter_space[param])
    aggregates = pd.DataFrame(index=np.arange(0, np.product(param_lengths)), \
                               columns=['v_threshold', 'v_half', 'scale', \
                                        'sum_R2'])
    years_climada_impact = np.unique(results.loc[results['climada']>0, 'year'])
    years_emdat_impact = np.unique(results.loc[results['emdat']>0, 'year'])
    cnt_ = 0
    for cnt1, param0 in enumerate(parameter_space[0]):
        for cnt2, param1 in enumerate(parameter_space[1]):
            for cnt3, param2 in enumerate(parameter_space[2]):
                if param0<0 or param1<=0 or param2<=0:
                    raise ValueError('Prohibited negative number or zero found in parameters [%f, %f, %f]' % (param0, param1, param2))
                if param2>1:
                    # print('Warning: scale = %0.18f is corrected to max. scale = 1.0' % param2)
                    param2 = 1
                aggregates.loc[cnt_, 'v_threshold'] = param0
                aggregates.loc[cnt_, 'v_half'] = param0+param1
                aggregates.loc[cnt_, 'scale'] = param2
                aggregates.loc[cnt_, 'sum_R2'] = sum((results.loc[(results['v_threshold']==param0) & \
                        (results['v_half']==param0+param1) & (results['scale']==param2) & \
                        results['year'].isin(years_climada_impact) & \
                        results['year'].isin(years_emdat_impact), 'climada'] - \
                        results.loc[(results['v_threshold']==param0) & \
                        (results['v_half']==param0+param1) & \
                        (results['scale']==param2) & \
                        results['year'].isin(years_climada_impact) & \
                        results['year'].isin(years_emdat_impact), 'emdat'])**2)
                cnt_ += 1
    
    return aggregates, years_climada_impact, years_emdat_impact

def fix_data(df, mismatches=[], year_range=[1980, 2017], save_path=None, rm_mismatches=False):
    """fix data frames resulting from CALIB 3 or 4:
        - remove 'Unnamed' columns
        - apply GDP scaling for TWN if not yet applied
        - remove mismatched TC events (from list)
    Input:
        df (DataFrame)
        save_path (str): full path to save fixded df to,
            if None (default), it is not saved
        rm_mismatches (boolean): if True, events are removed
    Returns:
        df (DataFrame)  
    """
    # remove 'Unnamed' columns:
    unnamed_columns = [s for s in df.columns if "Unnamed: " in s]
    df = df.drop(columns=unnamed_columns)
    
    # apply GDP scaling for TWN
    if not (False in list(df.loc[df.country=='TWN', 'emdat_impact'] == df.loc[df.country=='TWN', 'emdat_impact_scaled'])):
        gdp_twn = dict()
        for year in np.arange(year_range[0], year_range[-1]+1):
            gdp_twn[year] = gdp('TWN', year)[1]
        for ind in df.loc[df.country=='TWN'].index:
            df.loc[df.index==ind, 'emdat_impact_scaled'] = \
                df.loc[df.index==ind, 'emdat_impact'] * gdp_twn[2014] / \
                gdp_twn[df.loc[df.index==ind, 'year'].values[0]]

    df['log_ratio'] = np.log(np.asarray(df['climada_impact'].replace(0, np.nan)/df['emdat_impact_scaled']).astype(np.float64))

    # drop mismatched events (as listed in MISMATCHES):
    if rm_mismatches:
        for mm in mismatches:
            df = df[df.EM_ID != mm]

    if save_path and isinstance(save_path, str):
        df.to_csv(save_path, index=False)
    return df

def country_calib_3(exposures, hazard, results_CVA_ratio, regions_dict, \
                      parameter_space = \
                      [np.array(25.7), \
                      np.array([39, 49, 59, 99]), \
                      np.array(1)], \
                      yearly_impact=False, \
                      year_range=[1980, 2017]):
    """Loop through all regions/countries/matched events and range of v_half 
    Returns results, DataFrame which is ammended from input from CLAIB2 called
    results_CVA_ratio
    Called in CALIB3."""
    print('------ country/event vulnerability analysis v_half------')
    fail_list = list()
    IFS = ImpactFuncSet()
    results = pd.DataFrame()
    results_CVA_ratio = results_CVA_ratio.filter(['country','region_id','cal_region2', 'year', 'EM_ID', 'ibtracsID', 'emdat_impact', 'reference_year', 'emdat_impact_scaled', 'climada_impact'], axis=1)
    results_CVA_ratio.climada_impact = np.zeros(results_CVA_ratio.shape[0])
    hazard = hazard.select(date=(str(year_range[0]) + '-01-01', str(year_range[1]) + '-12-31'))
    if yearly_impact:
        print('country_vulnerability_analysis: Yearly damages not yet implemented. Process aborted.')
        return results, fail_list

    for reg in regions_dict: # loop: CALIBRATION REGIONS
        for c_index, country in enumerate(regions_dict[reg]): # loop: COUNTRIES in region
            print('------ ' + reg + ': ' + str(c_index) + ' - ' + country + ' ------')
            if not country in list(results_CVA_ratio.country):
                continue
            cntry_iso3 = u_coord.country_to_iso(country, representation='numeric')
            exp_ = LitPop()
            exp_.gdf = exposures.gdf[exposures.gdf.region_id==cntry_iso3]
            # loops: parameters for impact function

            for param0 in parameter_space[0]:
                for param1 in parameter_space[1]:
                    for param2 in parameter_space[2]:
                        print('parameters = [%f, %f, %f]' % (param0, param0+param1, param2))
                        if param0<0 or param1<=0 or param2<=0:
                            raise ValueError('Prohibited negative number or zero found in parameters [%f, %f, %f]' % (param0, param1, param2))
                        if param2>1:
                            print('Warning: scale = %0.18f is corrected to max. scale = 1.0' % param2)
                            param2 = 1
                        
                        if_tc = IFTropCyclone()
                        if_tc.haz_type = HAZ
                        if_tc.set_emanuel_usa(v_thresh=param0, \
                                              v_half=param0+param1, scale=param2)
                        IFS.clear()
                        IFS.append(if_tc)
                        try:
                            imp_ = ImpactCalc(exp_, IFS, hazard).impact()
                        except ValueError as error_msg:
                            print('Impact calculation failed for country: ' + country + ' :')
                            print(error_msg)
                            fail_list.append(str(cntry_iso3))
                            continue
                        results_tmp = results_CVA_ratio.loc[results_CVA_ratio.country==country]
                        results_tmp['v_thresh'] = np.full(results_tmp.shape[0], param0)
                        results_tmp['v_half'] = np.full(results_tmp.shape[0], param0+param1)
                        results_tmp['scale'] = np.full(results_tmp.shape[0], param2)
                        # loop: EVENT in imp_
                        for index, event in enumerate(imp_.event_name):
                            # print('111 ' + event + ': ' + str(imp_.at_event[index]))
                            if event in list(results_tmp.ibtracsID):
                                # print('+++ ' + event + ': ' + str(imp_.at_event[index]))

                                results_tmp.loc[results_tmp.ibtracsID==event, 'climada_impact'] = imp_.at_event[index]
                        results = pd.concat([results, results_tmp], ignore_index=True)
                        #results = results.append(results_tmp)         
            #results = results.reset_index(drop=True)
    return results, fail_list

def compute_metric_min(results_CALIB3, metric='RMSF', save=False):
    """Find RMSF or RMSD for each v_half/region combi
    Required by CALIB 4"""
    if metric=='RMSF':
        results_CALIB3['log_ratio'] = np.log(np.asarray(results_CALIB3['climada_impact'].replace(0, np.nan)/results_CALIB3['emdat_impact_scaled']).astype(np.float64))
    elif (metric=='RMSD' or metric=='RMSE'):
        metric = 'RMSD'
        results_CALIB3['log_ratio'] = np.log(np.asarray(results_CALIB3['climada_impact'].replace(0, np.nan)/results_CALIB3['emdat_impact_scaled']).astype(np.float64))
    else:
        raise ValueError('Metric %s not implemented. Set metric to RMSD or RMSF.' %(metric))
        # results_CALIB3['deviation'] = np.log(np.asarray(results_CALIB3['climada_impact'].replace(0, np.nan)/results_CALIB3['emdat_impact_scaled']).astype(np.float64))
    #results_CALIB3.log_ratio[isinf(results_CALIB3.log_ratio)]=np.nan
    rows_list = []
    for idx_reg, region in enumerate(results_CALIB3.cal_region2.unique()):
        df = results_CALIB3.loc[results_CALIB3.cal_region2==region]
        for v_half in np.sort(results_CALIB3.v_half.unique()):
            dict_row = dict()
            dict_row['cal_region2'] = region
            dict_row['v_half'] = v_half
            df_ = df.loc[np.round(df.v_half, decimals=7)==np.round(v_half, decimals=7)]
            dict_row['N'] = df_.shape[0]
            if metric=='RMSF':
                dict_row[metric] = np.exp(np.sqrt(np.sum(df_.log_ratio**2)/dict_row['N']))
            elif metric=='RMSD':
                dict_row[metric] = np.sqrt(np.sum((df_.climada_impact-df_.emdat_impact_scaled)**2)/dict_row['N'])
            dict_row['total_impact_EMDAT_scaled'] = np.sum(df_.emdat_impact_scaled)
            dict_row['total_impact_CLIMADA'] = np.sum(df_.climada_impact)
            rows_list.append(dict_row)
    for v_half in np.sort(results_CALIB3.v_half.unique()):
        dict_row = dict()
        dict_row['cal_region2'] = 'GLB'
        dict_row['v_half'] = v_half
        df_ = results_CALIB3.loc[np.round(results_CALIB3.v_half, decimals=7)==np.round(v_half, decimals=7)]
        dict_row['N'] = df_.shape[0]
        if metric=='RMSF':
            dict_row[metric] = np.exp(np.sqrt(np.sum(df_.log_ratio**2)/dict_row['N']))
        elif metric=='RMSD':
            dict_row[metric] = np.sqrt(np.sum((df_.climada_impact-df_.emdat_impact_scaled)**2)/dict_row['N'])
        dict_row['total_impact_EMDAT_scaled'] = np.sum(df_.emdat_impact_scaled)
        dict_row['total_impact_CLIMADA'] = np.sum(df_.climada_impact)
        rows_list.append(dict_row)
    results = pd.DataFrame(rows_list)
    min_metric = pd.DataFrame()
    min_metric['cal_region2'] = list(results_CALIB3.cal_region2.unique()) + ['GLB']
    min_metric['v_half'] = np.zeros(min_metric.shape[0])
    min_metric[metric] = np.zeros(min_metric.shape[0])
    min_metric['total_impact_EMDAT_scaled'] = np.zeros(min_metric.shape[0])
    min_metric['total_impact_CLIMADA'] = np.zeros(min_metric.shape[0])    
    for idx, region in enumerate(min_metric['cal_region2']):
        df = results.loc[results.cal_region2==region]
        min_metric.v_half.iloc[idx] = df.v_half.loc[df[metric]==df[metric].min()].values[0]
        min_metric[metric].iloc[idx] = df[metric].loc[df[metric]==df[metric].min()].values[0]
        min_metric.total_impact_EMDAT_scaled.iloc[idx] = df.total_impact_EMDAT_scaled.loc[df[metric]==df[metric].min()].values[0]
        min_metric.total_impact_CLIMADA.iloc[idx] = df.total_impact_CLIMADA.loc[df[metric]==df[metric].min()].values[0]        

    return results, min_metric

def compute_vhalf_total_impact(results_CALIB3, scaling_emdat=1, save=True):
    """Find v_half per rgeion with log-ratio of total impact closest to 0.
    Required by CALIB 4"""

    rows_list = []
    for idx_reg, region in enumerate(np.sort(results_CALIB3.cal_region2.unique())):
        df = results_CALIB3.loc[results_CALIB3.cal_region2==region]
        for v_half in np.sort(results_CALIB3.v_half.unique()):
            dict_row = dict()
            dict_row['cal_region2'] = region
            dict_row['v_half'] = v_half
            df_ = df.loc[np.round(df.v_half, decimals=7)==np.round(v_half, decimals=7)]
            dict_row['N'] = df_.shape[0]
            dict_row['total_impact_EMDAT_scaled'] = scaling_emdat*np.sum(df_.emdat_impact_scaled)
            dict_row['total_impact_CLIMADA'] = np.sum(df_.climada_impact)
            dict_row['log_ratio_total_impact'] = np.log(dict_row['total_impact_CLIMADA']/dict_row['total_impact_EMDAT_scaled'])
            rows_list.append(dict_row)
    for v_half in np.sort(results_CALIB3.v_half.unique()):
        dict_row = dict()
        dict_row['cal_region2'] = 'GLB'
        dict_row['v_half'] = v_half
        df_ = results_CALIB3.loc[np.round(results_CALIB3.v_half, decimals=7)==np.round(v_half, decimals=7)]
        dict_row['N'] = df_.shape[0]
        dict_row['total_impact_EMDAT_scaled'] = scaling_emdat*np.sum(df_.emdat_impact_scaled)
        dict_row['total_impact_CLIMADA'] = np.sum(df_.climada_impact)
        dict_row['log_ratio_total_impact'] = np.log(dict_row['total_impact_CLIMADA']/dict_row['total_impact_EMDAT_scaled'])
        rows_list.append(dict_row)
    results = pd.DataFrame(rows_list)
    best_vhalf = pd.DataFrame()
    best_vhalf['cal_region2'] = list(results_CALIB3.cal_region2.unique()) + ['GLB']
    best_vhalf['v_half'] = np.zeros(best_vhalf.shape[0])
    best_vhalf['total_impact_EMDAT_scaled'] = np.zeros(best_vhalf.shape[0])
    best_vhalf['total_impact_CLIMADA'] = np.zeros(best_vhalf.shape[0])
    best_vhalf['log_ratio_total_impact'] = np.zeros(best_vhalf.shape[0])
    for idx, region in enumerate(best_vhalf['cal_region2']):
        df = results.loc[results.cal_region2==region]
        best_vhalf.v_half.iloc[idx] = df.v_half.loc[df.log_ratio_total_impact.abs()==df.log_ratio_total_impact.abs().min()].values[0]
        best_vhalf.total_impact_EMDAT_scaled.iloc[idx] = df.total_impact_EMDAT_scaled.loc[df.log_ratio_total_impact.abs()==df.log_ratio_total_impact.abs().min()].values[0]
        best_vhalf.total_impact_CLIMADA.iloc[idx] = df.total_impact_CLIMADA.loc[df.log_ratio_total_impact.abs()==df.log_ratio_total_impact.abs().min()].values[0]
        best_vhalf.log_ratio_total_impact.iloc[idx] = df.log_ratio_total_impact.loc[df.log_ratio_total_impact.abs()==df.log_ratio_total_impact.abs().min()].values[0]
    return results, best_vhalf

def compute_global_rmsf(results_CALIB3, min_rmsf, v_halfs):
    """Find global RMSF for list of v_half values and for regional v_half set"""
    results_CALIB3['log_ratio'] = np.log(np.asarray(results_CALIB3['climada_impact'].replace(0, np.nan)/results_CALIB3['emdat_impact_scaled']).astype(np.float64))
    reg_log_ratios = []
    rmsf_ = pd.DataFrame(columns=['regional IFs'] + v_halfs, index=['global RMSF'])
    rmsf_reg_control = dict()
    for idx_reg, region in enumerate(np.sort(results_CALIB3.cal_region2.unique())):
        df = results_CALIB3.loc[results_CALIB3.cal_region2==region]
        log_ratios_ = list(df.log_ratio.loc[\
                            np.round(df.v_half, decimals=7)==np.round(list(min_rmsf.v_half.loc[min_rmsf.cal_region2 == region])[0], decimals=7) \
                            ])
        reg_log_ratios = reg_log_ratios + log_ratios_
        rmsf_reg_control[region] = np.exp(np.sqrt(np.sum(np.array(log_ratios_)**2)/len(log_ratios_)))
    rmsf_.loc['global RMSF', 'regional IFs'] = np.exp(np.sqrt(np.sum(np.array(reg_log_ratios)**2)/len(reg_log_ratios)))

    for v_half in v_halfs:
        df_ = results_CALIB3.loc[np.round(results_CALIB3.v_half, decimals=7)==np.round(v_half, decimals=7)]
        rmsf_.loc['global RMSF', v_half] = np.exp(np.sqrt(np.sum(df_.log_ratio**2)/df_.shape[0]))

    return rmsf_, rmsf_reg_control

def closest_ratio(results_CALIB3, v0, v_half_range, scale, target=0):
    """Find best fit to log(ratio)=0 for each event/country combo
    Required by CALIB 4"""

    for columnname in ['Unnamed: 0', 'Unnamed: 0.1']:
        if columnname in results_CALIB3.columns:
            results_CALIB3 = results_CALIB3.drop(columns=columnname)
    results_CALIB3['unique_ID'] = results_CALIB3.EM_ID + results_CALIB3.country
    results_CALIB3['log_ratio'] = np.log(np.asarray(results_CALIB3['climada_impact'].replace(0, np.nan)/ \
                  results_CALIB3['emdat_impact_scaled']).astype(np.float64))
    unique_IDs = np.unique(results_CALIB3['unique_ID'])
    results = pd.DataFrame(index=np.arange(0,len(unique_IDs)), \
                           columns = results_CALIB3.columns)
    results.unique_ID=unique_IDs
    
    for index, unique_ID in enumerate(unique_IDs):
        df_tmp = results_CALIB3.loc[results_CALIB3.unique_ID==unique_ID]
        results.loc[index] = df_tmp.iloc[np.argmin(np.abs(df_tmp.log_ratio - target))]
    return results

def boxplot_sorted(df, by, column, rot=0, ax=None, log=True):
    """ Plot a sorted Boxplot from Dataframe
    Required in CALIB 2."""
    # use dict comprehension to create new dataframe from the iterable groupby object
    # each group name becomes a column in the new dataframe
    df2 = pd.DataFrame({col:vals[column] for col, vals in df.groupby(by)})
    # find and sort the median values in this new dataframe
    meds = df2.median().sort_values()
    # use the columns in the dataframe, ordered sorted by median value
    # return axes so changes can be made outside the function
    if not ax:
        ax = df2[meds.index].boxplot(rot=rot, return_type="axes")
    else:
        df2[meds.index].boxplot(rot=rot, ax=ax, return_type="axes")
    if log: ax.set_yscale('log')
    return ax


def matched_event_tables(imps_, imp_emdat_scaled, imp_emdat, region, emdat_map, \
                         labels=[''], matched_only=True):
    """ called from CALIB 5: for Impact() from CLIMADA and EM-DAT, 
    return DataFrames with event impacts 
    for matched events"""
    
    emdat_map= pd.read_csv(emdat_map, encoding="ISO-8859-1", header=0)   
    df = pd.DataFrame(index=np.arange(0, len(imps_[0].event_id)), \
                              columns=['cal_region', \
                                       'year', 'EM_ID', \
                                       'ibtracsID', 'emdat_impact', \
                                       'reference_year', 'emdat_impact_scaled']+ labels)
    for index, event in enumerate(imps_[0].event_name):
        df.loc[index, 'ibtracsID'] = event
        df.loc[index, 'cal_region'] = region
        df.loc[index, 'reference_year'] = REF_YEAR
        for i, lbl in enumerate(labels):
            df.loc[index, lbl] = imps_[i].at_event[index]
        df.loc[index, 'EM_ID'] = 'NONE'
        df.loc[index, 'year'] = int(event[0:4])
        if emdat_map['EM_ID'].loc[emdat_map['ibtracsID'].isin([event])].size > 0:
            df.loc[index, 'EM_ID'] = emdat_map['EM_ID'].loc[emdat_map['ibtracsID'].isin([event])].values[0]
            if df.loc[index, 'EM_ID'] in imp_emdat.event_name:
                df.loc[index, 'emdat_impact'] = np.sum([imp_emdat.at_event[i] for i in range(len(imp_emdat.event_name)) if imp_emdat.event_name[i] == df.loc[index, 'EM_ID']])
                df.loc[index, 'emdat_impact_scaled'] = np.sum([imp_emdat_scaled.at_event[i] for i in range(len(imp_emdat_scaled.event_name)) if imp_emdat_scaled.event_name[i] == df.loc[index, 'EM_ID']])
    if matched_only:
        # Get names of indexes for which EM_ID is 'NONE'
        indexNames = df[df['EM_ID'] == 'NONE'].index
        # Delete these row indexes from dataFrame
        df.drop(indexNames , inplace=True)
            
    return df

def fill_result_table(regions_short, rmsf_results, min_rmsf, tot_results, best_tot_vhalf, \
                      results_CALIB3_default_IF, glob_rmsf_rmsf, glob_tdr_rmsf):
    result_table = pd.DataFrame(index=np.arange(len(regions_short)+2), columns=\
                                ['region', 'N_countries' ,'N', 'def_v_half', 'def_RMSF', 'def_TDR', \
                                 'rmsf_v_half', 'rmsf_RMSF', 'rmsf_TDR', 'tdr_v_half', 'tdr_RMSF', 'tdr_TDR', ])
    countries_list = pd.DataFrame(index=np.arange(len(results_CALIB3_default_IF.country.unique())), columns=\
                                ['region', 'country'])
    countries_list.country = results_CALIB3_default_IF.country.unique()
    result_table.region = regions_short + ['GLB_combined', 'GLB']
    result_table.def_v_half = 74.7
    result_table.tdr_TDR = 1
    N_countries = 0
    total_impact_EMDAT_scaled_GLB_tdr = 0
    total_impact_CLIMADA_GLB_tdr = 0
    total_impact_EMDAT_scaled_GLB_rmsf = 0
    total_impact_CLIMADA_GLB_rmsf = 0
    for reg in result_table.region:
        if reg!='GLB_combined':
            result_table.loc[result_table.region==reg, 'rmsf_v_half'] = \
                min_rmsf.loc[min_rmsf.cal_region2==reg, 'v_half'].values[0]
            result_table.loc[result_table.region==reg, 'tdr_v_half'] = \
                best_tot_vhalf.loc[min_rmsf.cal_region2==reg, 'v_half'].values[0]
            result_table.loc[result_table.region==reg, 'rmsf_RMSF'] = \
                min_rmsf.loc[min_rmsf.cal_region2==reg, 'RMSF'].values[0]
            result_table.loc[result_table.region==reg, 'rmsf_TDR'] = \
                min_rmsf.loc[min_rmsf.cal_region2==reg, 'total_impact_CLIMADA'].values[0] / \
                min_rmsf.loc[min_rmsf.cal_region2==reg, 'total_impact_EMDAT_scaled'].values[0]
            result_table.loc[result_table.region==reg, 'tdr_TDR'] = \
                best_tot_vhalf.loc[best_tot_vhalf.cal_region2==reg, 'total_impact_CLIMADA'].values[0] / \
                best_tot_vhalf.loc[best_tot_vhalf.cal_region2==reg, 'total_impact_EMDAT_scaled'].values[0]
    
            # question SM: why 74.00? where does this number come from?
            result_table.loc[result_table.region==reg, 'N'] = \
                rmsf_results.loc[(np.round(rmsf_results.v_half, decimals=2)==74.00) & (rmsf_results.cal_region2==reg), 'N'].values[0]
            result_table.loc[result_table.region==reg, 'def_RMSF'] = \
                rmsf_results.loc[(np.round(rmsf_results.v_half, decimals=2)==74.00) & (rmsf_results.cal_region2==reg), 'RMSF'].values[0]
            result_table.loc[result_table.region==reg, 'def_TDR'] = \
                rmsf_results.loc[(np.round(rmsf_results.v_half, decimals=2)==74.00) & (rmsf_results.cal_region2==reg), 'total_impact_CLIMADA'].values[0] / \
                rmsf_results.loc[(np.round(rmsf_results.v_half, decimals=2)==74.00) & (rmsf_results.cal_region2==reg), 'total_impact_EMDAT_scaled'].values[0]
            result_table.loc[result_table.region==reg, 'tdr_RMSF'] = \
                rmsf_results.loc[(np.round(rmsf_results.v_half, decimals=2) == \
                np.round(best_tot_vhalf.loc[best_tot_vhalf.cal_region2==reg, 'v_half'].values[0], decimals=2)) & (rmsf_results.cal_region2==reg), 'RMSF'].values[0]
            if reg!='GLB':
                total_impact_CLIMADA_GLB_rmsf += min_rmsf.loc[min_rmsf.cal_region2==reg, 'total_impact_CLIMADA'].values[0]
                total_impact_EMDAT_scaled_GLB_rmsf += min_rmsf.loc[min_rmsf.cal_region2==reg, 'total_impact_EMDAT_scaled'].values[0]
                total_impact_CLIMADA_GLB_tdr += best_tot_vhalf.loc[best_tot_vhalf.cal_region2==reg, 'total_impact_CLIMADA'].values[0]
                total_impact_EMDAT_scaled_GLB_tdr += best_tot_vhalf.loc[best_tot_vhalf.cal_region2==reg, 'total_impact_EMDAT_scaled'].values[0]

                result_table.loc[result_table.region==reg, 'N_countries'] = len(\
                    results_CALIB3_default_IF.loc[results_CALIB3_default_IF.cal_region2==reg, 'country'].unique())
                N_countries += result_table.loc[result_table.region==reg, 'N_countries'].values[0]
                for cntry in countries_list.country:
                    if cntry in results_CALIB3_default_IF.loc[results_CALIB3_default_IF.cal_region2==reg, 'country'].unique():
                        countries_list.loc[countries_list.country==cntry, 'region'] = reg
    result_table.loc[result_table.region=='GLB', 'N_countries'] = N_countries
    reg = 'GLB_combined'
    result_table.loc[result_table.region==reg, 'def_RMSF'] = result_table.loc[result_table.region=='GLB', 'def_RMSF'].values[0]
    result_table.loc[result_table.region==reg, 'rmsf_RMSF'] = glob_rmsf_rmsf['regional IFs'].values[0]
    result_table.loc[result_table.region==reg, 'tdr_RMSF'] = glob_tdr_rmsf['regional IFs'].values[0]
    result_table.loc[result_table.region==reg, 'def_TDR'] = result_table.loc[result_table.region=='GLB', 'def_TDR'].values[0]
    result_table.loc[result_table.region==reg, 'rmsf_TDR'] = total_impact_CLIMADA_GLB_rmsf/total_impact_EMDAT_scaled_GLB_rmsf
    result_table.loc[result_table.region==reg, 'tdr_TDR'] = total_impact_CLIMADA_GLB_tdr/total_impact_EMDAT_scaled_GLB_tdr
    return result_table, countries_list
    
def get_associated_disasters(df_events, emdat_csv, ass_disasters_none_str = '--'):
    df_emdat = emdat_df_load('all', HAZ, emdat_csv, year_range=YEAR_RANGE, target_version=2018)[0]
    if isinstance(df_events, str):
        df_events = pd.read_csv(df_events, encoding="ISO-8859-1", header=0)
    if 'Associated Dis' in df_emdat.columns:
        ass_dis_str = 'Associated Dis'
    else:
        ass_dis_str = 'Associated disaster'
    unique_ass_disasters = list(np.unique(df_emdat[ass_dis_str].unique().tolist() + \
                                          df_emdat[ass_dis_str+'2'].unique().tolist()))
    unique_ass_disasters.remove(ass_disasters_none_str)
    ass_disasters = dict()
    
    ass_disasters['All'] = unique_ass_disasters
    ass_disasters['Surge'] = ['Surge']
    ass_disasters['Rain'] = ['Rain']
    ass_disasters['Flood'] = ['Flood']
    ass_disasters['Slide'] = ['Slide (land, mud, snow, rock)']
    ass_disasters['Other'] = ['Broken Dam/Burst bank', 'Cold wave', 'Fire', 'Hail', \
                 'Lightening', 'Oil spill', 'Transport accident', 'Tsunami/Tidal wave']
    ass_disasters['OtherThanSurge'] = unique_ass_disasters
    ass_disasters['OtherThanSurge'].remove('Surge')
    
    if not 'country' in df_events.columns:
        if 'hit_country' in df_events.columns:
            df_events['country'] = df_events['hit_country']
        else:
            df_events['country'] = 'undefined'
    
    df_events['Associated_disaster'] = False
    df_events['Surge'] = False
    df_events['Rain'] = False
    df_events['Flood'] = False
    df_events['Slide'] = False
    df_events['Other'] = False
    df_events['OtherThanSurge'] = False
    
    for cntry in df_events['country'].unique():
        for em_id in df_events.EM_ID.loc[df_events.country==cntry].unique():
            df_ = df_emdat.loc[df_emdat['Disaster No.']==em_id]
            if len(df_)>0:
                ass_dis = list()
                ass_dis.append(df_.loc[df_.ISO==cntry, ass_dis_str].values[0])
                ass_dis.append(df_.loc[df_.ISO==cntry, ass_dis_str+'2'].values[0])
                
                df_events.Associated_disaster.loc[df_events[(df_events['country']==cntry) & \
                                                            (df_events['EM_ID']==em_id)].index.values[0]] = \
                                                            any(elem in ass_dis  for elem in ass_disasters['All'])
                df_events.Surge.loc[df_events[(df_events['country']==cntry) & \
                                                            (df_events['EM_ID']==em_id)].index.values[0]] = \
                                                            any(elem in ass_dis  for elem in ass_disasters['Surge'])
                df_events.Flood.loc[df_events[(df_events['country']==cntry) & \
                                                            (df_events['EM_ID']==em_id)].index.values[0]] = \
                                                            any(elem in ass_dis  for elem in ass_disasters['Flood'])
                df_events.Slide.loc[df_events[(df_events['country']==cntry) & \
                                                            (df_events['EM_ID']==em_id)].index.values[0]] = \
                                                            any(elem in ass_dis  for elem in ass_disasters['Slide'])
                df_events.Other.loc[df_events[(df_events['country']==cntry) & \
                                                            (df_events['EM_ID']==em_id)].index.values[0]] = \
                                                            any(elem in ass_dis  for elem in ass_disasters['Other'])
                df_events.OtherThanSurge.loc[df_events[(df_events['country']==cntry) & \
                                                            (df_events['EM_ID']==em_id)].index.values[0]] = \
                                                            any(elem in ass_dis  for elem in ass_disasters['OtherThanSurge'])                                                            

    return df_events


""" ------------------FUNCTIONS FOR CALIB 6 and 7_____________________"""

def trend_by_country_EMDAT(countries, year_range=YEAR_RANGE, reference_year=REF_YEAR, \
                           hazard_type_climada=HAZ):
    """compute trends in reported damanges from EM-DAT for selected countries"""
    cntry_list_scaled = list()
    statistics = dict()
    statistics_log = dict()
    if countries in ['all', 'GLB', 'GLB_all']:
        countries = emdat_countries_by_hazard(hazard_type_climada, EMDAT_CSV, ignore_missing=True, \
                              verbose=True, year_range=year_range, target_version=2018)[0]
    for idx, cntry in enumerate(countries):
        imp_emdat_country = emdat_to_impact(EMDAT_CSV, \
                                             year_range=year_range, 
                                             countries=[cntry],\
                                             hazard_type_climada=hazard_type_climada, \
                                             reference_year=0, target_version=2018)[0]
        imp_emdat_country_scaled = emdat_to_impact(EMDAT_CSV, \
                                             year_range=year_range, 
                                             countries=[cntry],\
                                             hazard_type_climada=hazard_type_climada, \
                                             reference_year=reference_year, \
                                             target_version=2018)[0]
        yearset_emdat = imp_emdat_country.calc_impact_year_set(year_range=year_range)
        yearset_emdat_scaled = imp_emdat_country_scaled.calc_impact_year_set(year_range=year_range)
        if idx == 0:
            df = pd.DataFrame(list(yearset_emdat.keys()), columns=['year'])
        df['%s' % (cntry)] = pd.Series(list(yearset_emdat.values()))
        df['%s scaled' % (cntry)] = pd.Series(list(yearset_emdat_scaled.values()))
        cntry_list_scaled.append('%s scaled' % (cntry))
        
        statistics[cntry] = [stats.linregress(df.year, df[cntry])]
        statistics['%s scaled' % (cntry)] = [stats.linregress(df.year, df['%s scaled' % (cntry)])]
        # for log: exclude zeros
        if df[(df[[cntry]] != 0).all(axis=1)].shape[0] > 0:
            statistics_log[cntry] = [stats.linregress(df[(df[[cntry]] != 0).all(axis=1)].year, np.log(df[(df[[cntry]] != 0).all(axis=1)][cntry]))]
            statistics_log['%s scaled' % (cntry)] = [stats.linregress(df[(df[['%s scaled' % (cntry)]] != 0).all(axis=1)].year, np.log(df[(df[['%s scaled' % (cntry)]] != 0).all(axis=1)]['%s scaled' % (cntry)]))]
        else:
            statistics_log[cntry] = []
            statistics_log['%s scaled' % (cntry)] = []
        # slope, intercept, r_value, p_value, std_err 
        
        
    df['all'] = df[countries].sum(axis=1)
    df['all scaled'] = df[cntry_list_scaled].sum(axis=1)
    statistics['all'] = [stats.linregress(df.year, df['all'])]
    statistics['all scaled'] = [stats.linregress(df.year, df['all scaled'])]
    statistics_log['all'] = [stats.linregress(df[(df[['all']] != 0).all(axis=1)].year, np.log(df[(df[['all']] != 0).all(axis=1)]['all']))]
    statistics_log['all scaled'] = [stats.linregress(df[(df[['all scaled']] != 0).all(axis=1)].year, np.log(df[(df[['all scaled']] != 0).all(axis=1)]['all scaled']))]
    
    return df, statistics, statistics_log
    
def trend_by_country_CLIMADA(countries, exposures, IFS, hazard, year_range=YEAR_RANGE):
    """compute trends in simulated damages for selected countries"""
    statistics = dict()
    statistics_log = dict()
    if IFS.size()==1:
        exposures.if_TC = IFS.get_ids('TC')[0]
        exposures.if_ = IFS.get_ids(HAZ)[0]
    elif not np.min(np.sort(IFS.get_ids('TC'))==np.sort(exposures.if_.unique())):
        print('Warning: if IDs dont match between IFS and Exposure:')
        print(np.sort(IFS.get_ids('TC')))
        print(np.sort(exposures.if_.unique()))
        # return None, None, None
    countries_in = list()
    aai = 0
    if countries=='GLB_all':
        imp_ = Impact()
        imp_.calc(exposures, IFS, hazard)
        aai += imp_.aai_agg
        yearset_ = imp_.calc_impact_year_set(year_range=year_range)
        df = pd.DataFrame(list(yearset_.keys()), columns=['year'])
        df['all'] = pd.Series(list(yearset_.values())) 
        statistics['all'] = [stats.linregress(df.year, df['all'])]
        statistics_log['all'] = []
    else:
        for idx, cntry in enumerate(countries):
            imp_ = Impact()
            try:
                exp_ = exposures.loc[exposures.region_id==int(iso_cntry.get(cntry).numeric)]
                imp_.calc(exp_, IFS, hazard)
                aai += imp_.aai_agg
                yearset_ = imp_.calc_impact_year_set(year_range=year_range)
                if idx == 0:
                    df = pd.DataFrame(list(yearset_.keys()), columns=['year'])
                df['%s' % (cntry)] = pd.Series(list(yearset_.values())) 
                statistics[cntry] = [stats.linregress(df.year, df[cntry])]
                if df[(df[[cntry]] != 0).all(axis=1)].shape[0] > 0:
                    statistics_log[cntry] = [stats.linregress(df[(df[[cntry]] != 0).all(axis=1)].year, np.log(df[(df[[cntry]] != 0).all(axis=1)][cntry]))]
                else:
                    statistics_log[cntry] = []
                countries_in.append(cntry)
            except:
                print('Key error for country: %s' % (cntry))
                statistics_log[cntry] = []
                statistics[cntry] = []
            # slope, intercept, r_value, p_value, std_err 

        df['all'] = df[countries_in].sum(axis=1)
        statistics['all'] = [stats.linregress(df.year, df['all'])]
        statistics_log['all'] = [stats.linregress(df[(df[['all']] != 0).all(axis=1)].year, np.log(df[(df[['all']] != 0).all(axis=1)]['all']))]
    return df, statistics, statistics_log, aai

def annual_corr_aei(yearly_impact_set_1, yearly_impact_set_2, regions=regions_short+['GLB'], methods=['pearson', 'spearman']):
    """
    for all regions, return correlation between two yearly impact sets, as well als AEI
    """
    
def aai_from_yi(yearly_impact_set, column_name='all'):
    """
    for all regions, return annual average impact aai, i.e. mean annual impact
    """
    aai = pd.DataFrame(index=yearly_impact_set.keys(), columns=['value', 'std'])
    for region in yearly_impact_set.keys():
        aai.loc[region, 'value'] = yearly_impact_set[region][column_name].mean()
        aai.loc[region, 'std'] = yearly_impact_set[region][column_name].std()
    return aai

def IFS_plot(IFSs, labels, colors, linestyles, title_string=None, include_GLB=False, figsize=None, **kwargs):
    """Plot the impact functions MDD, MDR and PAA in one graph, where
    MDR = PAA * MDD.

    Parameters:
        axis (matplotlib.axes._subplots.AxesSubplot, optional): axis to use
        kwargs (optional): arguments for plot matplotlib function, e.g. marker='x'

    Returns:
        matplotlib.axes._subplots.AxesSubplot
    """
    if title_string is None: title_string=''
    if figsize is None: figsize = (12, 11)

    num_plts = IFSs[0].size()-1+include_GLB
    num_row, num_col = u_plot._get_row_col_size(num_plts)
    fig, axis = plt.subplots(num_row, num_col, figsize=figsize)
    #fig.tight_layout()
    if num_plts > 1:
        axes = axis.flatten()
    else:
        axes = [axis]
 

    for (IFS, lbl, c, ls) in zip(IFSs, labels, colors, linestyles):
        i_axis = 0
        if isinstance(IFS, tuple):
            for idf in IFS[0]._data['TC']:
                if i_axis==9 + include_GLB:
                    continue
                IF0 = IFS[0]._data['TC'][idf]
                IF1 = IFS[1]._data['TC'][idf]
                axes[i_axis].fill_between(IF0.intensity, IF0.mdd * IF0.paa * 100, IF1.mdd * IF1.paa * 100, \
                            color=c, alpha=0.25, label=lbl, **kwargs)
                if lbl==labels[-1]: axes[i_axis].legend()
                axes[i_axis].axhline(y=50, label=None, alpha=0.45, linestyle=':', c='k', linewidth=1)
                i_axis += 1
        else:
            for idf in IFS._data['TC']:
                if i_axis==9 + include_GLB:
                    continue
                IF = IFS._data['TC'][idf]
                axes[i_axis].plot(IF.intensity, IF.mdd * IF.paa * 100, c=c, linestyle=ls, label=lbl, **kwargs)
                # axes[i_axis].set_xlim((20, IF.intensity.max()))
                axes[i_axis].set_xlim((20, 90))
                axes[i_axis].set_ylim((0, 100))
                title = '%s %s' % (title_string, str(IF.id))
                if IF.name != str(IF.id):
                    title = IF.name
                    # title += ': %s' % IF.name
                if (not num_plts==9) or IF.id in [7, 8, 9]:
                    axes[i_axis].set_xlabel('Intensity (' + IF.intensity_unit + ')')
                if (not num_plts==9) or IF.id in [1, 4, 7]:
                    axes[i_axis].set_ylabel('Impact (%)')
                axes[i_axis].set_title(title)
                if lbl==labels[-1] and IF.id in [1]: axes[i_axis].legend()
                i_axis += 1
    return fig, axes
