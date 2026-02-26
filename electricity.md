
# Electricity Sector
 electricity
        
##Commodity
| name | description | type | units |
|:---|:---|:---|:---|
| E\_bio\_m | (PJ) biomass for electricity generation | annual commodity | nan |
| E\_ng | (PJ) natural gas for electricity generation | annual commodity | nan |
| E\_coal | (PJ) coal for electricity generation | annual commodity | nan |
| E\_oil | (PJ) oil for electricity generation | annual commodity | nan |
| E\_dsl | (PJ) diesel for electricity generation | annual commodity | nan |
| E\_u\_nat | (PJ) uranium (natural) for electricity generation | annual commodity | nan |
| E\_u\_enr | (PJ) uranium (enriched) for electricity generation | annual commodity | nan |
| E\_gsl | (PJ) gasoline for electricity generation | annual commodity | nan |
| E\_bio\_g | (PJ) biogas for electricity generation | annual commodity | nan |
| E\_gsl | Gasoline for the electric power sector | annual commodity | nan |
| E\_bio\_m | Solid bioenergy for the electric power sector | annual commodity | nan |
| E\_ng | Natural gas for the electric power sector | annual commodity | nan |
| E\_coal | Coal for the electric power sector | annual commodity | nan |
| E\_oil | Oil for the electric power sector | annual commodity | nan |
| E\_dsl | Diesel for the electric power sector | annual commodity | nan |
| E\_u\_nat | Natural uranium for the electric power sector | annual commodity | nan |
| E\_u\_enr | Enriched uranium for the electric power sector | annual commodity | nan |
| E\_bio\_g | Gaseous bioenergy for the electric power sector | annual commodity | nan |
| E\_D\_elc\_int\_ab | (PJ) demanded for exogenous electricity from boundary interties | demand commodity | (PJ) |
| E\_D\_elc\_int\_sk | (PJ) demanded for exogenous electricity from boundary interties | demand commodity | (PJ) |
| E\_D\_elc\_int\_mb | (PJ) demanded for exogenous electricity from boundary interties | demand commodity | (PJ) |
| E\_D\_elc\_int\_on | (PJ) demanded for exogenous electricity from boundary interties | demand commodity | (PJ) |
| E\_D\_elc\_int\_ns | (PJ) demanded for exogenous electricity from boundary interties | demand commodity | (PJ) |
| E\_D\_elc\_int\_nb | (PJ) demanded for exogenous electricity from boundary interties | demand commodity | (PJ) |
| E\_D\_elc\_int\_usa | (PJ) demanded for exogenous electricity from boundary interties | demand commodity | (PJ) |
| E\_D\_elc\_int\_bc | (PJ) demanded for exogenous electricity from boundary interties | demand commodity | (PJ) |
| E\_D\_elc | (PJ) demand for electricity | demand commodity | (PJ) |
| E\_D\_elc\_int\_qc | (PJ) demanded for exogenous electricity from boundary interties | demand commodity | (PJ) |
| E\_D\_elc\_int\_pei | (PJ) demanded for exogenous electricity from boundary interties | demand commodity | (PJ) |
| E\_elc\_dem | (PJ) demand-side electricity | physical commodity | nan |
| E\_elc\_tx | (PJ) transmission-side electricity | physical commodity | nan |
| E\_hyd\_mly\_stor | (PJ) available generation stored in monthly hydro reservoir | physical commodity | nan |
| E\_elc\_tx\_ng\_cc | (PJ) intermediate commodity going either to E\_NG\_CCS\_RFIT\_95 or straight to E\_elc\_tx | physical commodity | nan |
| E\_elc\_tx\_coal | (PJ) intermediate commodity going either to E\_COAL\_CCS\_RFIT\_95 or straight to E\_elc\_tx | physical commodity | nan |
| E\_elc\_dx | (PJ) distribution-side electricity | physical commodity | nan |
| E\_elc\_dem | Electricity (direct use) for the electric power sector | physical commodity | nan |
| E\_ethos | (PJ) dummy commodity | source commodity | nan |

## Technology



| tech | description | unlim_cap | annual | reserve | curtail | flex |
|:---|:---|---:|---:|---:|---:|---:|
| F\_E\_BIO\_G | Gaseous bioenergy distribution from fuel sector to electric power sector | 1 | 1 | 0 | 0 | 0 |
| F\_E\_BIO\_M | Solid bioenergy distribution from fuel sector to electric power sector | 1 | 1 | 0 | 0 | 0 |
| F\_E\_NG | Natural gas distribution from fuel sector to electric power sector | 1 | 1 | 0 | 0 | 0 |
| F\_E\_COAL | Coal distribution from fuel sector to electric power sector | 1 | 1 | 0 | 0 | 0 |
| F\_E\_OIL | Oil distribution from fuel sector to electric power sector | 1 | 1 | 0 | 0 | 0 |
| F\_E\_DSL | Diesel distribution from fuel sector to electric power sector | 1 | 1 | 0 | 0 | 0 |
| F\_E\_U\_NAT | Natural uranium distribution from fuel sector to electric power sector | 1 | 1 | 0 | 0 | 0 |
| F\_E\_U\_ENR | Enriched uranium distribution from fuel sector to electric power sector | 1 | 1 | 0 | 0 | 0 |
| F\_E\_GSL | Gasoline distribution from fuel sector to electric power sector | 1 | 1 | 0 | 0 | 0 |
| E\_ELC\_DEM | provincial electricity demand | 1 | 1 | 0 | 0 | 0 |
| E\_ELC\_TX\_to\_DX | transmission-side electricity to distribution-side electricity | 1 | 0 | 0 | 0 | 0 |
| E\_ELC\_DX\_to\_DEM | distribution-side electricity to demand-side electricity | 1 | 0 | 0 | 0 | 0 |
| E\_GSL\_CT-EXS | gasoline combustion turbine generation - existing | 0 | 0 | 1 | 0 | 0 |
| E\_OIL\_ST-EXS | oil steam turbine generation - existing | 0 | 0 | 1 | 0 | 0 |
| E\_OIL\_CT-EXS | oil combustion turbine generation - existing | 0 | 0 | 1 | 0 | 0 |
| E\_NUC\_CANDU-EXS | nuclear candu generation - existing | 0 | 0 | 1 | 0 | 0 |
| E\_DSL\_CT-EXS | diesel combustion turbine generation - existing | 0 | 0 | 1 | 0 | 0 |
| E\_HYD\_MLY-EXS | hydroelectric generation with monthly reservoir - existing | 0 | 0 | 1 | 0 | 0 |
| E\_HYD\_ROR-EXS | hydroelectric run-of-river generation - existing | 0 | 0 | 1 | 1 | 0 |
| E\_BIO\_G-EXS | biogas generation - existing | 0 | 0 | 1 | 0 | 0 |
| E\_BIO\_M-EXS | biomass generation -existing | 0 | 0 | 1 | 0 | 0 |
| E\_COAL-EXS | coal generation - existing | 0 | 0 | 1 | 0 | 0 |
| E\_COAL\_CCS-EXS | coal generation with 95% ccs -existing | 0 | 0 | 1 | 0 | 0 |
| E\_HYD\_DLY-EXS | hydroelectric generation with daily reservoir storage - existing | 0 | 0 | 1 | 0 | 0 |
| E\_NG\_CC-EXS | natural gas combined cycle generation existing | 0 | 0 | 1 | 0 | 0 |
| E\_NG\_CG-EXS | natural gas heat and power cogeneration - existing | 0 | 0 | 1 | 0 | 0 |
| E\_NG\_CT-EXS | natural gas combustion turbine generation - existing | 0 | 0 | 1 | 0 | 0 |
| E\_SOL\_PV-EXS | utility-scale solar photovoltaic generation - existing | 0 | 0 | 1 | 1 | 0 |
| E\_WND\_ON-EXS | onshore wind generation - existing | 0 | 0 | 1 | 1 | 0 |
| E\_HYD\_MLY-EXS-IN | inflow to reservoir for monthly hydroelectric generation | 0 | 0 | 0 | 0 | 0 |
| E\_BAT\_3H-EXS | utility-scale lithium-ion battery storage with 3-hour capacity - existing | 0 | 0 | 0 | 0 | 0 |
| E\_BAT\_4H-EXS | utility-scale lithium-ion battery storage with 4-hour capacity - existing | 0 | 0 | 0 | 0 | 0 |
| E\_BAT\_5H-EXS | utility-scale lithium-ion battery storage with 5-hour capacity - existing | 0 | 0 | 0 | 0 | 0 |
| E\_PUMP\_4H-EXS | hydroelectric pumped storage with 6-hour capacity - existing | 0 | 0 | 0 | 0 | 0 |
| E\_BAT\_2H-EXS | utility-scale lithium-ion battery storage with 2-hour capacity - existing | 0 | 0 | 0 | 0 | 0 |
| E\_BAT\_1H-EXS | utility-scale lithium-ion battery storage with 1-hour capacity - existing | 0 | 0 | 0 | 0 | 0 |
| E\_BIO\_M-NEW | biomass generation - new | 0 | 0 | 1 | 0 | 0 |
| E\_NG\_CC-NEW | natural gas combined cycle generation - new | 0 | 0 | 1 | 0 | 0 |
| E\_NG\_CCS-NEW | natural gas combined cycle generation with 95% ccs - new | 0 | 0 | 1 | 0 | 0 |
| E\_NG\_CT-NEW | natural gas combustion turbine generation - new | 0 | 0 | 1 | 0 | 0 |
| E\_NUC\_PWR-NEW | nuclear pressurised water reactor generation - new | 0 | 0 | 1 | 0 | 0 |
| E\_NUC\_SMR-NEW | nuclear small modular reactor generation - new | 0 | 0 | 1 | 0 | 0 |
| E\_SOL\_PV-NEW-1 | utility-scale solar photovoltaic generation - new | 0 | 0 | 1 | 1 | 0 |
| E\_SOL\_PV-NEW-2 | utility-scale solar photovoltaic generation - new | 0 | 0 | 1 | 1 | 0 |
| E\_SOL\_PV-NEW-3 | utility-scale solar photovoltaic generation - new | 0 | 0 | 1 | 1 | 0 |
| E\_SOL\_PV-NEW-4 | utility-scale solar photovoltaic generation - new | 0 | 0 | 1 | 1 | 0 |
| E\_SOL\_PV-NEW-5 | utility-scale solar photovoltaic generation - new | 0 | 0 | 1 | 1 | 0 |
| E\_WND\_ON-NEW-1 | onshore wind generation - new | 0 | 0 | 1 | 1 | 0 |
| E\_WND\_ON-NEW-2 | onshore wind generation - new | 0 | 0 | 1 | 1 | 0 |
| E\_WND\_ON-NEW-3 | onshore wind generation - new | 0 | 0 | 1 | 1 | 0 |
| E\_WND\_ON-NEW-4 | onshore wind generation - new | 0 | 0 | 1 | 1 | 0 |
| E\_WND\_ON-NEW-5 | onshore wind generation - new | 0 | 0 | 1 | 1 | 0 |
| E\_WND\_ON-NEW-6 | onshore wind generation - new | 0 | 0 | 1 | 1 | 0 |
| E\_WND\_ON-NEW-7 | onshore wind generation - new | 0 | 0 | 1 | 1 | 0 |
| E\_WND\_ON-NEW-8 | onshore wind generation - new | 0 | 0 | 1 | 1 | 0 |
| E\_WND\_ON-NEW-9 | onshore wind generation - new | 0 | 0 | 1 | 1 | 0 |
| E\_WND\_ON-NEW-10 | onshore wind generation - new | 0 | 0 | 1 | 1 | 0 |
| E\_WND\_ON-NEW-11 | onshore wind generation - new | 0 | 0 | 1 | 1 | 0 |
| E\_WND\_ON-NEW-12 | onshore wind generation - new | 0 | 0 | 1 | 1 | 0 |
| E\_WND\_ON-NEW-13 | onshore wind generation - new | 0 | 0 | 1 | 1 | 0 |
| E\_BAT\_2H-NEW | utility-scale lithium-ion battery storage with 2-hour capacity - new | 0 | 0 | 0 | 0 | 0 |
| E\_BAT\_4H-NEW | utility-scale lithium-ion battery storage with 4-hour capacity - new | 0 | 0 | 0 | 0 | 0 |
| E\_COAL\_CCS\_RFIT\_90 | 90% ccs retrofit for coal generation | 0 | 0 | 0 | 0 | 0 |
| E\_COAL\_RFIT\_BYPASS | dummy bypass for ccs retrofit | 1 | 0 | 0 | 0 | 0 |
| E\_COAL\_CCS\_RFIT\_95 | 95% ccs retrofit for coal generation | 0 | 0 | 0 | 0 | 0 |
| E\_NG\_CCS\_RFIT\_90 | 90% ccs retrofit for natural gas combined cycle generation | 0 | 0 | 0 | 0 | 0 |
| E\_NG\_CC\_RFIT\_BYPASS | dummy bypass for ccs retrofit | 1 | 0 | 0 | 0 | 0 |
| E\_NG\_CCS\_RFIT\_95 | 95% ccs retrofit for natural gas combustion turbine generation | 0 | 0 | 0 | 0 | 0 |
| E\_INT\_OUT-BC | boundary intertie leaving the model - treated as a demand - AB out to BC | 1 | 1 | 0 | 0 | 0 |
| E\_INT\_IN-BC | boundary intertie entering the model - treated as a variable generator - BC into AB | 0 | 0 | 0 | 1 | 0 |
| E\_INT\_OUT-AB | boundary intertie leaving the model - treated as a demand - BC out to AB | 1 | 1 | 0 | 0 | 0 |
| E\_INT\_IN-AB | boundary intertie entering the model - treated as a variable generator - AB into BC | 0 | 0 | 0 | 1 | 0 |
| E\_INT\_OUT-SK | boundary intertie leaving the model - treated as a demand - AB out to SK | 1 | 1 | 0 | 0 | 0 |
| E\_INT\_IN-SK | boundary intertie entering the model - treated as a variable generator - SK into AB | 0 | 0 | 0 | 1 | 0 |
| E\_INT\_OUT-AB | boundary intertie leaving the model - treated as a demand - SK out to AB | 1 | 1 | 0 | 0 | 0 |
| E\_INT\_IN-AB | boundary intertie entering the model - treated as a variable generator - AB into SK | 0 | 0 | 0 | 1 | 0 |
| E\_INT\_IN-USA | boundary intertie entering the model - treated as a variable generator - USA into AB | 0 | 0 | 0 | 1 | 0 |
| E\_INT\_OUT-USA | boundary intertie leaving the model - treated as a demand - BC out to USA | 1 | 1 | 0 | 0 | 0 |
| E\_INT\_IN-USA | boundary intertie entering the model - treated as a variable generator - USA into BC | 0 | 0 | 0 | 1 | 0 |
| E\_INT\_OUT-ON | boundary intertie leaving the model - treated as a demand - MB out to ON | 1 | 1 | 0 | 0 | 0 |
| E\_INT\_IN-ON | boundary intertie entering the model - treated as a variable generator - ON into MB | 0 | 0 | 0 | 1 | 0 |
| E\_INT\_OUT-MB | boundary intertie leaving the model - treated as a demand - ON out to MB | 1 | 1 | 0 | 0 | 0 |
| E\_INT\_IN-MB | boundary intertie entering the model - treated as a variable generator - MB into ON | 0 | 0 | 0 | 1 | 0 |
| E\_INT\_OUT-SK | boundary intertie leaving the model - treated as a demand - MB out to SK | 1 | 1 | 0 | 0 | 0 |
| E\_INT\_IN-SK | boundary intertie entering the model - treated as a variable generator - SK into MB | 0 | 0 | 0 | 1 | 0 |
| E\_INT\_OUT-MB | boundary intertie leaving the model - treated as a demand - SK out to MB | 1 | 1 | 0 | 0 | 0 |
| E\_INT\_IN-MB | boundary intertie entering the model - treated as a variable generator - MB into SK | 0 | 0 | 0 | 1 | 0 |
| E\_INT\_OUT-NS | boundary intertie leaving the model - treated as a demand - NB out to NS | 1 | 1 | 0 | 0 | 0 |
| E\_INT\_IN-NS | boundary intertie entering the model - treated as a variable generator - NS into NB | 0 | 0 | 0 | 1 | 0 |
| E\_INT\_OUT-NB | boundary intertie leaving the model - treated as a demand - NS out to NB | 1 | 1 | 0 | 0 | 0 |
| E\_INT\_IN-NB | boundary intertie entering the model - treated as a variable generator - NB into NS | 0 | 0 | 0 | 1 | 0 |
| E\_INT\_OUT-PEI | boundary intertie leaving the model - treated as a demand - NB out to PEI | 1 | 1 | 0 | 0 | 0 |
| E\_INT\_IN-PEI | boundary intertie entering the model - treated as a variable generator - PEI into NB | 0 | 0 | 0 | 1 | 0 |
| E\_INT\_OUT-NB | boundary intertie leaving the model - treated as a demand - PEI out to NB | 1 | 1 | 0 | 0 | 0 |
| E\_INT\_IN-NB | boundary intertie entering the model - treated as a variable generator - NB into PEI | 0 | 0 | 0 | 1 | 0 |
| E\_INT\_OUT-QC | boundary intertie leaving the model - treated as a demand - NB out to QC | 1 | 1 | 0 | 0 | 0 |
| E\_INT\_IN-QC | boundary intertie entering the model - treated as a variable generator - QC into NB | 0 | 0 | 0 | 1 | 0 |
| E\_INT\_OUT-NB | boundary intertie leaving the model - treated as a demand - QC out to NB | 1 | 1 | 0 | 0 | 0 |
| E\_INT\_IN-NB | boundary intertie entering the model - treated as a variable generator - NB into QC | 0 | 0 | 0 | 1 | 0 |
| E\_INT\_OUT-USA | boundary intertie leaving the model - treated as a demand - NB out to USA | 1 | 1 | 0 | 0 | 0 |
| E\_INT\_IN-USA | boundary intertie entering the model - treated as a variable generator - USA into NB | 0 | 0 | 0 | 1 | 0 |
| E\_INT\_OUT-QC | boundary intertie leaving the model - treated as a demand - ON out to QC | 1 | 1 | 0 | 0 | 0 |
| E\_INT\_IN-QC | boundary intertie entering the model - treated as a variable generator - QC into ON | 0 | 0 | 0 | 1 | 0 |
| E\_INT\_OUT-ON | boundary intertie leaving the model - treated as a demand - QC out to ON | 1 | 1 | 0 | 0 | 0 |
| E\_INT\_IN-ON | boundary intertie entering the model - treated as a variable generator - ON into QC | 0 | 0 | 0 | 1 | 0 |
| E\_INT\_OUT-USA | boundary intertie leaving the model - treated as a demand - ON out to USA | 1 | 1 | 0 | 0 | 0 |
| E\_INT\_IN-USA | boundary intertie entering the model - treated as a variable generator - USA into ON | 0 | 0 | 0 | 1 | 0 |
| E\_INT\_OUT-USA | boundary intertie leaving the model - treated as a demand - QC out to USA | 1 | 1 | 0 | 0 | 0 |
| E\_INT\_IN-USA | boundary intertie entering the model - treated as a variable generator - USA into QC | 0 | 0 | 0 | 1 | 0 |
| E\_INT\_OUT-USA | boundary intertie leaving the model - treated as a demand - SK out to USA | 1 | 1 | 0 | 0 | 0 |
| E\_INT\_IN-USA | boundary intertie entering the model - treated as a variable generator - USA into SK | 0 | 0 | 0 | 1 | 0 |
| E\_INT | endogenous inter-regional intertie | 0 | 0 | 0 | 0 | 0 |
