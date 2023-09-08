"""
Gets the nearest CWEC station to a set of coordinates
Brute force until the workload justifies otherwise
"""

import os
import sqlite3
from geopy.distance import geodesic
from numpy import inf

script_path = os.path.realpath(os.path.dirname(__file__)) + "/"
cwec_db = script_path + "cwec.sqlite"

conn = sqlite3.connect(cwec_db)
curs = conn.cursor()

cwec_stations = curs.execute("SELECT station_id, degree_latitude, degree_longitude FROM stations").fetchall()

def get_nearest(lat, long):

    shortest_dist = inf
    nearest_station = None

    for station in cwec_stations:
        dist = geodesic((lat, long), (station[1], station[2]))
        if dist < shortest_dist:
            shortest_dist = dist
            nearest_station = station

    return nearest_station[0]