"""
This script calculates the capacity factor for a given wind farm
"""

from numpy import *
from matplotlib import pyplot

sind = lambda deg: sin(deg2rad(deg))
cosd = lambda deg: cos(deg2rad(deg))
arcsind = lambda deg: arcsin(deg2rad(deg))
arccosd = lambda deg: arccos(deg2rad(deg))

# horrible
hub_height_est = lambda rated_power: 4.2159*rated_power^0.3934

def wind_capacity_factor(hourly_ws, temp, hum, pow):

    # Turbines specs
    hub_height = hub_height_est(pow)

    # Log profile adjustment
    z0 = 0.05; # Characteristic roughness length
    h_meas = 10; # (m) height above ground of wind measuresments
    height_factor = log(hub_height/z0) / log(h_meas/z0)

    hourly_ice = temp <= 0 & hum > 0.88

    # Energy production
    hourlyws_hub = hourly_ws * height_factor
    hourly_kW = turbine_power_curve(hourlyws_hub, rated_power)

def turbine_power_curve(hourly_ws, rated_power):
    # return 8760 power