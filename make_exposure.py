#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Oct 24 13:53:34 2022

@author: simonameiler
"""

import os
import logging
import numpy as np

# import CLIMADA modules:
from climada.util.constants import SYSTEM_DIR
from climada.hazard import Centroids
from climada.entity import LitPop
from climada.util.coordinates import dist_to_coast
from climada.util.coordinates import pts_to_raster_meta, get_resolution

from tc_calibration_config import region_ids_cal

LOGGER = logging.getLogger(__name__)

res = 300
ref_year = 2014

cntrs_from_dicts = list(region_ids_cal.values())

countries = [item for sublist in cntrs_from_dicts for item in sublist]

def init_litpop(countries, hazard_type='TC', \
                         res_arcsec = 300, ref_year=2014):
    success = []
    fail = []
    print("-----------------Initiating LitPop--------------------")
    exp_litpop_list = []
    print("------------------------------------------------------")
    print("Initiating LitPop country per country:....")
    print("------------------------------------------------------")
    for cntry in countries:
        print("-------------------------" + cntry + "--------------------------") 
        try:
            exp_litpop_tmp = LitPop.from_countries(cntry, res_arcsec=res_arcsec, reference_year=ref_year)
            exp_litpop_tmp.set_geometry_points()
            exp_litpop_tmp.set_lat_lon()
            
            exp_litpop_list.append(exp_litpop_tmp)
            success.append(cntry)
        except Exception as e:
            fail.append(cntry)
            print("Error while initiating LitPop Exposure for " + cntry + ". ", e)
    del exp_litpop_tmp
    print("----------------------Done---------------------")
    
    exp_litpop = LitPop.concat(exp_litpop_list)
    exp_litpop.set_geometry_points()
    exp_litpop.set_lat_lon()

    exp_litpop.check()
    
    with open(os.path.join(SYSTEM_DIR, 'cntry_fail.txt'), "w") as output:
        output.write(str(fail))
    with open(os.path.join(SYSTEM_DIR, 'cntry_success.txt'), "w") as output:
        output.write(str(success))
    exp_str = f"litpop_0{res}as_{ref_year}_calib_global.hdf5"
    exp_litpop.write_hdf5(SYSTEM_DIR.joinpath(exp_str))
    return exp_litpop

exp = init_litpop(countries)
