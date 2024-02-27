"""
Aggregates transmission dummy techs, line losses and planning reserve margin
Written by Ian David Elder for the CANOE model
"""

import sqlite3
from setup import config
import coders_api
import os

# Regional parameters
_ca_sys_params, df_sys, date_accessed = coders_api.get_data(end_point='CA_system_parameters')
df_sys.set_index('province', inplace=True)
config.references['ca_system_parameters'] = config.params['coders']['reference'].replace('<date>', date_accessed)



def aggregate_reserve_margin():

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()


    """
    ##############################################################
        Planning reserve margin
    ##############################################################
    """

    for province, row in df_sys.iterrows():

        region = config.region_map[province.lower()]
        if region not in config.model_regions: continue # skip unrepresented provinces


        ## PlanningReserveMargin
        reserve_margin = row['reserve_requirements_percent']
        curs.execute(f"""REPLACE INTO
                    PlanningReserveMargin(regions, reserve_margin, reference, data_flags, dq_est, additional_notes)
                    VALUES("{region}", "{reserve_margin}", "{config.references['ca_system_parameters']}", "coders", 1, "reserve_requirements_percent")""")


    print(f"Planning reserve margin aggregated into {os.path.basename(config.database_file)}\n")

    conn.commit()
    conn.close()


# Data for provincial grid
def aggregate_transmission():

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()


    """
    ##############################################################
        Transmission techs
    ##############################################################
    """

    # Transmission techs ELC_TX <--> ELC_DX --> D_ELC
    tx_techs = ["tx_to_dx", "dx_to_tx"]
    dummy_techs = ["dx_to_dem", "g_to_tx", "grps_to_tx"]
    for trans_tech in tx_techs + dummy_techs:
        
        ## Technologies
        curs.execute(f"""REPLACE INTO
                    technologies(tech, flag, sector, tech_desc)
                    VALUES("{config.trans_techs.loc[trans_tech, 'tech']}", "p", "electric", "Transmission dummy tech")""")

    for province, row in df_sys.iterrows():

        region = config.region_map[province.lower()]
        if region not in config.model_regions: continue # skip unrepresented provinces

        for trans_tech in tx_techs + dummy_techs:

            tech_config = config.trans_techs.loc[trans_tech]
            input_comm = config.commodities.loc[tech_config['in_comm']]
            output_comm = config.commodities.loc[tech_config['out_comm']]


            ## Commodities
            curs.execute(f"""REPLACE INTO
                        commodities(comm_name, flag, comm_desc)
                        VALUES('{input_comm['commodity']}', '{input_comm['flag']}', '({input_comm['units']}) {input_comm['description']}')""")
            curs.execute(f"""REPLACE INTO
                        commodities(comm_name, flag, comm_desc)
                        VALUES('{output_comm['commodity']}', '{output_comm['flag']}', '({output_comm['units']}) {output_comm['description']}')""")


            ## Efficiency
            # Eff is line loss for TX <-> DX or 1 for dummy techs
            if trans_tech in tx_techs:
                eff = 1.0 - row["system_line_losses_percent"]
                note = f"({output_comm['units']}/{input_comm['units']}) system_line_losses_percent"
            else:
                eff = 1
                note = "dummy tech"

            curs.execute(f"""REPLACE INTO
                        Efficiency(regions, input_comm, tech, vintage, output_comm, efficiency, eff_notes, reference, data_flags, dq_est)
                        VALUES("{region}", "{input_comm['commodity']}", "{tech_config['tech']}", {config.model_periods[0]}, "{output_comm['commodity']}",
                        {eff}, "{note}", "{config.references['ca_system_parameters']}", "coders", 1)""")


    print(f"Transmission aggregated into {os.path.basename(config.database_file)}\n")

    conn.commit()
    conn.close()