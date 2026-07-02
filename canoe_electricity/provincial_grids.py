"""
Aggregates transmission dummy techs, line losses and planning reserve margin
Written by Ian David Elder for the CANOE model
"""

import sqlite3
from canoe_electricity.setup import config
import canoe_electricity.coders_api as coders_api
import os
from matplotlib import pyplot as pp
import pandas as pd
import canoe_electricity.utils as utils
from canoe_schema.v4_0.models import (
    PlanningReserveMargin, Technology, Efficiency, DemandSpecificDistribution, Demand
)

from provincial_data.default import cost_tx_dx

# Provincial parameters
df_sys: pd.DataFrame

weather_year = config.weather_year



def aggregate():

    global df_sys

    _coders_kwargs = dict(
        cache_dir=config.cache_dir,
        force_download=config.force_download,
        api_key_file=config.input_files + config.coders_api_key_file,
        debug=config.debug,
    )

    # Provincial system parameters
    df_sys, date_accessed = coders_api.get_data(end_point='CA_system_parameters', **_coders_kwargs)
    df_sys['region'] = [config.region_map[p.lower()] for p in df_sys['province'].values]
    df_sys = df_sys.loc[df_sys['region'].isin(config.model_regions)]
    df_sys.set_index('region', inplace=True)
    citation = config.coders.reference.replace('<table>', 'ca_system_parameters').replace('<date>', date_accessed)
    ref = config.refs.add('ca_system_parameters', citation)

    if config.include_reserve_margin: aggregate_reserve_margin()
    aggregate_demand()
    aggregate_transmission()



def aggregate_reserve_margin():

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    rows = [
        PlanningReserveMargin(
            region=region,
            margin=row['reserve_requirements_percent'],
            notes="CODERS - ca_system_parameters - reserve_requirements_percent",
            data_source=config.refs.get('ca_system_parameters').id,
            dq_cred=2,
            data_id=utils.data_id(region),
        )
        for region, row in df_sys.iterrows()
    ]
    if rows:
        curs.executemany(*PlanningReserveMargin.bulk_insert_or_ignore_sql(rows, include_nulls=True))

    print(f"Planning reserve margin aggregated into {os.path.basename(config.database_file)}\n")

    conn.commit()
    conn.close()



# In-province grid transmission structure
def aggregate_transmission():

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    """
    ##############################################################
        Transmission techs
    ##############################################################
    """

    # Transmission techs ELC_TX <--> ELC_DX --> D_ELC
    tech_rows = [
        Technology(
            tech=config.trans_techs.loc[code, 'tech'],
            flag='p',
            sector='electricity',
            unlim_cap=1,
            description=config.trans_techs.loc[code, 'description'],
            data_id=utils.data_id(),
        )
        for code in ['tx_to_dx', 'dx_to_dem']
    ]
    curs.executemany(*Technology.bulk_insert_or_ignore_sql(tech_rows, include_nulls=True))

    ## CostVariable
    for region, row in df_sys.iterrows():
        for period in config.model_periods:
            cost_tx_dx.aggregate(region, period, config.trans_techs.loc['tx_to_dx']['tech'], config.model_periods[0], curs, utils.data_id(region), 'tx')
            cost_tx_dx.aggregate(region, period, config.trans_techs.loc['dx_to_dem']['tech'], config.model_periods[0], curs, utils.data_id(region), 'dx')

    ## Efficiency
    eff_rows = []

    # TX to DX includes line loss
    for region, row in df_sys.iterrows():

        tech_config = config.trans_techs.loc['tx_to_dx']
        input_comm = config.commodities.loc[tech_config['in_comm']]
        output_comm = config.commodities.loc[tech_config['out_comm']]
        note = f"({output_comm['units']}/{input_comm['units']}) coders {region} system_line_losses_percent"

        eff_rows.append(Efficiency(
            region=region,
            input_comm=input_comm['commodity'],
            tech=tech_config['tech'],
            vintage=config.model_periods[0],
            output_comm=output_comm['commodity'],
            efficiency=1.0 - float(row["system_line_losses_percent"]),
            notes=note,
            data_source=config.refs.get('ca_system_parameters').id,
            data_id=utils.data_id(region),
        ))

    # DX to DEM just a dummy for distribution costs
    for region in config.model_regions:

        tech_config = config.trans_techs.loc['dx_to_dem']
        input_comm = config.commodities.loc[tech_config['in_comm']]
        output_comm = config.commodities.loc[tech_config['out_comm']]

        eff_rows.append(Efficiency(
            region=region,
            input_comm=input_comm['commodity'],
            tech=tech_config['tech'],
            vintage=config.model_periods[0],
            output_comm=output_comm['commodity'],
            efficiency=1,
            notes="dummy tech for distribution costs",
            data_id=utils.data_id(region),
        ))

    curs.executemany(*Efficiency.bulk_insert_or_ignore_sql(eff_rows, include_nulls=True))

    print(f"Transmission aggregated into {os.path.basename(config.database_file)}\n")

    conn.commit()
    conn.close()



def aggregate_demand():

    print("Aggregating provincial electricity demand...")

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    _coders_kwargs = dict(
        cache_dir=config.cache_dir,
        force_download=config.force_download,
        api_key_file=config.input_files + config.coders_api_key_file,
        debug=config.debug,
    )

    # Annual demand projections
    df_annual, date_accessed = coders_api.get_data(end_point="forecasted_annual_demand", **_coders_kwargs)
    citation = config.coders.reference.replace("<date>", date_accessed).replace("<table>", "forecasted_annual_demand")
    config.refs.add('forecasted_annual_demand', citation)
    df_annual['region'] = [config.region_map[p.lower()] for p in df_annual['province']]
    df_annual.set_index('region', inplace=True)

    # Demand tech and commodity data
    dem_comm = config.commodities.loc['demand']
    tech_config = config.trans_techs.loc['demand']
    input_comm = config.commodities.loc[tech_config['in_comm']]
    output_comm = config.commodities.loc[tech_config['out_comm']]

    # Get available data provinces and years from coders
    df_avail, _date = coders_api.get_data(end_point="provincial_demand", **_coders_kwargs)

    for _idx, prov in df_avail.iterrows():

        region = config.region_map[prov['province'].lower()]
        if region not in config.model_regions: continue

        data_id = utils.data_id(f"DEM{region}")


        """
        ##############################################################
            Hourly provincial electricity demand
        ##############################################################
        """

        if str(weather_year) not in prov['year']:
            print(f"Provincial hourly demand data not available for {region} for year {weather_year} so DemandSpecificDistribution was skipped.")
            continue

        df_hourly, date_accessed = coders_api.get_data(end_point="provincial_demand", year=weather_year, province=prov['province'], **_coders_kwargs)
        dsd_reference = config.coders.reference.replace("<date>", date_accessed).replace("<table>", "provincial_demand")
        ref = config.refs.add(f"provincial_demand", dsd_reference)

        if df_hourly is None or (len(df_hourly) < 8760):
            print(f"Insufficient hourly demand data available for {region} so DemandSpecificDistribution was skipped.")
            continue

        hourly_dem = df_hourly['demand_MWh'].iloc[0:8760].astype(float).ffill().to_numpy().copy()

        # Store hourly demand to calculate capacity credits for VREs
        # Can't turn back before this point or wont be able to calculate CCs
        config.provincial_demand[region] = hourly_dem


        ## Technology
        tech_row = Technology(
            tech=tech_config['tech'],
            flag='p',
            sector='electricity',
            unlim_cap=1,
            annual=1,
            description=tech_config['description'],
            data_id=utils.data_id(),
        )
        curs.executemany(*Technology.bulk_insert_or_ignore_sql([tech_row], include_nulls=True))

        ## Efficiency
        eff_row = Efficiency(
            region=region,
            input_comm=input_comm['commodity'],
            tech=tech_config['tech'],
            vintage=config.model_periods[0],
            output_comm=output_comm['commodity'],
            efficiency=1,
            notes="dummy tech",
            data_id=data_id,
        )
        curs.executemany(*Efficiency.bulk_insert_or_ignore_sql([eff_row], include_nulls=True))


        # If not including demand, don't go any further
        if not config.include_provincial_demand or not config.regions.loc[region, 'include_demand']: continue


        # Apply tolerance and normalise
        hourly_dem[hourly_dem < hourly_dem.mean() * config.dsd_tolerance] = 0
        dsd = hourly_dem / hourly_dem.sum()

        # Plot provincial demand
        pp.figure()
        pp.plot(dsd)
        pp.title(f"{region} normalised hourly electricity demand")
        pp.ylabel("DSD")
        pp.xlabel("Hour of year")


        ## DemandSpecificDistribution
        dsd_note = f"{weather_year} hourly demand divided by sum of hourly demand for that year"

        dsd_rows = []
        for period in config.model_periods:
            for h, time in config.time.iterrows():

                if time['tod'] == config.time.iloc[0]['tod']:
                    dsd_rows.append(DemandSpecificDistribution(
                        region=region,
                        period=period,
                        season=time['season'],
                        tod=time['tod'],
                        demand_name=dem_comm['commodity'],
                        dsd=dsd[h],
                        notes=dsd_note,
                        data_source=ref.id,
                        dq_cred=2,
                        data_id=data_id,
                    ))
                else:
                    dsd_rows.append(DemandSpecificDistribution(
                        region=region,
                        period=period,
                        season=time['season'],
                        tod=time['tod'],
                        demand_name=dem_comm['commodity'],
                        dsd=dsd[h],
                        notes=dsd_note,
                        data_source=ref.id,
                        dq_cred=2,
                        data_id=data_id,
                    ))

        if dsd_rows:
            curs.executemany(*DemandSpecificDistribution.bulk_insert_or_ignore_sql(dsd_rows, include_nulls=True))


        """
        ##############################################################
            Annual provincial electricity demand
        ##############################################################
        """

        ## Demand
        demand_rows = []
        for period in config.model_periods:

            demand_year = str(utils.data_year(period))
            ann_dem = config.units.loc['demand', 'coders_conv_fact'] * df_annual.loc[region, demand_year]

            demand_rows.append(Demand(
                region=region,
                period=period,
                commodity=dem_comm['commodity'],
                demand=ann_dem,
                units=f"({dem_comm['units']})",
                notes=f"provincial electricity demand projection {df_annual.loc[region, 'province']} {demand_year}",
                data_source=config.refs.get("forecasted_annual_demand").id,
                dq_cred=2,
                data_id=data_id,
            ))

        if demand_rows:
            curs.executemany(*Demand.bulk_insert_or_ignore_sql(demand_rows, include_nulls=True))


    conn.commit()
    conn.close()

    print(f"Provincial electricity demand data aggregated into {os.path.basename(config.database_file)}\n")



if __name__ == "__main__":

    aggregate()
