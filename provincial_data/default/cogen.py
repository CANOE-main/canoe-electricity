import sqlite3
from canoe_electricity.setup import config
import pandas as pd
import canoe_electricity.utils as utils
from canoe_schema.v4_0.models import LimitActivity


def aggregate(df_rtv: pd.DataFrame):

    conn = sqlite3.connect(config.database_file)
    curs = conn.cursor()

    # Cogen tech codes
    codes = (
        'ng_cg',
        'biomass_cg'
    )

    df_rtv = df_rtv.loc[
        (df_rtv['tech_code'].isin(codes)) # is cogen
        & (df_rtv['vint'] < config.model_periods[0]) # existing capacity only
    ]

    if len(df_rtv) == 0:
        conn.close()
        return # probably new capacity

    print("Aggregating cogen constraints...")

    max_note = (
        'unit_average_annual_energy from CODERS. '
        'Must match historical generation as we do not adjust heat demand based on cogeneration activity.'
    )
    min_note = max_note + ' (95% of max for computational slack)'

    ref = config.refs.get('generators')

    rows = []
    for period in config.model_periods:
        for region in config.model_regions:

            # If there's surviving cogen in this period, add the constraints
            df_rpt = df_rtv.loc[(df_rtv['region'] == region) & (df_rtv['vint'] + df_rtv['life'] > period)]

            if len(df_rpt) > 0:

                if isinstance(df_rpt, pd.DataFrame):
                    df_rpt = df_rpt.groupby(['region','tech']).sum(numeric_only=True).reset_index().iloc[0]

                max_act = df_rpt['unit_average_annual_energy'] * config.units.loc['activity', 'coders_conv_fact']
                max_act *= 1000 # apparently this column is GWh
                data_id = utils.data_id(df_rpt['region'])

                rows.append(LimitActivity(
                    region=df_rpt['region'],
                    period=period,
                    tech_or_group=df_rpt['tech'],
                    operator='ge',
                    activity=max_act * 0.95,
                    units='(PJ)',
                    notes=min_note,
                    data_source=ref.id,
                    dq_cred=2,
                    data_id=data_id,
                ))
                rows.append(LimitActivity(
                    region=df_rpt['region'],
                    period=period,
                    tech_or_group=df_rpt['tech'],
                    operator='le',
                    activity=max_act,
                    units='(PJ)',
                    notes=max_note,
                    data_source=ref.id,
                    dq_cred=2,
                    data_id=data_id,
                ))

    if rows:
        curs.executemany(*LimitActivity.bulk_insert_or_ignore_sql(rows))

    conn.commit()
    conn.close()
