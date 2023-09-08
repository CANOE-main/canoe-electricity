"""
This script calculates the capacity factor for a given solar array
"""

from numpy import *
from matplotlib import pyplot

sind = lambda deg: sin(deg2rad(deg))
cosd = lambda deg: cos(deg2rad(deg))
arcsind = lambda deg: arcsin(deg2rad(deg))
arccosd = lambda deg: arccos(deg2rad(deg))

def solar_capacity_factor(DNI, DHI, longitude, latitude):
    # latitude at location +N -S
    # longitude at location +W -E (-ve)

    az_panels = 0 # due south
    tilt = latitude-15 # latitude tilt
    losses = 0.25 # typical losses to electricity, snow, dust and such TODO: something more legit
    delta_UTC = -5 # timezone hours from UTC
    ref_insolation = 1000 # W/m2

    hour_days = arange(1,8761,1)/24 # days of the year passed for each hour, 0 to 365
    daily_hours = 24*mod(hour_days,1) # hours through each day, 0 to 24
    dec_angle = -23.45*cosd((360/365)*(hour_days+10)) # declination angle of the sun

    # correcting for solar time
    LSTM = 15*-delta_UTC # local standard time meridian
    B = (360/365)*(hour_days-81) # days from equinox
    EOT = 9.87*sind(2*B) - 7.53*cosd(B) - 1.5*sind(B) # equation of time
    time_correction = 4*(-longitude - LSTM) + EOT # solar time correction minutes
    LST = daily_hours + time_correction/60 # local solar time
    hour_angle = 15*(LST - 12) # hour angle, adjustes solar azimuth

    # angle of the sun in the sky by hour
    solar_alt = arcsind( cosd(latitude)*cosd(dec_angle)*cosd(hour_angle) + sind(latitude)*sind(dec_angle) )
    solar_az = arccosd( (sind(dec_angle) - sind(solar_alt)*sind(latitude)) / (cosd(solar_alt)*cosd(latitude)) )
    solar_az = (solar_az - 180)/2 * (daily_hours<12) + (180 - solar_az)/2 * (daily_hours>=12)
    surface_az = solar_az - az_panels
    sun_surface_angle = arccosd(cosd(solar_alt)*cosd(surface_az)*sind(tilt) + sind(solar_alt)*cosd(tilt))

    # If the sun is behind the panel then force to perpendicular for zero direct insolation
    sun_surface_angle[sun_surface_angle > 90] = 90
    sun_surface_angle[sun_surface_angle < -90] = 90

    # direct irradiance on the panels
    dir_I = DNI * cosd(sun_surface_angle)

    # diffuse irradiance on the panels
    diff_I = DHI * (180-tilt)/180

    hourly_irradiance = diff_I + dir_I*(dir_I>0)
    hourly_cf = hourly_irradiance * (1-losses) / (ref_insolation/1000*3600) # kJ/h to W/1000

    return hourly_cf