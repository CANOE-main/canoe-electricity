import pandas as pd
import numpy as np
from matplotlib import pyplot as pp


## Uses the NREL ReEDS method (LDC-NLDC) top 100h to calculate marginal capacity credits of VREs
def aggregate_vre(df_bins: pd.DataFrame, df_cf: pd.DataFrame, region: str, show_plots: bool = True):

    # Get hourly generation from existing VREs to calculate prior net load
    exs_vre_gen = pd.read_csv("ontario_exs_vre_gen_hourly_2018.csv")
    load = pd.read_csv("ontario_load_hourly_2018.csv")
    net_load = load - exs_vre_gen # first net load is demand minus hourly generation of existing VREs


    ## Just to setup plotting
    if show_plots:
        # Set up the capacity credit plot, hourly above and ldc/cc side-by-side below
        figure, axes = pp.subplot_mosaic([['hourly','hourly'], ['dc','cc']], figsize=(10, 8))
        pp.subplots_adjust(hspace=0.3, wspace=0.3, top=0.87, bottom=0.1, left=0.1, right=0.9)

        # Plot prior load and net load, and ldc/nldc
        axes['hourly'].set_title(f"marginal hourly net load")
        axes['hourly'].set_xlabel(f"hour of year")
        axes['hourly'].set_ylabel(f"load (MW)")
        axes['hourly'].plot(load, color=(0, 0, 1, 1))
        axes['hourly'].plot(net_load, color=(0, 1, 0, 1))

        axes['dc'].set_title(f"marginal net load duration curve")
        axes['dc'].set_xlabel(f"sorted by hourly load (descending)")
        axes['dc'].set_ylabel(f"load (MW)")
        axes['dc'].plot(range(len(load)), np.sort(load)[::-1], color=(0, 0, 1, 1)) # original ldc
        axes['dc'].plot(range(len(net_load)), np.sort(net_load)[::-1], color=(0, 1, 0, 1)) # nldc after existing capacity


    ## Calculate each marginal capacity credit and add to plots
    # Actual calculation of CCs in this loop
    green = 1 # Colour gradient from yellow to red by reducing green
    for bin_index, bin in df_bins.iterrows():

        # Subtract generation from this cluster from previous net load to get next marginal net load and nldc
        cf = df_cf[bin_index].to_numpy()
        marginal_net_load: np.ndarray = net_load - cf * bin['max_cap'] # next marginal net load is previous net load minus hourly generation of this bin
        marginal_nldc = np.sort(marginal_net_load)[::-1] # net load duration curve is marginal net load sorted (descending)

        # Capacity credit is mean of nldc reduction in top 100 hours (NREL ReEDS) divided by nameplate capacity
        cc = (np.sort(net_load)[::-1] - marginal_nldc)[0:100].mean() / bin['max_cap'] # cc is last nldc minus this nldc averaged over top 100h
        df_bins.loc[bin_index, 'cc'] = cc # save calculated cc to the bin

        # Save this marginal net load for next loop
        net_load = marginal_net_load

        # Add to duration curve and hourly plots
        if show_plots:
            green -= 1 / len(df_bins.index) # reduce green linearly so yellow turns gradually to red
            axes['dc'].plot(range(len(marginal_nldc)), marginal_nldc, color=(1, green, 0, 1))
            axes['hourly'].plot(range(len(marginal_net_load)), marginal_net_load, color=(1, green, 0, 1))


    ## Plot marginal capacity credits by VRE cluster
    if show_plots:
        axes['cc'].set_title(f"marginal capacity credit")
        axes['cc'].set_xlabel(f"new capacity bins")
        axes['cc'].set_ylabel(f"capacity credit (% capacity)")

        ccs = df_bins['cc'].values.tolist()
        axes['cc'].plot(range(len(ccs)), ccs)

        pp.show()