"""
Adapted for code repository on 2022-06-28

description: Load TC tracks from the IBTrACS and generate a probabilistic track
            set from it. Next, calculate the 2D windfields after Holland (2008)
            for both track sets.

@author: simonameiler
"""

import pickle
import copy as cp

# import CLIMADA modules:
from climada.util.constants import SYSTEM_DIR
from climada.util.save import save
from climada.hazard import Centroids, TCTracks, TropCyclone

# paths and directories
haz_dir = SYSTEM_DIR/"hazard"
cent_str = SYSTEM_DIR.joinpath("earth_centroids_0300as_global.hdf5")


######### read IBTrACS from NetCDF and save as folder of .nc files ###########

# populate tracks by loading data from NetCDF:
tracks = TCTracks.from_ibtracs_netcdf(year_range=(1980,2017))
tracks_IB = TCTracks()
for i in range(0,6):
    filterdict = {'category': i}
    tracks_IB.data.extend(tracks.subset(filterdict).data)
# post processing, increase time steps for smoother wind field:
tracks_IB.equal_timestep(time_step_h=1., land_params=False)

# load centroids
cent = Centroids.from_hdf5(cent_str)

# calculate windfield for the historical IBTrACS
tc_haz = TropCyclone.from_tracks(tracks_IB, centroids=cent)
tc_haz.write_hdf5(haz_dir.joinpath("TC_global_0300as_IBTrACS.hdf5"))

